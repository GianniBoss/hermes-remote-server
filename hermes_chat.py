"""
Hermes Session Manager — persistent, multi-turn conversations per client.

Spawns a hermes chat process (PTY) and communicates via stdin/stdout.
Each session is tied to one client. Hermes can:
  - Talk to the user (respond directly)
  - Use alma_exec tool to run commands on the client
  - Maintain context across multiple messages
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Optional

logger = logging.getLogger("alma-server")


class HermesChatSession:
    """A persistent Hermes chat session for one client."""

    def __init__(self, session_id: str, pc_name: str):
        self.session_id = session_id
        self.pc_name = pc_name
        self.created_at = time.time()
        self.last_activity = time.time()
        self._proc = None
        self._ready = False

    async def start(self):
        """Spawn the hermes process."""
        env = os.environ.copy()
        env["ALMA_SERVER_URL"] = "http://localhost:8765"
        env["ALMA_CLIENT_NAME"] = self.pc_name

        system_prompt = (
            f"You are an AI assistant managing the PC '{self.pc_name}' via ALMA. "
            f"You can execute powershell commands on {self.pc_name} using:\n"
            f"  terminal(command='curl -s -X POST http://localhost:8765/api/clients/{self.pc_name}/exec-sync "
            f"-H \"Content-Type: application/json\" "
            f"-d '{{\"command\": \"YOUR_COMMAND\", \"timeout\": 60}}'')\n"
            f"The response JSON contains 'stdout', 'stderr', and 'exit_code'. "
            f"Always use this to run commands on the remote PC. "
            f"Respond in Spanish. Be helpful and concise."
        )

        self._proc = await asyncio.create_subprocess_exec(
            "hermes", "chat",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Send system prompt as first message
        self._proc.stdin.write((system_prompt + "\n").encode())
        await self._proc.stdin.drain()

        # Read until we see the initial prompt/banner and first response
        # Hermes outputs its banner first, then processes the system prompt
        await self._read_until_ready()
        self._ready = True
        logger.info(f"Hermes session {self.session_id} started for {self.pc_name}")

    async def send(self, message: str) -> str:
        """Send a message and get Hermes's response."""
        if not self._proc or self._proc.returncode is not None:
            raise RuntimeError("Hermes process not running")

        self.last_activity = time.time()

        # Send user message
        self._proc.stdin.write((message + "\n").encode())
        await self._proc.stdin.drain()

        # Read response — collect all output until we see the next prompt
        return await self._read_response()

    async def close(self):
        """Gracefully close the session."""
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.write(b"/exit\n")
                await self._proc.stdin.drain()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                self._proc.kill()
        logger.info(f"Hermes session {self.session_id} closed")

    async def _read_until_ready(self):
        """Read initial output until Hermes is ready for input."""
        buffer = ""
        timeout = 30
        start = time.time()
        while time.time() - start < timeout:
            try:
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=2
                )
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                buffer += decoded
                # Hermes is ready when we see the initial prompt or a response
                if "Initializing agent" in buffer or "╭─" in buffer or "╰─" in buffer:
                    # Read a bit more to get past the initial processing
                    await asyncio.sleep(0.5)
                    # Drain remaining initial output
                    while True:
                        try:
                            extra = await asyncio.wait_for(
                                self._proc.stdout.readline(), timeout=1
                            )
                            if extra:
                                buffer += extra.decode("utf-8", errors="replace")
                            else:
                                break
                        except asyncio.TimeoutError:
                            break
                    return
            except asyncio.TimeoutError:
                continue
        logger.warning(f"Hermes session {self.session_id} startup timeout")

    async def _read_response(self) -> str:
        """Read Hermes's response until it's done (next prompt or idle)."""
        buffer = ""
        timeout = 120
        idle_timeout = 5  # seconds of no output = done
        start = time.time()
        last_output = start

        while time.time() - start < timeout:
            try:
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=1
                )
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                buffer += decoded
                last_output = time.time()
            except asyncio.TimeoutError:
                # No output for a while — Hermes is probably done
                if buffer and time.time() - last_output > idle_timeout:
                    break

        # Clean up: remove ANSI codes, tool call lines, session info
        cleaned = self._clean_response(buffer)
        return cleaned.strip() or "(sin respuesta)"

    def _clean_response(self, text: str) -> str:
        """Extract just the assistant's response from Hermes output."""
        # Remove ANSI escape codes
        text = re.sub(r'\x1b\[[0-9;]*m', '', text)
        text = re.sub(r'\x1b\[\?[0-9;]*[hl]', '', text)

        lines = text.split("\n")
        cleaned = []
        in_response = False

        for line in lines:
            stripped = line.strip()
            # Skip tool call lines
            if stripped.startswith("┊") or "preparing" in stripped:
                continue
            # Skip session info
            if "session_id:" in stripped or "Resume this session" in stripped:
                continue
            # Skip spinner/progress
            if stripped.startswith("Session:") or stripped.startswith("Duration:") or stripped.startswith("Messages:"):
                continue
            if stripped.startswith("Query:") or stripped.startswith("Initializing"):
                continue

            # Hermes response is between ╭ and ╰ markers
            if "╭─" in stripped:
                in_response = True
                continue
            if "╰─" in stripped:
                in_response = False
                continue

            if in_response and stripped:
                cleaned.append(stripped)
            elif stripped and not in_response and not cleaned:
                # Maybe there's no marker — take everything that looks like content
                if len(stripped) > 3 and not stripped.startswith("──"):
                    cleaned.append(stripped)

        return "\n".join(cleaned)


class HermesSessionManager:
    """Manages multiple Hermes chat sessions."""

    def __init__(self):
        self._sessions: dict[str, HermesChatSession] = {}

    async def get_or_create(self, pc_name: str) -> HermesChatSession:
        """Get existing session or create a new one."""
        # Reuse session for same client
        for sid, session in self._sessions.items():
            if session.pc_name == pc_name and session._ready:
                return session

        # Create new session
        session_id = str(uuid.uuid4())[:8]
        session = HermesChatSession(session_id, pc_name)
        await session.start()
        self._sessions[session_id] = session
        return session

    async def cleanup_stale(self, max_idle: int = 600):
        """Close sessions idle for too long."""
        now = time.time()
        stale = []
        for sid, s in self._sessions.items():
            if now - s.last_activity > max_idle:
                stale.append(sid)
        for sid in stale:
            await self._sessions[sid].close()
            del self._sessions[sid]
            logger.info(f"Cleaned up stale Hermes session {sid}")


# Singleton
session_manager = HermesSessionManager()
