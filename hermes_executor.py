"""
Hermes Executor — isolated Hermes sessions per client.

When the user wants Hermes to perform work on a specific client,
the server spawns a dedicated Hermes CLI process with custom tools
that route commands ONLY to that client.

Key guarantees:
  - One Hermes session = one client PC (no cross-contamination)
  - Custom tool "alma_exec" enqueues commands, waits for results
  - Session times out if idle for too long
  - Results delivered back to the dashboard

Architecture:
  Dashboard → POST /api/clients/{name}/hermes → spawns Hermes
  Hermes tool call → enqueue task for client → client heartbeat picks it up
  Client executes → POST /api/task-result → Hermes tool receives result
  Hermes finishes → final response sent to dashboard
"""
import asyncio
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger("alma-server")


class HermesSession:
    """An isolated Hermes session tied to a single client."""

    def __init__(self, session_id: str, pc_name: str, registry):
        self.session_id = session_id
        self.pc_name = pc_name
        self.registry = registry
        self.created_at = time.time()
        self.last_activity = time.time()
        self.status = "idle"  # idle, running, completed, error
        self.final_response = ""
        self._pending_tasks: dict[str, asyncio.Future] = {}  # task_id → Future

    def resolve_task(self, task_id: str, result: dict):
        """Called when a task result comes back from the client."""
        if task_id in self._pending_tasks:
            future = self._pending_tasks.pop(task_id)
            if not future.done():
                future.set_result(result)
            self.last_activity = time.time()

    async def execute_command(self, command: str, timeout: int = 300) -> dict:
        """Enqueue a command for the client and wait for the result."""
        task_id = str(uuid.uuid4())[:8]

        # Enqueue for the client
        online = self.registry.enqueue_task(self.pc_name, task_id, command)
        if not online:
            return {"exit_code": -1, "stdout": "", "stderr": "", "error": f"Client '{self.pc_name}' offline"}

        # Create a future and wait for the result
        future = asyncio.get_event_loop().create_future()
        self._pending_tasks[task_id] = future
        self.status = "running"
        self.last_activity = time.time()

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_tasks.pop(task_id, None)
            return {"exit_code": -1, "stdout": "", "stderr": "", "error": f"Task timed out ({timeout}s)"}
        finally:
            if not self._pending_tasks:
                self.status = "idle"


class HermesExecutor:
    """Manages Hermes sessions and tool routing."""

    def __init__(self, registry):
        self.registry = registry
        self._sessions: dict[str, HermesSession] = {}  # session_id → session
        self._pending_sync_tasks: dict[str, asyncio.Future] = {}  # task_id → Future

    def create_session(self, pc_name: str) -> HermesSession:
        """Create a new isolated session for a client."""
        session_id = str(uuid.uuid4())[:8]
        session = HermesSession(session_id, pc_name, self.registry)
        self._sessions[session_id] = session
        logger.info(f"Hermes session {session_id} created for {pc_name}")
        return session

    def get_session(self, session_id: str) -> Optional[HermesSession]:
        return self._sessions.get(session_id)

    def resolve_task_result(self, pc_name: str, task_id: str, result: dict):
        """Route a task result to the correct session or sync task."""
        # Check sync tasks first (for alma_exec tool)
        if task_id in self._pending_sync_tasks:
            future = self._pending_sync_tasks.pop(task_id)
            if not future.done():
                future.set_result(result)
            # Turn off fast poll
            self.registry.set_fast_poll(pc_name, False)
            return

        # Route to Hermes session
        for session in self._sessions.values():
            if session.pc_name == pc_name:
                session.resolve_task(task_id, result)

    def cleanup_stale_sessions(self, max_idle: int = 600):
        """Remove sessions idle for too long."""
        now = time.time()
        stale = [
            sid for sid, s in self._sessions.items()
            if now - s.last_activity > max_idle
        ]
        for sid in stale:
            logger.info(f"Cleaning up stale session {sid}")
            del self._sessions[sid]


# Singleton
hermes_executor = HermesExecutor(registry=None)  # initialized in main.py
