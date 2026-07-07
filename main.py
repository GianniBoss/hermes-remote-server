"""
Hermes Remote Agents — Server
FastAPI backend: WebSocket for clients, REST API for dashboard, webhook dispatch.

The server tells each client the GitHub repo URL on connect,
so clients always know where to check for updates.
"""
import os
import uuid
import logging
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ws_manager import manager
from client_registry import registry
from webhook import webhook_manager

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hermes-server")

# ── Config from env ───────────────────────────────────────────────────
CLIENT_REPO_URL = os.getenv(
    "CLIENT_REPO_URL",
    "https://github.com/GianniBoss/hermes-remote-client",
)
SERVER_VERSION = "1.0.0"

# ── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(title="Hermes Remote Server", version=SERVER_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────
class WebhookConfigModel(BaseModel):
    url: str
    interval_seconds: int = 30
    enabled: bool = True

class ExecRequest(BaseModel):
    command: str
    task_id: str | None = None

class RepoUrlUpdate(BaseModel):
    repo_url: str


# ═══════════════════════════════════════════════════════════════════════
#  WebSocket — Client Connections
# ═══════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{pc_name}")
async def ws_client_endpoint(ws: WebSocket, pc_name: str):
    """
    WebSocket endpoint for agent clients.
    Path param `pc_name` is the friendly name configured on the client.
    """
    await manager.connect(pc_name, ws)
    client_ip = ws.client.host if ws.client else "unknown"

    # Register in memory
    registry.register(pc_name, client_ip=client_ip)

    # First message to client: server handshake with repo URL
    await manager.send(pc_name, {
        "type": "handshake",
        "server_version": SERVER_VERSION,
        "repo_url": CLIENT_REPO_URL,
        "message": "Connected to Hermes Remote Server",
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "hello":
                # Client introduction on connect
                registry.register(
                    pc_name,
                    hostname=data.get("hostname", ""),
                    version=data.get("version", ""),
                    client_ip=client_ip,
                )
                logger.info(f"Client hello: {pc_name} v{data.get('version')} on {data.get('hostname')}")

            elif msg_type == "metrics":
                # Client sends system metrics
                registry.update_metrics(pc_name, data.get("data", {}))

            elif msg_type == "pong":
                pass  # keepalive response

            elif msg_type == "exec_result":
                # Client returns command execution result
                task_id = data.get("task_id", "unknown")
                logger.info(f"Task {task_id} from {pc_name}: exit={data.get('exit_code')}")

            elif msg_type == "update_status":
                # Client reports update progress
                logger.info(f"Update on {pc_name}: {data.get('status')}")

            else:
                logger.debug(f"Unknown message type from {pc_name}: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {pc_name}")
    except Exception as e:
        logger.error(f"WebSocket error for {pc_name}: {e}")
    finally:
        manager.disconnect(pc_name)
        registry.unregister(pc_name)


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Dashboard
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/status")
async def server_status():
    """Health check + basic stats."""
    return {
        "status": "ok",
        "version": SERVER_VERSION,
        "uptime": "n/a",
        "clients_total": registry.total_count,
        "clients_online": registry.online_count,
        "client_repo_url": CLIENT_REPO_URL,
    }

@app.get("/api/clients")
async def list_clients():
    """Get all registered clients with latest metrics."""
    return {
        "clients": [c.to_dict() for c in registry.get_all()],
        "total": registry.total_count,
        "online": registry.online_count,
    }

@app.get("/api/clients/{pc_name}")
async def get_client(pc_name: str):
    """Get a single client's details."""
    client = registry.get(pc_name)
    if not client:
        raise HTTPException(404, f"Client '{pc_name}' not found")
    return client.to_dict()

@app.post("/api/clients/{pc_name}/exec")
async def exec_on_client(pc_name: str, req: ExecRequest):
    """Send a command to be executed on a remote client."""
    if not manager.is_online(pc_name):
        raise HTTPException(404, f"Client '{pc_name}' is not online")

    task_id = req.task_id or str(uuid.uuid4())[:8]

    sent = await manager.send(pc_name, {
        "type": "exec",
        "command": req.command,
        "task_id": task_id,
    })

    if not sent:
        raise HTTPException(500, "Failed to send command to client")

    return {
        "task_id": task_id,
        "pc_name": pc_name,
        "command": req.command,
        "status": "sent",
        "timestamp": datetime.utcnow().isoformat(),
    }

@app.post("/api/clients/{pc_name}/update")
async def trigger_update(pc_name: str):
    """Tell a client to check for updates now."""
    if not manager.is_online(pc_name):
        raise HTTPException(404, f"Client '{pc_name}' is not online")

    await manager.send(pc_name, {"type": "update", "force": True})
    return {"status": "update_triggered", "pc_name": pc_name}

@app.post("/api/broadcast")
async def broadcast_message(message: dict):
    """Send a message to ALL connected clients."""
    await manager.broadcast(message)
    return {"status": "broadcast", "targets": manager.online_count}


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Webhook
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/webhook/config")
async def get_webhook_config():
    return webhook_manager.get_config()

@app.post("/api/webhook/config")
async def set_webhook_config(config: WebhookConfigModel):
    await webhook_manager.set_config(config.url, config.interval_seconds, config.enabled)
    return {"status": "ok", "config": webhook_manager.get_config()}

@app.post("/api/webhook/trigger")
async def trigger_webhook():
    result = await webhook_manager.send_now()
    return result


# ═══════════════════════════════════════════════════════════════════════
#  REST API — Repo URL Management
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/repo-url")
async def get_repo_url():
    """Get the client repo URL that clients use for auto-update."""
    return {"repo_url": CLIENT_REPO_URL}

@app.post("/api/repo-url")
async def set_repo_url(req: RepoUrlUpdate):
    """
    Change the repo URL and notify all connected clients.
    Clients will use the new URL for future auto-update checks.
    """
    global CLIENT_REPO_URL
    CLIENT_REPO_URL = req.repo_url
    # Notify all connected clients of the new repo URL
    await manager.broadcast({
        "type": "repo_url_changed",
        "repo_url": req.repo_url,
    })
    logger.info(f"Repo URL changed → {req.repo_url}, broadcast to {manager.online_count} clients")
    return {"status": "ok", "repo_url": req.repo_url, "notified_clients": manager.online_count}


# ═══════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
