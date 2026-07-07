"""
Client Registry
Stores client metadata, metrics, and per-client task queue in memory.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
import time
import logging
from collections import deque

logger = logging.getLogger("alma-server")

# Time before a client is considered offline (seconds)
STALE_TIMEOUT = 90  # 3 missed heartbeats at 30s interval


@dataclass
class ClientInfo:
    pc_name: str
    hostname: str = ""
    version: str = ""
    listen_ip: str = ""        # Client IP as seen by server
    connected_at: float = 0.0
    last_seen: float = 0.0
    last_metrics: Optional[dict] = None
    online: bool = True
    tasks: deque = field(default_factory=deque)  # Queue of {task_id, command} dicts

    def to_dict(self) -> dict:
        return {
            "pc_name": self.pc_name,
            "hostname": self.hostname,
            "version": self.version,
            "client_ip": self.listen_ip,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "last_metrics": self.last_metrics,
            "online": self.online,
            "pending_tasks": len(self.tasks),
            "idle_seconds": time.time() - self.last_seen if self.online else 0,
        }

    def add_task(self, task_id: str, command: str):
        self.tasks.append({"task_id": task_id, "command": command})

    def pop_tasks(self) -> list[dict]:
        """Return and clear all pending tasks."""
        tasks = list(self.tasks)
        self.tasks.clear()
        return tasks


class ClientRegistry:
    def __init__(self, poll_interval: int = 30):
        self._clients: Dict[str, ClientInfo] = {}
        self.poll_interval = poll_interval

    @property
    def total_count(self) -> int:
        return len(self._clients)

    @property
    def online_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.online)

    def register(self, pc_name: str, client_ip: str = "", hostname: str = "",
                 version: str = "", initial_metrics: dict = None):
        now = time.time()
        existing = self._clients.get(pc_name)
        if existing:
            existing.hostname = hostname or existing.hostname
            existing.version = version or existing.version
            existing.listen_ip = client_ip or existing.listen_ip
            existing.connected_at = now
            existing.last_seen = now
            existing.online = True
            if initial_metrics:
                existing.last_metrics = initial_metrics
            logger.info(f"Re-registered: {pc_name} v{existing.version} ({existing.listen_ip})")
        else:
            self._clients[pc_name] = ClientInfo(
                pc_name=pc_name,
                hostname=hostname,
                version=version,
                listen_ip=client_ip,
                connected_at=now,
                last_seen=now,
                online=True,
                last_metrics=initial_metrics,
            )
            logger.info(f"Registered: {pc_name} v{version} ({client_ip})")

    def unregister(self, pc_name: str):
        if pc_name in self._clients:
            self._clients[pc_name].online = False
            logger.info(f"Client offline: {pc_name}")

    def heartbeat(self, pc_name: str, metrics: dict = None) -> list[dict]:
        """Called when a client sends a heartbeat. Returns any pending tasks."""
        client = self._clients.get(pc_name)
        if not client:
            logger.warning(f"Heartbeat from unknown client: {pc_name}")
            return []

        client.last_seen = time.time()
        client.online = True
        if metrics:
            client.last_metrics = metrics

        # Return any pending tasks
        tasks = client.pop_tasks()
        if tasks:
            logger.info(f"Delivering {len(tasks)} task(s) to {pc_name}")
        return tasks

    def update_metrics(self, pc_name: str, metrics: dict):
        if c := self._clients.get(pc_name):
            c.last_metrics = metrics
            c.last_seen = time.time()
            c.online = True

    def enqueue_task(self, pc_name: str, task_id: str, command: str) -> bool:
        """Queue a task for a client. Returns True if client is online."""
        client = self._clients.get(pc_name)
        if not client:
            return False
        client.add_task(task_id, command)
        logger.info(f"Task queued for {pc_name}: [{task_id}] {command[:80]}")
        return client.online

    def mark_stale(self, pc_name: str):
        """Called when a poll fails. Marks offline if too long unseen."""
        client = self._clients.get(pc_name)
        if client and (time.time() - client.last_seen) > STALE_TIMEOUT:
            client.online = False
            logger.info(f"Client marked offline (stale): {pc_name}")

    def check_stale_clients(self):
        """Check all clients and mark stale ones offline."""
        now = time.time()
        for c in self._clients.values():
            if c.online and (now - c.last_seen) > STALE_TIMEOUT:
                c.online = False
                logger.info(f"Client timed out: {c.pc_name}")

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
