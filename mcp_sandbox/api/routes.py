from fastapi import FastAPI, Request, Response
from mcp.server.sse import SseServerTransport

from mcp_sandbox.api.sandbox_file import build_sandbox_file_router


def configure_app(app: FastAPI, sandbox_plugin):
    """Configure FastAPI app with routes and middleware"""

    # Share the MCP plugin's SandboxManager with the file-access API so that
    # idle tracking and the session->sandbox map stay consistent.
    app.include_router(build_sandbox_file_router(sandbox_plugin.sandbox_env))

    mcp_server = sandbox_plugin.mcp._mcp_server
    event_stream = SseServerTransport("/messages/")

    async def handle_event_stream(request: Request) -> Response:
        """Handle Server-Sent Events (SSE) connections (no auth)"""
        initialization_options = mcp_server.create_initialization_options()
        async with event_stream.connect_sse(
            request.scope,
            request.receive,
            request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                initialization_options,
            )
        return Response()

    app.add_route("/sse", handle_event_stream)
    app.mount("/messages/", app=event_stream.handle_post_message)

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    return event_stream
