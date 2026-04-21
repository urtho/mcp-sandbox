from typing import Dict, Any, Optional
from fastmcp import FastMCP, Context
from mcp_sandbox.core.sandbox_modules.manager import SandboxManager
from mcp_sandbox.core.sandbox_modules.file_ops import SandboxFileOpsMixin
from mcp_sandbox.core.sandbox_modules.package import SandboxPackageMixin
from mcp_sandbox.core.sandbox_modules.records import SandboxRecordsMixin
from mcp_sandbox.core.sandbox_modules.execution import SandboxExecutionMixin
from mcp_sandbox.utils.config import DEFAULT_DOCKER_IMAGE


RESUME_HINT = (
    "A sandbox is auto-created on your first tool call and bound to this MCP "
    "session. The response contains `sandbox_id` and — on first creation — "
    "`resume_token`. Save BOTH. To resume the same sandbox from another "
    "session, pass `sandbox_id` AND `resume_token` to any tool. Never share "
    "the `resume_token`: anyone who has it can take over the sandbox."
)

ENVIRONMENT_HINT = (
    "SANDBOX ENVIRONMENT: each sandbox is a container based on "
    "jupyter/scipy-notebook (Debian + Python 3.12). The following packages are "
    "pre-installed and importable directly, no install needed: numpy, pandas, "
    "scipy, matplotlib, seaborn, bokeh, altair, scikit-learn, scikit-image, "
    "statsmodels, sympy, numba, numexpr, dask, h5py, pytables, sqlalchemy, "
    "openpyxl, xlrd, beautifulsoup4, cython, cloudpickle, dill, protobuf. "
    "Write outputs (plots, CSVs, text) under /app/results — that path is a "
    "tmpfs volume capped at 1GB and served back via `file_links` in results. "
    "/tmp is a 256MB tmpfs, also writable. Each code or shell call is killed "
    "after 60s. `pip`/`uv pip install` work only if the deployment attaches a "
    "PyPI proxy to the sandbox network (see the README); by default the "
    "sandbox has NO network, so rely on the pre-installed stack. `requests` "
    "and other network clients will fail unless a proxy is configured."
)


class SandboxEnvironment(
    SandboxManager,
    SandboxFileOpsMixin,
    SandboxPackageMixin,
    SandboxRecordsMixin,
    SandboxExecutionMixin,
):
    pass


class SandboxToolsPlugin:
    """Expose sandbox operations as MCP tools for Python code execution."""

    def __init__(self, base_image: str = DEFAULT_DOCKER_IMAGE):
        self.sandbox_env = SandboxEnvironment(base_image=base_image)
        self.mcp = FastMCP("Python Sandbox Executor")
        self._register_tools()

    def _resolve_sandbox(
        self,
        ctx: Context,
        sandbox_id: Optional[str],
        resume_token: Optional[str],
    ) -> Dict[str, Any]:
        """Return a dict with `sandbox_id` (+ `resume_token`/`download_token`
        on first creation), or {"error": True, "message": ...}.
        """
        session_id = ctx.session_id or "anonymous"
        if sandbox_id:
            result = self.sandbox_env.bind_session_to_sandbox(
                session_id, sandbox_id, resume_token or ""
            )
            return result
        return self.sandbox_env.get_or_create_session_sandbox(session_id)

    def _run(self, ctx, sandbox_id, resume_token, body):
        resolved = self._resolve_sandbox(ctx, sandbox_id, resume_token)
        if resolved.get("error"):
            return resolved
        sid = resolved["sandbox_id"]
        with self.sandbox_env.sandbox_lock(sid):
            result = body(sid)
        # Surface the sandbox_id in every response.
        result["sandbox_id"] = sid
        # Only include tokens when a new sandbox was just created.
        for key in ("resume_token", "download_token"):
            if key in resolved:
                result[key] = resolved[key]
        result["resume_hint"] = RESUME_HINT
        return result

    def _register_tools(self):
        @self.mcp.tool(
            name="list_sandboxes",
            description=(
                "Lists all existing Python sandboxes and their installed packages. "
                + RESUME_HINT
            ),
        )
        def list_sandboxes() -> list:
            return self.sandbox_env.list_user_sandboxes()

        @self.mcp.tool(
            name="execute_python_code",
            description=(
                "Executes Python code in a sandbox and returns stdout, stderr, "
                "exit_code, files, and file_links. Parameters: code (string, "
                "required); sandbox_id (string, optional); resume_token "
                "(string, optional — REQUIRED when sandbox_id is provided).\n\n"
                + ENVIRONMENT_HINT
                + "\n\n"
                + RESUME_HINT
            ),
        )
        def execute_python_code(
            code: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
            resume_token: Optional[str] = None,
        ) -> Dict[str, Any]:
            return self._run(
                ctx,
                sandbox_id,
                resume_token,
                lambda sid: self.sandbox_env.execute_python_code(sid, code),
            )

        @self.mcp.tool(
            name="execute_terminal_command",
            description=(
                "Executes a terminal command in a sandbox. Returns stdout, "
                "stderr, exit_code. Parameters: command (string, required); "
                "sandbox_id (string, optional); resume_token (string, optional — "
                "REQUIRED with sandbox_id). " + RESUME_HINT
            ),
        )
        def execute_terminal_command(
            command: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
            resume_token: Optional[str] = None,
        ) -> Dict[str, Any]:
            resolved = self._resolve_sandbox(ctx, sandbox_id, resume_token)
            if resolved.get("error"):
                return {
                    "stdout": "",
                    "stderr": resolved["message"],
                    "exit_code": -1,
                }
            sid = resolved["sandbox_id"]
            with self.sandbox_env.sandbox_lock(sid):
                result = self.sandbox_env.execute_terminal_command(sid, command)
            result["sandbox_id"] = sid
            for key in ("resume_token", "download_token"):
                if key in resolved:
                    result[key] = resolved[key]
            result["resume_hint"] = RESUME_HINT
            return result

        @self.mcp.tool(
            name="install_package_in_sandbox",
            description=(
                "Installs an additional Python package via pip/uv. Only needed "
                "for packages NOT already in the scipy-notebook stack (see "
                "execute_python_code description). Requires the deployment to "
                "expose a PyPI proxy to the sandbox network; otherwise this "
                "call will fail because sandboxes have no internet by default. "
                "Parameters: package_name (string, required); sandbox_id "
                "(string, optional); resume_token (string, optional — REQUIRED "
                "with sandbox_id). " + RESUME_HINT
            ),
        )
        def install_package_in_sandbox(
            package_name: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
            resume_token: Optional[str] = None,
        ) -> Dict[str, Any]:
            return self._run(
                ctx,
                sandbox_id,
                resume_token,
                lambda sid: self.sandbox_env.install_package(sid, package_name),
            )

        @self.mcp.tool(
            name="check_package_installation_status",
            description=(
                "Checks the installation status of a package in a sandbox. "
                "Parameters: package_name (string, required); sandbox_id "
                "(string, optional); resume_token (string, optional — REQUIRED "
                "with sandbox_id). " + RESUME_HINT
            ),
        )
        def check_package_installation_status(
            package_name: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
            resume_token: Optional[str] = None,
        ) -> Dict[str, Any]:
            return self._run(
                ctx,
                sandbox_id,
                resume_token,
                lambda sid: self.sandbox_env.check_package_status(sid, package_name),
            )

        @self.mcp.tool(
            name="upload_file_to_sandbox",
            description=(
                "Uploads a local file to a sandbox. Parameters: local_file_path "
                "(string, required); dest_path (string, optional, default "
                "/app/results); sandbox_id (string, optional); resume_token "
                "(string, optional — REQUIRED with sandbox_id). " + RESUME_HINT
            ),
        )
        def upload_file_to_sandbox(
            local_file_path: str,
            ctx: Context,
            dest_path: str = "/app/results",
            sandbox_id: Optional[str] = None,
            resume_token: Optional[str] = None,
        ) -> dict:
            return self._run(
                ctx,
                sandbox_id,
                resume_token,
                lambda sid: self.sandbox_env.upload_file_to_sandbox(
                    sid, local_file_path, dest_path
                ),
            )
