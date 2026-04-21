import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_sandbox.core.mcp_tools import SandboxToolsPlugin
from mcp_sandbox.api.routes import configure_app
from mcp_sandbox.utils.config import logger, HOST, PORT


def main():
    """Main entry point for the application"""
    app = FastAPI(title="MCP Sandbox")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    sandbox_plugin = SandboxToolsPlugin()
    configure_app(app, sandbox_plugin)

    logger.info("Starting MCP Sandbox (auth disabled)")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
