from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from mcp_sandbox.utils.config import logger
import io
import os
import tarfile
import mimetypes


def build_sandbox_file_router(sandbox_manager) -> APIRouter:
    """Build the read-only sandbox file router bound to the given manager.

    The manager is shared with the MCP plugin so idle tracking and the
    session->sandbox map stay consistent across HTTP and SSE traffic.
    """
    router = APIRouter()

    @router.get("/sandbox/file")
    def get_sandbox_file(
        sandbox_id: str = Query(..., description="Sandbox ID"),
        file_path: str = Query(
            ...,
            description="Absolute path to the file inside the sandbox, e.g. /app/results/foo.txt",
        ),
    ):
        try:
            container, error = sandbox_manager.get_container_by_sandbox_id(sandbox_id)
            if error:
                logger.error(
                    f"Failed to get container for sandbox {sandbox_id}: {error['message']}"
                )
                raise HTTPException(
                    status_code=404, detail=f"Sandbox not found: {sandbox_id}"
                )
            if not container:
                raise HTTPException(
                    status_code=404,
                    detail=f"Container not found for sandbox: {sandbox_id}",
                )

            stream, _ = container.get_archive(file_path)
            tar_bytes = io.BytesIO(b"".join(stream))
            with tarfile.open(fileobj=tar_bytes) as tar:
                members = tar.getmembers()
                if not members:
                    raise HTTPException(
                        status_code=404, detail="File not found in sandbox"
                    )
                rel_path = file_path.lstrip("/")
                member = next((m for m in members if m.name == rel_path), None)
                if member is None:
                    basename = os.path.basename(file_path)
                    member = next(
                        (m for m in members if m.name.endswith(basename)), members[0]
                    )
                fileobj = tar.extractfile(member)
                if not fileobj:
                    raise HTTPException(
                        status_code=404, detail="File not found in sandbox"
                    )
                mime_type, _ = mimetypes.guess_type(member.name)
                mime_type = mime_type or "application/octet-stream"
                headers = {"Content-Disposition": f"inline; filename={member.name}"}
                return StreamingResponse(fileobj, media_type=mime_type, headers=headers)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch file from sandbox {sandbox_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error fetching file from sandbox: {e}"
            )

    return router
