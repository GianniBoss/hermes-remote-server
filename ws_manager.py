"""
WebSocket Connection Manager
Handles all active client connections, send/receive, auto-cleanup.
"""
from fastapi import WebSocket
from typing import Dict, Optional
import asyncio
import json
import logging

logger = logging.getLogger("alma-server")


class ConnectionManager:
    def __init__(self):
        self._clients: Dict[str, WebSocket] = {}  # pc_name → websocket
        self._tasks: Dict[str, asyncio.Task] = {}  # pc_name → read_loop task

    @property
    def online_count(self) -> int:
        return len(self._clients)

    @property
    def client_names(self) -> list:
        return list(self._clients.keys())

    async def connect(self, pc_name: str, ws: WebSocket):
        await ws.accept()
        # Close old connection if same name reconnects
        if pc_name in self._clients:
            await self._close_connection(pc_name)
        self._clients[pc_name] = ws
        logger.info(f"[+] Client connected: {pc_name} (total: {len(self._clients)})")

    def disconnect(self, pc_name: str):
        if pc_name in self._clients:
            del self._clients[pc_name]
        if pc_name in self._tasks:
            self._tasks[pc_name].cancel()
            del self._tasks[pc_name]
        logger.info(f"[-] Client disconnected: {pc_name} (total: {len(self._clients)})")

    def is_online(self, pc_name: str) -> bool:
        return pc_name in self._clients

    async def send(self, pc_name: str, data: dict) -> bool:
        """Send JSON to a specific client. Returns False if client not connected."""
        ws = self._clients.get(pc_name)
        if ws is None:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            self.disconnect(pc_name)
            return False

    async def broadcast(self, data: dict):
        """Send JSON to all connected clients."""
        disconnected = []
        for name, ws in self._clients.items():
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(name)
        for name in disconnected:
            self.disconnect(name)

    async def _close_connection(self, pc_name: str):
        ws = self._clients.get(pc_name)
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        self.disconnect(pc_name)


# Singleton
manager = ConnectionManager()
