from typing import Dict, Any
import threading
from datetime import datetime
from mcp_sandbox.utils.config import PYPI_INDEX_URL, INSTALL_TIMEOUT_SECONDS


class SandboxPackageMixin:
    def _install_package_sync(
        self, sandbox_id: str, package_name: str
    ) -> Dict[str, Any]:
        from mcp_sandbox.utils.config import logger

        status_key = f"{sandbox_id}:{package_name}"
        try:
            with self._get_running_sandbox(sandbox_id) as sandbox:
                pip_index_url = PYPI_INDEX_URL
                pip_index_opt = f" --index-url {pip_index_url}" if pip_index_url else ""
                logger.info(
                    f"Installing {package_name} (index={pip_index_url or 'PyPI default'}, "
                    f"timeout={INSTALL_TIMEOUT_SECONDS}s)"
                )
                exec_result = sandbox.exec_run(
                    cmd=[
                        "timeout",
                        "--signal=KILL",
                        str(INSTALL_TIMEOUT_SECONDS),
                        "sh",
                        "-c",
                        f"uv pip install{pip_index_opt} {package_name}",
                    ],
                    stdout=True,
                    stderr=True,
                    privileged=False,
                )
                exit_code = exec_result.exit_code
                output = exec_result.output.decode("utf-8")
                logger.info(f"Package installation output: {output}")
                logger.info(f"Exit code: {exit_code}")
                if exit_code == 0:
                    status = {
                        "status": "success",
                        "message": f"Successfully installed {package_name}",
                        "complete": True,
                        "success": True,
                        "end_time": datetime.now(),
                    }
                    self.package_install_status[status_key] = status
                    return status
                else:
                    status = {
                        "status": "failed",
                        "message": f"Failed to install {package_name}: {output}",
                        "stderr": output,
                        "complete": True,
                        "success": False,
                        "end_time": datetime.now(),
                    }
                    self.package_install_status[status_key] = status
                    return status
        except Exception as e:
            logger.error(
                f"Failed to install package {package_name} for sandbox {sandbox_id}: {e}",
                exc_info=True,
            )
            error_message = str(e)
            if hasattr(e, "stderr") and e.stderr:
                stderr = (
                    e.stderr.decode("utf-8")
                    if isinstance(e.stderr, bytes)
                    else str(e.stderr)
                )
                error_message = f"{error_message}\nDetails: {stderr}"
            status = {
                "status": "failed",
                "message": f"Error: {error_message}",
                "stderr": error_message,
                "complete": True,
                "success": False,
                "end_time": datetime.now(),
            }
            self.package_install_status[status_key] = status
            return status

    def install_package(self, sandbox_id: str, package_name: str) -> Dict[str, Any]:
        from mcp_sandbox.utils.config import logger

        error = self.verify_sandbox_exists(sandbox_id)
        if error:
            return error
        logger.info(
            f"Starting installation of package {package_name} for sandbox {sandbox_id}"
        )
        status_key = f"{sandbox_id}:{package_name}"
        if status_key in self.package_install_status:
            status = self.package_install_status[status_key]
            if status["status"] == "installing" and not status["complete"]:
                return {
                    "success": None,
                    "status": "installing",
                    "message": f"Package {package_name} installation already in progress",
                }
        self.package_install_status[status_key] = {
            "status": "installing",
            "start_time": datetime.now(),
            "message": f"Installing {package_name}...",
            "complete": False,
        }
        install_thread = threading.Thread(
            target=self._install_package_sync,
            args=(sandbox_id, package_name),
            daemon=True,
        )
        install_thread.start()
        try:
            import time

            start_time = time.time()
            max_wait = 5
            while time.time() - start_time < max_wait:
                if status_key in self.package_install_status:
                    status = self.package_install_status[status_key]
                    if status.get("complete", False):
                        logger.info(
                            f"Package {package_name} installed within 5 seconds: {status}"
                        )
                        return status
                time.sleep(0.1)
            logger.info(
                f"Installation of {package_name} is taking longer than 5 seconds, continuing in background"
            )
            return {
                "success": None,
                "status": "installing",
                "message": f"Installation of {package_name} in progress. Use check_package_status to monitor progress.",
            }
        except Exception as e:
            logger.error(f"Error while monitoring installation: {e}", exc_info=True)
            return {
                "success": None,
                "status": "installing",
                "message": f"Installation of {package_name} in progress. Use check_package_status to monitor progress.",
            }

    def check_package_status(
        self, sandbox_id: str, package_name: str
    ) -> Dict[str, Any]:
        from mcp_sandbox.utils.config import logger

        error = self.verify_sandbox_exists(sandbox_id)
        if error:
            return error
        status_key = f"{sandbox_id}:{package_name}"
        if status_key in self.package_install_status:
            status = self.package_install_status[status_key]
            if status.get("complete", False):
                return status
        if (
            status_key in self.package_install_status
            and self.package_install_status[status_key]["status"] == "installing"
        ):
            try:
                import time

                start_time = time.time()
                max_wait = 5
                while time.time() - start_time < max_wait:
                    status = self.package_install_status[status_key]
                    if status.get("complete", False):
                        logger.info(
                            f"Package {package_name} installation completed within check window"
                        )
                        return status
                    time.sleep(0.1)
                logger.info(
                    f"Package {package_name} installation still in progress after 5 seconds"
                )
                elapsed_time = datetime.now() - status["start_time"]
                status["elapsed_seconds"] = elapsed_time.total_seconds()
                return status
            except Exception as e:
                logger.error(
                    f"Error while waiting for package status: {e}", exc_info=True
                )
        if status_key not in self.package_install_status:
            try:
                with self._get_running_sandbox(sandbox_id) as sandbox:
                    exec_result = sandbox.exec_run(
                        cmd=f"uv pip list | grep -i {package_name}",
                        stdout=True,
                        stderr=True,
                        privileged=False,
                    )
                    output = exec_result.output.decode("utf-8").strip()
                    if output and package_name.lower() in output.lower():
                        return {
                            "status": "success",
                            "message": f"Package {package_name} is already installed",
                            "complete": True,
                            "success": True,
                        }
                    else:
                        return {
                            "status": "not_found",
                            "message": f"No installation record found for {package_name}",
                            "complete": True,
                            "success": False,
                        }
            except Exception as e:
                logger.error(
                    f"Error checking if package {package_name} is installed: {e}"
                )
                return {
                    "status": "error",
                    "message": f"Error checking package status: {str(e)}",
                    "complete": True,
                    "success": False,
                }
        status = self.package_install_status[status_key]
        if status["status"] == "installing" and not status.get("complete", False):
            elapsed_time = datetime.now() - status["start_time"]
            status["elapsed_seconds"] = elapsed_time.total_seconds()
        return status

    def list_installed_packages(self, sandbox_id: str) -> list:
        import re
        import json
        from mcp_sandbox.utils.config import logger

        try:
            # 使用get_container_by_sandbox_id方法获取容器
            sandbox, error = self.get_container_by_sandbox_id(sandbox_id)
            if error:
                logger.warning(f"[list_installed_packages] {error['message']}")
                return []

            # 确保sandbox是一个有效的容器对象
            if not sandbox:
                logger.warning(
                    f"[list_installed_packages] No valid container for sandbox: {sandbox_id}"
                )
                return []

            logger.info(
                f"[list_installed_packages] Using container for sandbox: {sandbox_id}"
            )
            exec_result = sandbox.exec_run("uv pip list --format=json")
            output = exec_result.output.decode()
            match = re.search(r"\[.*\]", output, re.DOTALL)
            if match:
                json_str = match.group(0)
                try:
                    packages = json.loads(json_str)
                    logger.info(
                        f"[list_installed_packages] Successfully listed {len(packages)} packages for sandbox {sandbox_id}"
                    )
                    return packages
                except Exception as parse_err:
                    logger.error(
                        f"[list_installed_packages] JSON parse error: {parse_err} | json_str={json_str!r}"
                    )
                    return []
            else:
                logger.warning(
                    f"[list_installed_packages] No JSON array found in output: {output!r}"
                )
                return []
        except Exception as e:
            logger.error(
                f"[list_installed_packages] Error listing packages in {sandbox_id}: {e}",
                exc_info=True,
            )
            return []
