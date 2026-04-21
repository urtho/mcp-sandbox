import logging
import os
import tomli
from pathlib import Path

# Load configuration from TOML file
CONFIG_FILE = Path("config.toml").resolve()

# Default configuration if file doesn't exist
DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": 8181,
    },
    "auth": {
        "require_auth": False,
        "default_user_id": "root",
        "user_sandbox_limit": 3,
    },
    "docker": {
        "default_image": "python-sandbox:latest",
        "dockerfile_path": "sandbox_images/Dockerfile",
        "check_dockerfile_changes": True,
        "build_info_file": ".docker_build_info",
        "sandbox_idle_timeout_seconds": 1800,
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "log_file": "mcp_sandbox.log",
    },
}

# Load configuration
try:
    with open(CONFIG_FILE, "rb") as f:
        config = tomli.load(f)
    logging.info(f"Loaded configuration from {CONFIG_FILE}")
except (FileNotFoundError, tomli.TOMLDecodeError) as e:
    logging.warning(
        f"Could not load configuration file: {e}. Using default configuration."
    )
    config = DEFAULT_CONFIG

# Extract configuration values
HOST = os.environ.get("APP_HOST", config["server"]["host"])
PORT = int(os.environ.get("APP_PORT", config["server"]["port"]))
DEFAULT_DOCKER_IMAGE = config["docker"]["default_image"]
SANDBOX_IDLE_TIMEOUT_SECONDS = int(
    config.get("docker", {}).get("sandbox_idle_timeout_seconds", 1800)
)

# Auth configuration
REQUIRE_AUTH = config.get("auth", {}).get("require_auth", False)
DEFAULT_USER_ID = config.get("auth", {}).get("default_user_id", "root")
USER_SANDBOX_LIMIT = config.get("auth", {}).get("user_sandbox_limit", 3)

PYPI_INDEX_URL = config["mirror"]["pypi_index_url"]

# Base URL for file access
BASE_URL = f"http://{HOST}:{PORT}/static/"

# Configure logging for MCP_SANDBOX
logger = logging.getLogger("MCP_SANDBOX")
logger.setLevel(getattr(logging, config["logging"]["level"]))
logger.propagate = False
formatter = logging.Formatter(config["logging"]["format"])


# Color formatter for console logs
class ColorFormatter(logging.Formatter):
    COLOR_MAP = {
        logging.DEBUG: "\033[37m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[41m",
    }
    RESET_SEQ = "\033[0m"

    def format(self, record):
        msg = super().format(record)
        color = self.COLOR_MAP.get(record.levelno, self.RESET_SEQ)
        return f"{color}{msg}{self.RESET_SEQ}"


# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter(config["logging"]["format"]))
# File handler
file_handler = logging.FileHandler(config["logging"]["log_file"])
file_handler.setFormatter(formatter)
# Attach handlers
logger.addHandler(console_handler)
logger.addHandler(file_handler)
