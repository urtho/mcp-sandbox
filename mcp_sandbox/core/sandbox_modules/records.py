from typing import List, Dict, Any
from mcp_sandbox.utils.config import logger


class SandboxRecordsMixin:
    def list_sandboxes(self) -> list:
        """List all sandbox containers known to Docker"""
        sandboxes = []
        for sandbox in self.sandbox_client.containers.list(
            all=True, filters={"label": "python-sandbox"}
        ):
            sandboxes.append(
                {
                    "sandbox_id": sandbox.id,
                    "name": sandbox.name,
                    "status": sandbox.status,
                    "image": sandbox.image.tags[0]
                    if sandbox.image.tags
                    else sandbox.image.short_id,
                    "created": sandbox.attrs.get("Created"),
                    "last_used": self.sandbox_last_used.get(sandbox.id),
                }
            )
        return sandboxes

    def list_user_sandboxes(self) -> List[Dict[str, Any]]:
        """List every sandbox container with its installed-package snapshot"""
        out: List[Dict[str, Any]] = []
        try:
            containers = self.sandbox_client.containers.list(
                all=True, filters={"label": "python-sandbox"}
            )
        except Exception as e:
            logger.error(f"list_user_sandboxes: Docker error: {e}")
            return out

        for container in containers:
            entry: Dict[str, Any] = {
                "sandbox_id": container.id,
                "name": container.name,
                "status": container.status,
                "installed_packages": [],
            }
            try:
                packages = self.list_installed_packages(container.id)
                if packages:
                    entry["installed_packages"] = packages
            except Exception as e:
                logger.error(
                    f"Error listing packages for sandbox {container.id}: {e}"
                )
            out.append(entry)
        return out
