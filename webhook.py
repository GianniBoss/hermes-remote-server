"""
Webhook Dispatcher
Periodically POSTs client data JSON to an external URL.
"""
from dataclasses import dataclass
from typing import Optional
import asyncio
import httpx
import time
import logging

logger = logging.getLogger("hermes-server")


@dataclass
class WebhookConfig:
    url: str = ""
    interval_seconds: int = 30
    enabled: bool = False


class WebhookManager:
    def __init__(self):
        self.config = WebhookConfig()
        self._task: Optional[asyncio.Task] = None
        self.last_sent_at: float = 0
        self.last_status_code: int = 0
        self.last_error: str = ""

    def get_config(self) -> dict:
        return {
            "url": self.config.url,
            "interval_seconds": self.config.interval_seconds,
            "enabled": self.config.enabled,
            "last_sent_at": self.last_sent_at,
            "last_status_code": self.last_status_code,
            "last_error": self.last_error,
        }

    async def set_config(self, url: str, interval_seconds: int, enabled: bool):
        self.config.url = url
        self.config.interval_seconds = max(5, interval_seconds)  # minimum 5s
        self.config.enabled = enabled
        self._restart_loop()

    def _restart_loop(self):
        if self._task and not self._task.done():
            self._task.cancel()
        if self.config.enabled and self.config.url:
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        while self.config.enabled and self.config.url:
            await asyncio.sleep(self.config.interval_seconds)
            await self.send_now()

    async def send_now(self) -> dict:
        """Build payload and POST to webhook URL. Returns result dict."""
        from client_registry import registry

        clients_data = []
        for c in registry.get_all():
            clients_data.append({
                "pc_name": c.pc_name,
                "hostname": c.hostname,
                "version": c.version,
                "client_ip": c.client_ip,
                "online": c.online,
                "connected_at": c.connected_at,
                "last_seen": c.last_seen,
                "metrics": c.last_metrics,
            })

        payload = {
            "server_ts": time.time(),
            "clients": clients_data,
            "total_clients": registry.total_count,
            "online_clients": registry.online_count,
        }

        if not self.config.url:
            return {"status": "skipped", "reason": "no webhook URL configured"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.config.url,
                    json=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "HermesRemoteServer/1.0"},
                )
                self.last_sent_at = time.time()
                self.last_status_code = resp.status_code
                self.last_error = ""
                logger.info(f"Webhook sent → {self.config.url} | {resp.status_code}")
                return {"status": "sent", "http_code": resp.status_code, "clients_count": len(clients_data)}
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Webhook failed → {self.config.url}: {e}")
            return {"status": "error", "error": str(e)}


# Singleton
webhook_manager = WebhookManager()
