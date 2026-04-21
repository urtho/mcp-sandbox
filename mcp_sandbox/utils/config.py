import logging
import os
import tomli
from pathlib import Path

CONFIG_FILE = Path("config.toml").resolve()

DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": 8181,
    },
    "sandbox": {
        "global_sandbox_limit": 50,
        "per_session_sandbox_limit": 3,
        "sandbox_network": "none",
        "execution_timeout_seconds": 60,
        "install_timeout_seconds": 180,
        "tmp_dir_size": "256m",
        "results_dir_size": "1g",
        "pids_limit": 256,
        "nofile_soft_limit": 1024,
        "nofile_hard_limit": 2048,
        "sandbox_uid": 1000,
        "sandbox_gid": 100,
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
    "mirror": {
        "pypi_index_url": "",
    },
}

try:
    with open(CONFIG_FILE, "rb") as f:
        config = tomli.load(f)
    logging.info(f"Loaded configuration from {CONFIG_FILE}")
except (FileNotFoundError, tomli.TOMLDecodeError) as e:
    logging.warning(
        f"Could not load configuration file: {e}. Using default configuration."
    )
    config = DEFAULT_CONFIG


def _sandbox(key, default):
    return config.get("sandbox", {}).get(key, default)


HOST = os.environ.get("APP_HOST", config["server"]["host"])
PORT = int(os.environ.get("APP_PORT", config["server"]["port"]))
DEFAULT_DOCKER_IMAGE = config["docker"]["default_image"]
SANDBOX_IDLE_TIMEOUT_SECONDS = int(
    config.get("docker", {}).get("sandbox_idle_timeout_seconds", 1800)
)

GLOBAL_SANDBOX_LIMIT = int(_sandbox("global_sandbox_limit", 50))
PER_SESSION_SANDBOX_LIMIT = int(_sandbox("per_session_sandbox_limit", 3))
SANDBOX_NETWORK = os.environ.get(
    "MCP_SANDBOX_NETWORK", _sandbox("sandbox_network", "none")
)
EXECUTION_TIMEOUT_SECONDS = int(_sandbox("execution_timeout_seconds", 60))
INSTALL_TIMEOUT_SECONDS = int(_sandbox("install_timeout_seconds", 180))
TMP_DIR_SIZE = str(_sandbox("tmp_dir_size", "256m"))
RESULTS_DIR_SIZE = str(_sandbox("results_dir_size", "1g"))
PIDS_LIMIT = int(_sandbox("pids_limit", 256))
NOFILE_SOFT = int(_sandbox("nofile_soft_limit", 1024))
NOFILE_HARD = int(_sandbox("nofile_hard_limit", 2048))
SANDBOX_UID = int(_sandbox("sandbox_uid", 1000))
SANDBOX_GID = int(_sandbox("sandbox_gid", 100))

PYPI_INDEX_URL = os.environ.get(
    "MCP_SANDBOX_PIP_INDEX_URL", config.get("mirror", {}).get("pypi_index_url", "")
)

logger = logging.getLogger("MCP_SANDBOX")
logger.setLevel(getattr(logging, config["logging"]["level"]))
logger.propagate = False
formatter = logging.Formatter(config["logging"]["format"])


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


console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter(config["logging"]["format"]))
file_handler = logging.FileHandler(config["logging"]["log_file"])
file_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.addHandler(file_handler)
