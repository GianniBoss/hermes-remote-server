# AGENTS.md — ALMA Remote Agent System

> This file is read by AI coding agents (Claude Code, Codex, Cursor, etc.)
> to understand the codebase and contribute effectively.
> Keep it up to date as the project evolves.

## What is ALMA?

ALMA is a client/server system for remote PC management and monitoring.
It lets a central dashboard control and monitor multiple Windows PCs
running the ALMA Agent client.

- **ALMA Server** — FastAPI backend (Python) + React dashboard with WebSocket connectivity
- **ALMA Client** — Single .exe Windows agent (Go) with system metrics, command execution, and auto-update

## Repository Structure

```
alma-remote-server/          ← GitHub: GianniBoss/alma-remote-server  (THIS REPO)
├── main.py                  FastAPI server — WebSocket, REST API, webhook
├── ws_manager.py            WebSocket connection manager
├── client_registry.py       Client state & metrics store
├── webhook.py               Webhook dispatcher (JSON POST to external URL)
├── requirements.txt         Python dependencies
├── dashboard/
│   ├── src/
│   │   ├── App.tsx          Main layout, routing, state
│   │   ├── ClientCard.tsx   Single client card with CPU/RAM/disk bars
│   │   ├── ChatPanel.tsx    Chat panel for sending commands to a client
│   │   ├── WebhookConfig.tsx Webhook URL/interval config form
│   │   ├── types.ts         TypeScript types
│   │   └── main.tsx         React entry point
│   ├── dist/                Built static files (served by FastAPI)
│   ├── vite.config.ts       Vite config with API proxy
│   ├── index.html           HTML shell
│   └── package.json
└── .gitignore

alma-client/                 ← GitHub: GianniBoss/alma-client
├── main.go                  Entry point — CLI flags, service mode, main loop
├── go.mod                   Go module (alma-client)
├── config/config.go         Config file read/write (JSON)
├── metrics/metrics.go       System metrics: CPU, RAM, disk, uptime (gopsutil)
├── wsclient/wsclient.go     WebSocket client with auto-reconnect
├── executor/executor.go     Command execution with timeout
├── updater/updater.go       GitHub Releases auto-update
├── installer/installer.go   Windows service installation (sc.exe)
└── .gitignore
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  ALMA SERVER                       │
│  ┌────────────┐  ┌──────────┐                    │
│  │  Dashboard  │  │  FastAPI  │                   │
│  │  (React)    │◄─┤  Backend  │                   │
│  │  :8765      │  │  :8765    │                   │
│  └────────────┘  └────┬─────┘                    │
│                       │ WebSocket                 │
└───────────────────────┼──────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  ALMA CLIENT  │ │  ALMA CLIENT  │ │  ALMA CLIENT  │
│  Go .exe      │ │  Go .exe      │ │  Go .exe      │
└──────────────┘ └──────────────┘ └──────────────┘
```

### WebSocket Protocol (JSON)

**Client → Server:**
```json
{"type": "hello", "pc_name": "PC-1", "hostname": "DESKTOP-ABC", "version": "1.0.0"}
{"type": "metrics", "data": { "cpu_percent": 4.4, "ram_percent": 85, ... }}
{"type": "pong"}
{"type": "exec_result", "task_id": "uuid", "exit_code": 0, "stdout": "...", "stderr": ""}
```

**Server → Client:**
```json
{"type": "handshake", "server_version": "1.0.0", "repo_url": "https://github.com/GianniBoss/alma-client"}
{"type": "ping"}
{"type": "exec", "command": "powershell Get-Process", "task_id": "uuid"}
{"type": "update"}
{"type": "repo_url_changed", "repo_url": "..."}
```

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clients` | List all clients with metrics |
| GET | `/api/clients/{name}` | Single client detail |
| POST | `/api/clients/{name}/exec` | Execute command on client (body: `{"command":"..."}`) |
| GET | `/api/clients/{name}/history` | Command history |
| DELETE | `/api/clients/{name}` | Disconnect client |
| GET | `/api/webhook/config` | Get webhook config |
| POST | `/api/webhook/config` | Set webhook config (body: `{"url":"...","interval_seconds":30,"enabled":true}`) |
| POST | `/api/webhook/trigger` | Trigger webhook immediately |

## Running Locally (Development)

### Server
```bash
cd alma-remote-server/

# Create venv & install deps
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt

# Run server
python main.py
# → http://localhost:8765

# Dashboard dev mode (separate terminal)
cd dashboard/
npm install
npx vite dev
# → http://localhost:5173 (proxies API to :8765)
```

### Client
```bash
cd alma-client/

# Run in console mode (debug)
go run . -server localhost:8765 -name "Test-PC"

# Build .exe for distribution
go build -ldflags="-s -w -H windowsgui" -o alma-client.exe .

# Install as Windows service (run as admin)
alma-client.exe -install -server 192.168.1.100:8765 -name "Office-PC"

# Uninstall service (run as admin)
alma-client.exe -uninstall
```

## Key Design Decisions

1. **Client in Go** → single ~6.5 MB .exe, no runtime, no dependencies. Compiles natively for Windows.
2. **Server in Python/FastAPI** → mature async WebSocket, easy integration with Python ecosystem.
3. **Dashboard in React + Vite + Tailwind 4** → same stack as user's other projects. Built static files served by FastAPI in production.
4. **WebSocket transport** → persistent bidirectional connection. Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s).
5. **GitHub Releases for auto-update** → no extra infra. Client polls GitHub API every 30 min.
6. **Server provides repo URL on handshake** → clients always know where to check for updates. Server can change it anytime via REST API.
7. **Windows Service via sc.exe** → `-install` / `-uninstall` flags. Integrates into Windows SCM natively.

## Building for Production

### Server
```bash
cd dashboard/ && npm run build  # builds to dist/
cd .. && python main.py         # serves dashboard from dist/
```

### Client
```bash
cd alma-client/
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w -H windowsgui" -o alma-client.exe .
```

## Tech Stack

- **Server:** Python 3.11+, FastAPI, uvicorn, websockets, httpx, pydantic
- **Dashboard:** React 19, TypeScript, Vite 7, Tailwind CSS 4
- **Client:** Go 1.22+, gorilla/websocket, gopsutil/v3, golang.org/x/sys

## Development Notes for AI Agents

- The server and client are separate repos. Changes to the WebSocket protocol must be coordinated across both.
- The Go module name is `alma-client`. All imports use this prefix: `alma-client/config`, `alma-client/wsclient`, etc.
- The dashboard build output (`dist/`) IS committed to git — this is intentional so the server works out of the box with `python main.py`.
- The client config file (`agent.conf`) is JSON. Defaults are set in `config/config.go`. CLI flags override config values.
- The updater downloads the new .exe to `%TEMP%/alma-agent-update.exe`, then writes a .bat script to swap and relaunch.
- WebSocket reconnect uses exponential backoff. Connection is NOT lost when metrics tick — only when the server goes down.
- All Python loggers use name `"alma-server"`.
