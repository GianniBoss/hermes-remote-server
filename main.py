"""
ALMA Server
FastAPI backend: HTTP REST API for dashboard + client heartbeat protocol.

Protocol (HTTP, all client → server outbound):
  POST /api/register     Client startup
  POST /api/heartbeat    Periodic (metrics + task polling)
  POST /api/task-result  After executing a task
  POST /api/unregister   Client shutdown
"""
import os
import uuid
import asyncio
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from client_registry import registry
from webhook import webhook_manager
from hermes_executor import hermes_executor

# Wire up singleton
hermes_executor.registry = registry

# In-memory task result store (for dashboard polling)
_task_results: dict[str, dict] = {}

# Chat history per client (persisted to disk)
import json as _json
from pathlib import Path as _Path
_CHAT_HISTORY_DIR = _Path(os.path.dirname(__file__)) / "chat_history"
_CHAT_HISTORY_DIR.mkdir(exist_ok=True)

def _get_chat_history(pc_name: str) -> list[dict]:
    path = _CHAT_HISTORY_DIR / f"{pc_name}.json"
    if path.exists():
        return _json.loads(path.read_text())
    return []

def _save_chat_history(pc_name: str, messages: list[dict]):
    path = _CHAT_HISTORY_DIR / f"{pc_name}.json"
    # Keep last 200 messages max
    if len(messages) > 200:
        messages = messages[-200:]
    path.write_text(_json.dumps(messages))

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("alma-server")

# ── Config from env ───────────────────────────────────────────────────
CLIENT_REPO_URL = os.getenv(
    "CLIENT_REPO_URL",
    "https://github.com/GianniBoss/alma-client",
)
SERVER_VERSION = "1.1.0"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))

# ── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(title="ALMA Server", version=SERVER_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════
#  Models
# ═══════════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    pc_name: str
    hostname: str = ""
    version: str = "0.0.0"
    metrics: dict = {}

class HeartbeatRequest(BaseModel):
    pc_name: str
    metrics: dict = {}

class TaskResultRequest(BaseModel):
    pc_name: str
    task_id: str
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    error: str = ""

class UnregisterRequest(BaseModel):
    pc_name: str

class ExecRequest(BaseModel):
    command: str

class WebhookConfigModel(BaseModel):
    url: str
    interval_seconds: int = 30
    enabled: bool = True


# ═══════════════════════════════════════════════════════════════════════
#  Client Protocol Endpoints (HTTP — outbound from client)
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/register")
async def client_register(req: RegisterRequest, request: Request):
    """Client calls this on startup to announce itself."""
    client_ip = request.client.host if request.client else "unknown"
    registry.register(
        pc_name=req.pc_name,
        client_ip=client_ip,
        hostname=req.hostname,
        version=req.version,
        initial_metrics=req.metrics,
    )
    return {
        "status": "ok",
        "server_version": SERVER_VERSION,
        "poll_interval": POLL_INTERVAL,
        "repo_url": CLIENT_REPO_URL,
    }


@app.post("/api/heartbeat")
async def client_heartbeat(req: HeartbeatRequest):
    """Client calls this periodically. Server responds with any pending tasks."""
    tasks = registry.heartbeat(req.pc_name, req.metrics)
    interval = registry.get_poll_interval(req.pc_name)
    return {
        "status": "ok",
        "poll_interval": interval,
        "tasks": tasks,
    }


@app.post("/api/task-result")
async def client_task_result(req: TaskResultRequest):
    """Client calls this after executing a task."""
    logger.info(
        f"Task result from {req.pc_name} [{req.task_id}]: "
        f"exit={req.exit_code}, stdout_len={len(req.stdout)}"
    )
    # Store for dashboard polling
    _task_results[req.task_id] = {
        "exit_code": req.exit_code,
        "stdout": req.stdout,
        "stderr": req.stderr,
        "error": req.error,
        "timestamp": datetime.now().isoformat(),
    }
    # Route to Hermes session if one is waiting for this result
    hermes_executor.resolve_task_result(
        req.pc_name, req.task_id,
        {"exit_code": req.exit_code, "stdout": req.stdout, "stderr": req.stderr, "error": req.error}
    )
    return {"status": "ok"}


@app.get("/api/tasks/{task_id}")
async def get_task_result(task_id: str):
    """Dashboard polls this to get command execution results."""
    result = _task_results.get(task_id)
    if not result:
        return {"status": "pending"}
    return result


@app.post("/api/unregister")
async def client_unregister(req: UnregisterRequest):
    """Client calls this on graceful shutdown."""
    registry.unregister(req.pc_name)
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Dashboard
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/clients")
async def list_clients():
    clients = registry.get_all()
    return {
        "clients": [c.to_dict() for c in clients],
        "total": registry.total_count,
        "online": registry.online_count,
    }


@app.get("/api/clients/{pc_name}")
async def get_client(pc_name: str):
    client = registry.get(pc_name)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client.to_dict()


@app.post("/api/clients/{pc_name}/exec")
async def exec_command(pc_name: str, req: ExecRequest):
    """Queue a command for a client. Delivered on next heartbeat."""
    client = registry.get(pc_name)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.online:
        raise HTTPException(status_code=400, detail=f"Client '{pc_name}' is offline")

    task_id = str(uuid.uuid4())[:8]
    registry.enqueue_task(pc_name, task_id, req.command)
    return {
        "task_id": task_id,
        "pc_name": pc_name,
        "status": "queued",
        "message": f"Task queued for {pc_name}. Will execute on next heartbeat.",
    }


class ExecSyncRequest(BaseModel):
    command: str
    timeout: int = 300


@app.post("/api/clients/{pc_name}/exec-sync")
async def exec_command_sync(pc_name: str, req: ExecSyncRequest):
    """Execute a command on a client and WAIT for the result (blocking).

    Used by Hermes's alma_exec tool for synchronous remote execution.
    The server queues the task, waits for the client to pick it up and
    return the result, then responds.
    """
    client = registry.get(pc_name)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.online:
        raise HTTPException(status_code=400, detail=f"Client '{pc_name}' is offline")

    task_id = str(uuid.uuid4())[:8]
    registry.enqueue_task(pc_name, task_id, req.command)

    # Switch client to fast-poll mode so it picks up the task quickly
    registry.set_fast_poll(pc_name, True)

    # Create a future to wait for the result
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    hermes_executor._pending_sync_tasks[task_id] = future

    try:
        result = await asyncio.wait_for(future, timeout=req.timeout + 60)
        return {
            "task_id": task_id,
            "exit_code": result.get("exit_code", -1),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error", ""),
        }
    except asyncio.TimeoutError:
        hermes_executor._pending_sync_tasks.pop(task_id, None)
        registry.set_fast_poll(pc_name, False)
        return {
            "task_id": task_id,
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "error": f"Task timed out after {req.timeout}s",
        }


@app.delete("/api/clients/{pc_name}")
async def disconnect_client(pc_name: str):
    registry.unregister(pc_name)
    return {"status": "ok", "message": f"Client '{pc_name}' marked offline"}


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Hermes Sessions (isolated per client)
# ═══════════════════════════════════════════════════════════════════════

class HermesRequest(BaseModel):
    prompt: str
    timeout: int = 300


@app.post("/api/clients/{pc_name}/hermes")
async def start_hermes_session(pc_name: str, req: HermesRequest):
    """Multi-turn Hermes chat for a client. Sessions persist across messages."""
    client = registry.get(pc_name)
    if not client or not client.online:
        raise HTTPException(status_code=400, detail=f"Client '{pc_name}' not available")

    try:
        from hermes_chat import session_manager
        session = await session_manager.get_or_create(pc_name)
        response = await session.send(req.prompt)

        # Save to history
        history = _get_chat_history(pc_name)
        history.append({"role": "user", "text": req.prompt, "ts": datetime.now().isoformat()})
        history.append({"role": "assistant", "text": response, "ts": datetime.now().isoformat()})
        _save_chat_history(pc_name, history)

        return {
            "session_id": session.session_id,
            "pc_name": pc_name,
            "status": "ok",
            "response": response,
        }
    except Exception as e:
        logger.error(f"Hermes chat error: {e}")
        import subprocess
        result = subprocess.run(
            ["hermes", "chat", "-q",
             f"Responde en español. Usuario: {req.prompt}",
             "-Q"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        return {
            "session_id": "fallback",
            "pc_name": pc_name,
            "status": "ok",
            "response": output or "(sin respuesta)",
        }


@app.get("/api/clients/{pc_name}/history")
async def get_chat_history(pc_name: str):
    """Get chat history for a client."""
    return {"messages": _get_chat_history(pc_name)}


@app.get("/api/hermes/{session_id}")
async def get_hermes_session(session_id: str):
    """Check status of a Hermes session."""
    session = hermes_executor.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session.session_id,
        "pc_name": session.pc_name,
        "status": session.status,
        "final_response": session.final_response,
    }


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Repo URL Management
# ═══════════════════════════════════════════════════════════════════════

class RepoURLRequest(BaseModel):
    repo_url: str


@app.get("/api/repo-url")
async def get_repo_url():
    return {"repo_url": CLIENT_REPO_URL}


@app.post("/api/repo-url")
async def set_repo_url(req: RepoURLRequest):
    global CLIENT_REPO_URL
    CLIENT_REPO_URL = req.repo_url
    logger.info(f"Repo URL changed → {req.repo_url}")
    return {"status": "ok", "repo_url": req.repo_url}


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Webhook
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/webhook/config")
async def get_webhook_config():
    return webhook_manager.get_config()


@app.post("/api/webhook/config")
async def set_webhook_config(config: WebhookConfigModel):
    webhook_manager.set_config(config.url, config.interval_seconds, config.enabled)
    return {"status": "ok"}


@app.post("/api/webhook/trigger")
async def trigger_webhook():
    await webhook_manager.send_now()
    return {"status": "sent"}


# ═══════════════════════════════════════════════════════════════════════
#  Health
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": SERVER_VERSION,
        "clients_online": registry.online_count,
        "clients_total": registry.total_count,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Background: stale client checker
# ═══════════════════════════════════════════════════════════════════════

async def stale_checker():
    """Periodically check for clients and Hermes sessions that have gone stale."""
    while True:
        await asyncio.sleep(30)
        registry.check_stale_clients()
        hermes_executor.cleanup_stale_sessions(max_idle=600)
        try:
            from hermes_chat import session_manager
            await session_manager.cleanup_stale(max_idle=600)
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    asyncio.create_task(stale_checker())
    logger.info(f"ALMA Server v{SERVER_VERSION} started")


# ═══════════════════════════════════════════════════════════════════════
#  Static Files — Dashboard (production)
# ═══════════════════════════════════════════════════════════════════════

_dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard", "dist")
if os.path.isdir(_dashboard_dir):
    app.mount("/", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")


# ═══════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
