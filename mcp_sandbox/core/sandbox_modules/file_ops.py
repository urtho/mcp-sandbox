from typing import List
import tarfile
import io
from pathlib import Path


class SandboxFileOpsMixin:
    def list_files_in_sandbox(
        self, sandbox_id: str, directory: str = "/app/results", with_stat: bool = False
    ) -> List:
        from mcp_sandbox.utils.config import logger

        try:
            container, error = self.get_container_by_sandbox_id(sandbox_id)
            if error:
                logger.error(
                    f"Failed to get container for sandbox {sandbox_id}: {error['message']}"
                )
                return []

            if not container:
                logger.error(f"No container found for sandbox {sandbox_id}")
                return []

            exec_result = container.exec_run(f"ls -1 {directory}")
            if exec_result.exit_code != 0:
                return []

            files = exec_result.output.decode().splitlines()
            full_paths = [f"{directory.rstrip('/')}/{f}" for f in files]

            if with_stat:
                stat_files = []
                for f in full_paths:
                    stat_result = container.exec_run(f'stat -c "%n|%Z" "{f}"')
                    if stat_result.exit_code == 0:
                        parts = stat_result.output.decode().strip().split("|", 1)
                        if len(parts) == 2:
                            stat_files.append((parts[0], int(parts[1])))
                return stat_files
            else:
                return full_paths
        except Exception as e:
            from mcp_sandbox.utils.config import logger

            logger.error(f"Failed to list files in sandbox {sandbox_id}: {e}")
            return []

    def get_file_link(self, sandbox_id: str, file_path: str) -> str:
        from mcp_sandbox.utils.config import HOST, PORT

        base_url = f"http://{HOST}:{PORT}"
        return f"{base_url}/sandbox/file?sandbox_id={sandbox_id}&file_path={file_path}"

    def upload_file_to_sandbox(
        self, sandbox_id: str, local_file_path: str, dest_path: str = "/app/results"
    ) -> dict:
        from mcp_sandbox.utils.config import logger

        error = self.verify_sandbox_exists(sandbox_id)
        if error:
            return error
        try:
            with self._get_running_sandbox(sandbox_id) as sandbox:
                local_file = Path(local_file_path)
                if not local_file.exists():
                    return {
                        "error": True,
                        "message": f"Local file not found: {local_file_path}",
                    }
                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                    tar.add(str(local_file), arcname=local_file.name)
                tar_stream.seek(0)
                sandbox.put_archive(dest_path, tar_stream.read())
                return {
                    "success": True,
                    "message": f"Uploaded {local_file.name} to {dest_path} in sandbox {sandbox_id}",
                }
        except Exception as e:
            logger.error(
                f"Failed to upload file to sandbox {sandbox_id}: {e}", exc_info=True
            )
            return {"error": True, "message": str(e)}
