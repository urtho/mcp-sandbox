from typing import Dict, Any
import time
import uuid
from mcp_sandbox.utils.config import EXECUTION_TIMEOUT_SECONDS


def _timeout_cmd(seconds: int, cmd: list) -> list:
    """Prepend `timeout --signal=KILL` to a command list."""
    return ["timeout", "--signal=KILL", str(seconds), *cmd]


def _annotate_timeout(exit_code: int, stderr: str) -> str:
    if exit_code == 124:
        return (stderr + "\n" if stderr else "") + (
            f"[timeout: killed after {EXECUTION_TIMEOUT_SECONDS}s]"
        )
    if exit_code == 137:
        return (stderr + "\n" if stderr else "") + "[killed by runtime limit]"
    return stderr


class SandboxExecutionMixin:
    def execute_python_code(self, sandbox_id: str, code: str) -> Dict[str, Any]:
        error = self.verify_sandbox_exists(sandbox_id)
        if error:
            return error
        start_ts = int(time.time())
        logger = self._get_logger()
        logger.info(f"Running code in sandbox {sandbox_id} (len={len(code)})")
        try:
            with self._get_running_sandbox(sandbox_id) as sandbox:
                # Unique per-call path avoids clobbering if two callers end up
                # on the same sandbox despite the sandbox_lock.
                temp_code_file = f"/tmp/code_{uuid.uuid4().hex}.py"
                write_code_cmd = f"cat > {temp_code_file} << 'EOL'\n{code}\nEOL"
                write_result = sandbox.exec_run(
                    cmd=["sh", "-c", write_code_cmd],
                    workdir="/app/results",
                    privileged=False,
                )
                if write_result.exit_code != 0:
                    logger.error(
                        f"Failed to write code to sandbox: {write_result.output.decode('utf-8')}"
                    )
                    return {
                        "error": "Failed to prepare code execution",
                        "stdout": "",
                        "stderr": write_result.output.decode("utf-8"),
                        "exit_code": write_result.exit_code,
                        "files": [],
                        "file_links": [],
                    }
                exec_result = sandbox.exec_run(
                    cmd=_timeout_cmd(
                        EXECUTION_TIMEOUT_SECONDS, ["python", temp_code_file]
                    ),
                    workdir="/app/results",
                    stdout=True,
                    stderr=True,
                    demux=True,
                    privileged=False,
                )
                exit_code = exec_result.exit_code
                stdout_bytes, stderr_bytes = exec_result.output
                stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
                stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
                stderr = _annotate_timeout(exit_code, stderr)
                sandbox.exec_run(cmd=["rm", "-f", temp_code_file], privileged=False)
                all_files = self.list_files_in_sandbox(sandbox_id, with_stat=True)
                new_files = [f for f, ctime in all_files if ctime >= start_ts]
                file_links = [self.get_file_link(sandbox_id, f) for f in new_files]
                logger.info("Execution results:")
                logger.info(f"Exit code: {exit_code}")
                if stdout:
                    logger.info("Stdout:")
                    logger.info(stdout)
                if stderr:
                    logger.warning("Stderr:")
                    logger.warning(stderr)
                return {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "files": new_files,
                    "file_links": file_links,
                }
        except ValueError as e:
            return {
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "files": [],
                "file_links": [],
            }
        except Exception as e:
            logger.error(
                f"Failed to run code in sandbox {sandbox_id}: {e}", exc_info=True
            )
            error_message = str(e)
            if hasattr(e, "stderr") and e.stderr:
                stderr = (
                    e.stderr.decode("utf-8")
                    if isinstance(e.stderr, bytes)
                    else str(e.stderr)
                )
                error_message = f"{error_message}\nDetails: {stderr}"
            return {
                "error": error_message,
                "stdout": "",
                "stderr": error_message,
                "exit_code": 1,
                "files": [],
                "file_links": [],
            }

    def execute_terminal_command(self, sandbox_id: str, command: str) -> Dict[str, Any]:
        """Execute a terminal command in a specified sandbox

        Args:
            sandbox_id: The sandbox ID
            command: The command to execute

        Returns:
            Dictionary containing stdout, stderr and exit_code
        """
        logger = self._get_logger()

        # Verify if sandbox exists
        error = self.verify_sandbox_exists(sandbox_id)
        if error:
            return {
                "stdout": "",
                "stderr": error.get("message", "Sandbox not found"),
                "exit_code": -1,
            }

        try:
            with self._get_running_sandbox(sandbox_id) as container:
                logger.info(f"Executing command in sandbox {sandbox_id}: {command}")
                exec_result = container.exec_run(
                    _timeout_cmd(
                        EXECUTION_TIMEOUT_SECONDS, ["sh", "-c", command]
                    ),
                    stdout=True,
                    stderr=True,
                    stdin=False,
                    tty=False,
                    demux=True,
                )
                exit_code = exec_result.exit_code
                stdout_bytes, stderr_bytes = exec_result.output

                stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
                stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
                stderr = _annotate_timeout(exit_code, stderr)

                return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        except Exception as e:
            logger.error(
                f"Error executing command in sandbox {sandbox_id}: {e}", exc_info=True
            )
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    def _get_logger(self):
        from mcp_sandbox.utils.config import logger

        return logger
