import io
import os
import secrets
import tarfile
import mimetypes

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from mcp_sandbox.utils.config import logger


RESULTS_ROOT = "/app/results"


def build_sandbox_file_router(sandbox_manager) -> APIRouter:
    """Read-only download endpoint scoped to /app/results/ and gated by the
    per-sandbox download_token. Uses the same manager as the MCP plugin so
    idle tracking stays consistent.
    """
    router = APIRouter()

    @router.get("/sandbox/file")
    def get_sandbox_file(
        sandbox_id: str = Query(..., description="Sandbox ID"),
        file_path: str = Query(
            ...,
            description="Absolute path inside the sandbox under /app/results/",
        ),
        token: str = Query(..., description="Per-sandbox download token"),
    ):
        # Clamp to /app/results/ — reject traversal.
        normalized = os.path.normpath(file_path)
        if not normalized.startswith(RESULTS_ROOT + "/") and normalized != RESULTS_ROOT:
            raise HTTPException(
                status_code=403,
                detail=f"file_path must be under {RESULTS_ROOT}/",
            )

        container, error = sandbox_manager.get_container_by_sandbox_id(sandbox_id)
        if error or not container:
            raise HTTPException(
                status_code=404, detail=f"Sandbox not found: {sandbox_id}"
            )

        expected = sandbox_manager.get_download_token(container)
        if not expected or not token or not secrets.compare_digest(expected, token):
            logger.warning(f"/sandbox/file: bad token for {sandbox_id}")
            raise HTTPException(status_code=403, detail="Invalid download token")

        try:
            stream, _ = container.get_archive(normalized)
        except Exception as e:
            logger.error(f"get_archive failed for {sandbox_id}:{normalized}: {e}")
            raise HTTPException(status_code=404, detail="File not found in sandbox")

        tar_bytes = io.BytesIO(b"".join(stream))
        with tarfile.open(fileobj=tar_bytes) as tar:
            members = tar.getmembers()
            if not members:
                raise HTTPException(
                    status_code=404, detail="File not found in sandbox"
                )
            rel_path = normalized.lstrip("/")
            member = next((m for m in members if m.name == rel_path), None)
            if member is None:
                basename = os.path.basename(normalized)
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

    return router
