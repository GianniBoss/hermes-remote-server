"""
Client Registry
Stores client metadata and latest metrics in memory.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
import time
import logging

logger = logging.getLogger("hermes-server")


@dataclass
class ClientInfo:
    pc_name: str
    hostname: str = ""
    version: str = ""
    client_ip: str = ""
    connected_at: float = 0.0
    last_seen: float = 0.0
    last_metrics: Optional[dict] = None
    online: bool = True

    def to_dict(self) -> dict:
        return {
            "pc_name": self.pc_name,
            "hostname": self.hostname,
            "version": self.version,
            "client_ip": self.client_ip,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "last_metrics": self.last_metrics,
            "online": self.online,
            "idle_seconds": time.time() - self.last_seen if self.online else 0,
        }


class ClientRegistry:
    def __init__(self):
        self._clients: Dict[str, ClientInfo] = {}

    @property
    def total_count(self) -> int:
        return len(self._clients)

    @property
    def online_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.online)

    def register(self, pc_name: str, hostname: str = "", version: str = "", client_ip: str = ""):
        now = time.time()
        existing = self._clients.get(pc_name)
        if existing:
            # Reconnect: update fields, mark online
            existing.hostname = hostname or existing.hostname
            existing.version = version or existing.version
            existing.client_ip = client_ip or existing.client_ip
            existing.connected_at = now
            existing.last_seen = now
            existing.online = True
        else:
            self._clients[pc_name] = ClientInfo(
                pc_name=pc_name,
                hostname=hostname,
                version=version,
                client_ip=client_ip,
                connected_at=now,
                last_seen=now,
                online=True,
            )
        logger.info(f"Registered client: {pc_name} (hostname={hostname}, v{version})")

    def unregister(self, pc_name: str):
        if pc_name in self._clients:
            self._clients[pc_name].online = False
            logger.info(f"Client offline: {pc_name}")

    def update_metrics(self, pc_name: str, metrics: dict):
        if c := self._clients.get(pc_name):
            c.last_metrics = metrics
            c.last_seen = time.time()
            c.online = True

    def get(self, pc_name: str) -> Optional[ClientInfo]:
        return self._clients.get(pc_name)

    def get_all(self) -> list:
        return sorted(self._clients.values(), key=lambda c: c.pc_name)

    def get_all_online(self) -> list:
        return [c for c in self._clients.values() if c.online]

    def remove(self, pc_name: str):
        self._clients.pop(pc_name, None)


# Singleton
registry = ClientRegistry()
