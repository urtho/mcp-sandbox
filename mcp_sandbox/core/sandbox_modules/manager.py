import uuid
import json
import secrets
import threading
from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from pathlib import Path
import hashlib
from contextlib import contextmanager
from mcp_sandbox.utils.config import (
    logger,
    DEFAULT_DOCKER_IMAGE,
    GLOBAL_SANDBOX_LIMIT,
    PER_SESSION_SANDBOX_LIMIT,
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SANDBOX_NETWORK,
    TMP_DIR_SIZE,
    RESULTS_DIR_SIZE,
    PIDS_LIMIT,
    NOFILE_SOFT,
    NOFILE_HARD,
    SANDBOX_UID,
    SANDBOX_GID,
    config,
)
from mcp_sandbox.utils.task_manager import PeriodicTaskManager
import docker


SANDBOX_LABEL_KEY = "python-sandbox"
SANDBOX_LABEL_FILTER = {"label": SANDBOX_LABEL_KEY}
LABEL_RESUME_TOKEN = "mcp-sandbox.resume-token"
LABEL_DOWNLOAD_TOKEN = "mcp-sandbox.download-token"
LABEL_OWNER_SESSION = "mcp-sandbox.owner-session"


class SandboxManager:
    """Manage Sandboxes with automatic creation"""

    def __init__(self, base_image: str = DEFAULT_DOCKER_IMAGE):
        self.base_image = base_image
        self.sandbox_last_used: Dict[str, datetime] = {}
        self.session_sandbox_map: Dict[str, str] = {}
        self.package_install_status: Dict[str, Dict[str, Any]] = {}
        # Per-sandbox locks serialize concurrent tool calls on the same sandbox
        # so the shared /tmp/code_to_run.py path is never clobbered.
        self._sandbox_locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        try:
            self.sandbox_client = docker.from_env()
            logger.info("Sandbox client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Sandbox client: {e}", exc_info=True)
            raise
        self._ensure_sandbox_image()
        self._load_sandbox_records()
        self._start_idle_enforcer()
        logger.info(
            "SandboxManager initialized "
            f"(image={self.base_image}, network={SANDBOX_NETWORK}, "
            f"global_limit={GLOBAL_SANDBOX_LIMIT}, session_limit={PER_SESSION_SANDBOX_LIMIT})"
        )

    @contextmanager
    def sandbox_lock(self, sandbox_id: str):
        """Acquire an exclusive lock on a single sandbox for the duration of a tool call."""
        with self._locks_guard:
            lock = self._sandbox_locks.setdefault(sandbox_id, threading.Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _start_idle_enforcer(self) -> None:
        """Start background task that removes sandboxes idle beyond the timeout"""
        if SANDBOX_IDLE_TIMEOUT_SECONDS <= 0:
            logger.info("Sandbox idle enforcement disabled (timeout <= 0)")
            return
        interval = max(30, min(300, SANDBOX_IDLE_TIMEOUT_SECONDS // 6 or 60))
        PeriodicTaskManager.start_task(
            self.cleanup_idle_sandboxes,
            interval,
            f"sandbox idle enforcer (timeout={SANDBOX_IDLE_TIMEOUT_SECONDS}s)",
        )

    def cleanup_idle_sandboxes(self) -> None:
        """Remove sandbox containers that have been idle longer than the timeout"""
        try:
            containers = self.sandbox_client.containers.list(
                all=True, filters=SANDBOX_LABEL_FILTER
            )
        except Exception as e:
            logger.error(f"Idle enforcer: failed to list containers: {e}")
            return

        now = datetime.now()
        for container in containers:
            last_used = self.sandbox_last_used.get(container.id)
            if last_used is None:
                # Untracked container — adopt it so it gets a grace period before removal.
                self.sandbox_last_used[container.id] = now
                continue
            idle_seconds = (now - last_used).total_seconds()
            if idle_seconds < SANDBOX_IDLE_TIMEOUT_SECONDS:
                continue
            logger.info(
                f"Idle enforcer: removing sandbox {container.id} "
                f"(idle {idle_seconds:.0f}s >= {SANDBOX_IDLE_TIMEOUT_SECONDS}s)"
            )
            try:
                if container.status == "running":
                    container.stop(timeout=0)
                container.remove(force=True)
            except Exception as e:
                logger.error(
                    f"Idle enforcer: failed to remove {container.id}: {e}",
                    exc_info=True,
                )
                continue
            self._forget_sandbox(container.id)

    def _forget_sandbox(self, sandbox_id: str) -> None:
        """Drop in-memory bookkeeping for a sandbox that no longer exists"""
        self.sandbox_last_used.pop(sandbox_id, None)
        for session_id, sb_id in list(self.session_sandbox_map.items()):
            if sb_id == sandbox_id:
                del self.session_sandbox_map[session_id]
        with self._locks_guard:
            self._sandbox_locks.pop(sandbox_id, None)

    def _ensure_sandbox_image(self):
        """Ensure our custom Sandbox image exists, build it if needed"""
        custom_image_name = DEFAULT_DOCKER_IMAGE
        sandboxfile_path = Path(
            config["docker"].get("dockerfile_path", "Dockerfile")
        ).resolve()
        build_info_file = Path(
            config["docker"].get("build_info_file", ".docker_build_info")
        ).resolve()
        check_changes = config["docker"].get("check_dockerfile_changes", True)
        image_exists = True
        try:
            self.sandbox_client.images.get(custom_image_name)
            logger.info(f"Sandbox image exists: {custom_image_name}")
        except docker.errors.ImageNotFound:
            image_exists = False
            logger.info(f"Sandbox image not found: {custom_image_name}")
        need_rebuild = not image_exists
        if image_exists and check_changes and sandboxfile_path.exists():
            current_hash = self._get_file_hash(sandboxfile_path)
            previous_hash = None
            if build_info_file.exists():
                try:
                    with open(build_info_file, "r") as f:
                        build_info = json.load(f)
                        previous_hash = build_info.get("dockerfile_hash")
                        logger.info(
                            f"Found previous build info with hash: {previous_hash}"
                        )
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Could not read build info file: {e}")
            if previous_hash != current_hash:
                logger.info(
                    f"Sandboxfile has changed (Previous: {previous_hash}, Current: {current_hash})"
                )
                need_rebuild = True
        if need_rebuild:
            if not sandboxfile_path.exists():
                logger.error("Sandboxfile not found, falling back to base image")
                return
            try:
                logger.info(f"Building Sandbox image: {custom_image_name}")
                _, logs = self.sandbox_client.images.build(
                    path=str(sandboxfile_path.parent),
                    dockerfile=str(sandboxfile_path.name),
                    tag=custom_image_name,
                    rm=True,
                    forcerm=True,
                )
                for log in logs:
                    if "stream" in log:
                        logger.info(log["stream"].strip())
                if check_changes:
                    build_info = {
                        "dockerfile_hash": self._get_file_hash(sandboxfile_path),
                        "build_time": datetime.now().isoformat(),
                        "image_name": custom_image_name,
                    }
                    with open(build_info_file, "w") as f:
                        json.dump(build_info, f)
                        logger.info(f"Saved build info to {build_info_file}")
                self.base_image = custom_image_name
                logger.info(f"Successfully built Sandbox image: {custom_image_name}")
            except Exception as e:
                logger.error(f"Failed to build Sandbox image: {e}", exc_info=True)

    def _get_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of a file to detect changes"""
        if not file_path.exists():
            return ""
        try:
            with open(file_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            return file_hash
        except IOError as e:
            logger.error(f"Error reading file for hashing: {e}")
            return ""

    def _load_sandbox_records(self) -> None:
        """Seed the last-used clock for existing containers discovered at startup"""
        try:
            sandboxes = self.sandbox_client.containers.list(
                all=True, filters=SANDBOX_LABEL_FILTER
            )
            for sandbox in sandboxes:
                self.sandbox_last_used[sandbox.id] = datetime.now()
                logger.info(f"Loaded existing sandbox: {sandbox.id}")
        except Exception as e:
            logger.error(f"Failed to load existing sandboxes: {e}", exc_info=True)

    def _count_sandboxes(self) -> int:
        """Current number of python-sandbox containers known to Docker"""
        try:
            return len(
                self.sandbox_client.containers.list(
                    all=True, filters=SANDBOX_LABEL_FILTER
                )
            )
        except Exception as e:
            logger.error(f"Failed to count sandboxes: {e}")
            return 0

    def _count_session_sandboxes(self, session_id: str) -> int:
        """Sandboxes created by this MCP session (still alive)"""
        try:
            containers = self.sandbox_client.containers.list(
                all=True,
                filters={"label": f"{LABEL_OWNER_SESSION}={session_id}"},
            )
            return len(containers)
        except Exception as e:
            logger.error(f"Failed to count session sandboxes: {e}")
            return 0

    def _label(self, container, key: str) -> Optional[str]:
        try:
            return container.labels.get(key)
        except Exception:
            return None

    def get_resume_token(self, container) -> Optional[str]:
        return self._label(container, LABEL_RESUME_TOKEN)

    def get_download_token(self, container) -> Optional[str]:
        return self._label(container, LABEL_DOWNLOAD_TOKEN)

    def create_sandbox(self, owner_session_id: str = "") -> Tuple[str, str, str]:
        """Create a hardened sandbox container.

        Returns (sandbox_id, resume_token, download_token).
        """
        sandbox_name = f"python-sandbox-{str(uuid.uuid4())[:8]}"
        resume_token = secrets.token_urlsafe(32)
        download_token = secrets.token_urlsafe(24)
        # tmpfs needs uid/gid to be writable by the image's non-root user
        # (jovyan @ 1000:100 in jupyter/scipy-notebook). /tmp keeps the default
        # 1777 sticky-bit mode so `pip`/`uv` build dirs work for any UID.
        results_opts = (
            f"rw,size={RESULTS_DIR_SIZE},nosuid,nodev,noexec,"
            f"uid={SANDBOX_UID},gid={SANDBOX_GID},mode=755"
        )
        tmpfs_opts = {
            "/tmp": f"rw,size={TMP_DIR_SIZE},nosuid,nodev",
            "/app/results": results_opts,
        }
        labels = {
            SANDBOX_LABEL_KEY: "true",
            LABEL_RESUME_TOKEN: resume_token,
            LABEL_DOWNLOAD_TOKEN: download_token,
        }
        if owner_session_id:
            labels[LABEL_OWNER_SESSION] = owner_session_id
        ulimits = [
            docker.types.Ulimit(name="nofile", soft=NOFILE_SOFT, hard=NOFILE_HARD),
        ]
        try:
            sandbox = self.sandbox_client.containers.create(
                image=self.base_image,
                name=sandbox_name,
                detach=True,
                working_dir="/app/results",
                labels=labels,
                mem_limit="1g",
                memswap_limit="1g",
                nano_cpus=1_000_000_000,
                pids_limit=PIDS_LIMIT,
                ulimits=ulimits,
                tmpfs=tmpfs_opts,
                network_mode=SANDBOX_NETWORK,
                privileged=False,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
            )
            sandbox.start()
            logger.info(
                f"Created sandbox {sandbox.id} (name={sandbox_name}, "
                f"network={SANDBOX_NETWORK}, session={owner_session_id or '-'})"
            )
            self.sandbox_last_used[sandbox.id] = datetime.now()
            return sandbox.id, resume_token, download_token
        except Exception as e:
            logger.error(f"Failed to create sandbox: {e}", exc_info=True)
            raise

    def create_user_sandbox(self, session_id: str = "") -> dict:
        """Create a new sandbox, subject to the global and per-session caps.

        Returns a dict containing `sandbox_id`, `resume_token`, and
        `download_token`. The caller MUST show the tokens to the model and
        NEVER echo them in untrusted contexts.
        """
        total = self._count_sandboxes()
        if total >= GLOBAL_SANDBOX_LIMIT:
            logger.warning(
                f"Global sandbox limit reached ({total}/{GLOBAL_SANDBOX_LIMIT})"
            )
            return {
                "error": True,
                "message": (
                    f"Global limit of {GLOBAL_SANDBOX_LIMIT} sandboxes reached. "
                    "Delete an existing sandbox before creating a new one."
                ),
            }
        if session_id and PER_SESSION_SANDBOX_LIMIT > 0:
            mine = self._count_session_sandboxes(session_id)
            if mine >= PER_SESSION_SANDBOX_LIMIT:
                return {
                    "error": True,
                    "message": (
                        f"Per-session limit of {PER_SESSION_SANDBOX_LIMIT} "
                        "sandboxes reached for this MCP session."
                    ),
                }
        try:
            sandbox_id, resume_token, download_token = self.create_sandbox(
                owner_session_id=session_id
            )
            return {
                "sandbox_id": sandbox_id,
                "resume_token": resume_token,
                "download_token": download_token,
                "status": "active",
            }
        except Exception as e:
            logger.error(f"Error creating sandbox: {e}", exc_info=True)
            return {"error": True, "message": str(e)}

    def get_or_create_session_sandbox(self, session_id: str) -> dict:
        """Return the sandbox bound to this MCP session, creating one on first use.

        On first use, the response contains `resume_token` and `download_token`;
        callers MUST surface these to the model and NEVER echo them elsewhere.
        """
        bound = self.session_sandbox_map.get(session_id)
        if bound:
            try:
                container = self.sandbox_client.containers.get(bound)
                return {
                    "sandbox_id": bound,
                    "status": "active",
                    "resumed": True,
                    # tokens omitted on refetch — caller already has them
                }
            except docker.errors.NotFound:
                logger.info(
                    f"Session {session_id} was bound to sandbox {bound} but container is gone; recreating"
                )
                self._forget_sandbox(bound)

        created = self.create_user_sandbox(session_id=session_id)
        if created.get("error"):
            return created
        self.session_sandbox_map[session_id] = created["sandbox_id"]
        created["resumed"] = False
        return created

    def bind_session_to_sandbox(
        self, session_id: str, sandbox_id: str, resume_token: str
    ) -> dict:
        """Adopt an explicitly-passed sandbox into this session.

        Requires a valid `resume_token` to defeat sandbox hijacking by anyone
        who merely learned the sandbox_id.
        """
        try:
            container = self.sandbox_client.containers.get(sandbox_id)
        except docker.errors.NotFound:
            return {"error": True, "message": f"Sandbox not found: {sandbox_id}"}
        except Exception as e:
            logger.error(f"bind_session_to_sandbox: Docker error: {e}")
            return {"error": True, "message": str(e)}

        expected = self.get_resume_token(container)
        if not expected or not resume_token or not secrets.compare_digest(
            expected, resume_token
        ):
            logger.warning(
                f"bind_session_to_sandbox: token mismatch for {sandbox_id}"
            )
            return {"error": True, "message": "Invalid resume_token"}

        self.session_sandbox_map[session_id] = container.id
        return {"sandbox_id": container.id, "status": "active", "resumed": True}

    def get_container_by_sandbox_id(self, sandbox_id: str):
        """Return (container, None) or (None, error) for a sandbox ID.

        The sandbox ID is the Docker container ID (Docker accepts unambiguous
        prefixes too).
        """
        try:
            container = self.sandbox_client.containers.get(sandbox_id)
        except docker.errors.NotFound:
            logger.warning(
                f"[get_container_by_sandbox_id] Container not found: {sandbox_id}"
            )
            return None, {
                "error": True,
                "message": f"Sandbox not found: {sandbox_id}",
            }
        except Exception as e:
            logger.error(
                f"[get_container_by_sandbox_id] Docker error for {sandbox_id}: {e}",
                exc_info=True,
            )
            return None, {"error": True, "message": str(e)}

        self.sandbox_last_used[container.id] = datetime.now()
        return container, None

    def verify_sandbox_exists(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Verify if sandbox exists, using sandbox_id instead of container ID"""
        container, error = self.get_container_by_sandbox_id(sandbox_id)
        if error:
            return error
        return None

    def delete_sandbox(self, sandbox_id: str) -> Dict[str, Any]:
        """Stop and remove a sandbox container"""
        try:
            container = self.sandbox_client.containers.get(sandbox_id)
        except docker.errors.NotFound:
            self._forget_sandbox(sandbox_id)
            return {
                "success": True,
                "message": f"Sandbox {sandbox_id} was not present; tracking cleared",
            }
        except Exception as e:
            logger.error(f"delete_sandbox: docker error for {sandbox_id}: {e}")
            return {"success": False, "message": str(e)}

        try:
            if container.status == "running":
                container.stop(timeout=0)
            container.remove(force=True)
        except Exception as e:
            logger.error(
                f"delete_sandbox: failed to remove {sandbox_id}: {e}", exc_info=True
            )
            return {"success": False, "message": str(e)}

        self._forget_sandbox(container.id)
        return {
            "success": True,
            "message": f"Sandbox {sandbox_id} deleted",
        }

    @contextmanager
    def _get_running_sandbox(self, sandbox_id: str):
        """Get running container by sandbox_id"""
        container, error = self.get_container_by_sandbox_id(sandbox_id)
        if error:
            logger.error(
                f"Failed to get container for sandbox {sandbox_id}: {error['message']}"
            )
            raise ValueError(error["message"])

        # Ensure container is running
        if container.status != "running":
            logger.info(
                f"Sandbox {sandbox_id} container is not running. Current status: {container.status}"
            )

            # If container has exited, try to get logs to understand why
            if container.status == "exited":
                try:
                    logs = container.logs(tail=50).decode("utf-8")
                    logger.info(
                        f"Logs from exited container for sandbox {sandbox_id}:\n{logs}"
                    )
                except Exception as log_err:
                    logger.error(
                        f"Failed to get logs for exited sandbox {sandbox_id}: {log_err}"
                    )

            # Try to start the container
            logger.info(f"Attempting to start container for sandbox {sandbox_id}...")
            container.start()
            container.reload()
            logger.info(f"Container for sandbox {sandbox_id} started successfully.")

        yield container
