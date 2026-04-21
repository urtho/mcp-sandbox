from typing import Dict, Any, Optional
from fastmcp import FastMCP, Context
from mcp_sandbox.core.sandbox_modules.manager import SandboxManager
from mcp_sandbox.core.sandbox_modules.file_ops import SandboxFileOpsMixin
from mcp_sandbox.core.sandbox_modules.package import SandboxPackageMixin
from mcp_sandbox.core.sandbox_modules.records import SandboxRecordsMixin
from mcp_sandbox.core.sandbox_modules.execution import SandboxExecutionMixin
from mcp_sandbox.utils.config import DEFAULT_DOCKER_IMAGE


RESUME_HINT = (
    "The returned `sandbox_id` is a UUID that persists across MCP reconnects. "
    "Save it; pass it as `sandbox_id` to any tool later to resume the same "
    "Python sandbox. Omitting `sandbox_id` auto-creates or reuses a sandbox "
    "bound to the current MCP session."
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

    def _resolve_sandbox_id(
        self, ctx: Context, sandbox_id: Optional[str]
    ) -> Dict[str, Any]:
        """Return {"sandbox_id": ...} or {"error": True, "message": ...}.

        If `sandbox_id` is supplied it is validated and the current session is
        (re)bound to it. Otherwise the session-bound sandbox is returned,
        creating one on first use.
        """
        session_id = ctx.session_id or "anonymous"
        if sandbox_id:
            if not self.sandbox_env.bind_session_to_sandbox(session_id, sandbox_id):
                return {
                    "error": True,
                    "message": f"Sandbox not found: {sandbox_id}",
                }
            return {"sandbox_id": sandbox_id, "resumed": True}
        created = self.sandbox_env.get_or_create_session_sandbox(session_id)
        return created

    def _register_tools(self):
        """Register all MCP tools"""

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
                "exit_code, files, and file_links. Parameters: code (string, required); "
                "sandbox_id (string, optional). " + RESUME_HINT
            ),
        )
        def execute_python_code(
            code: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            resolved = self._resolve_sandbox_id(ctx, sandbox_id)
            if resolved.get("error"):
                return resolved
            sid = resolved["sandbox_id"]
            result = self.sandbox_env.execute_python_code(sid, code)
            result["sandbox_id"] = sid
            result["resume_hint"] = RESUME_HINT
            return result

        @self.mcp.tool(
            name="execute_terminal_command",
            description=(
                "Executes a terminal command in a sandbox. Returns stdout, stderr, "
                "exit_code. Parameters: command (string, required); sandbox_id "
                "(string, optional). " + RESUME_HINT
            ),
        )
        def execute_terminal_command(
            command: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            resolved = self._resolve_sandbox_id(ctx, sandbox_id)
            if resolved.get("error"):
                return {
                    "stdout": "",
                    "stderr": resolved["message"],
                    "exit_code": -1,
                }
            sid = resolved["sandbox_id"]
            result = self.sandbox_env.execute_terminal_command(sid, command)
            result["sandbox_id"] = sid
            result["resume_hint"] = RESUME_HINT
            return result

        @self.mcp.tool(
            name="install_package_in_sandbox",
            description=(
                "Installs a Python package in a sandbox via pip. Parameters: "
                "package_name (string, required); sandbox_id (string, optional). "
                + RESUME_HINT
            ),
        )
        def install_package_in_sandbox(
            package_name: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            resolved = self._resolve_sandbox_id(ctx, sandbox_id)
            if resolved.get("error"):
                return resolved
            sid = resolved["sandbox_id"]
            result = self.sandbox_env.install_package(sid, package_name)
            result["sandbox_id"] = sid
            return result

        @self.mcp.tool(
            name="check_package_installation_status",
            description=(
                "Checks the installation status of a package in a sandbox. "
                "Parameters: package_name (string, required); sandbox_id (string, "
                "optional). " + RESUME_HINT
            ),
        )
        def check_package_installation_status(
            package_name: str,
            ctx: Context,
            sandbox_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            resolved = self._resolve_sandbox_id(ctx, sandbox_id)
            if resolved.get("error"):
                return resolved
            sid = resolved["sandbox_id"]
            result = self.sandbox_env.check_package_status(sid, package_name)
            result["sandbox_id"] = sid
            return result

        @self.mcp.tool(
            name="upload_file_to_sandbox",
            description=(
                "Uploads a local file to a sandbox. Parameters: local_file_path "
                "(string, required); dest_path (string, optional, default "
                "/app/results); sandbox_id (string, optional). " + RESUME_HINT
            ),
        )
        def upload_file_to_sandbox(
            local_file_path: str,
            ctx: Context,
            dest_path: str = "/app/results",
            sandbox_id: Optional[str] = None,
        ) -> dict:
            resolved = self._resolve_sandbox_id(ctx, sandbox_id)
            if resolved.get("error"):
                return resolved
            sid = resolved["sandbox_id"]
            result = self.sandbox_env.upload_file_to_sandbox(
                sid, local_file_path, dest_path
            )
            result["sandbox_id"] = sid
            return result
