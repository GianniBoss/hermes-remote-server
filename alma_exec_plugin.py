"""
ALMA Plugin for Hermes Agent — adds alma_exec tool.

Registers a tool that Hermes can use to execute commands on a remote ALMA client.
Also works as standalone CLI for testing.

Environment variables:
  ALMA_SERVER_URL  —  http://alma-server:8765
  ALMA_CLIENT_NAME —  PC-Recepcion (the target client)
"""
import json
import os
import sys
import urllib.request
import urllib.error


# ── Core function (works standalone or inside Hermes) ─────────────────

def alma_exec(command: str, timeout: int = 300, task_id: str = None) -> str:
    """Execute a command on the remote ALMA client and return the result."""
    server = os.getenv("ALMA_SERVER_URL", "http://localhost:8765")
    client = os.getenv("ALMA_CLIENT_NAME", "")

    if not client:
        return json.dumps({"error": "ALMA_CLIENT_NAME not set", "exit_code": -1, "stdout": "", "stderr": ""})

    url = f"{server}/api/clients/{client}/exec-sync"
    data = json.dumps({"command": command, "timeout": timeout}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        resp = urllib.request.urlopen(req, timeout=timeout + 60)
        result = json.loads(resp.read())
        return json.dumps({
            "exit_code": result.get("exit_code", -1),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error", ""),
        })
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if e.fp else ""
        return json.dumps({"error": f"HTTP {e.code}: {body}", "exit_code": -1, "stdout": "", "stderr": ""})
    except Exception as e:
        return json.dumps({"error": str(e), "exit_code": -1, "stdout": "", "stderr": ""})


# ── Hermes tool registration ─────────────────────────────────────────

try:
    from tools.registry import registry

    def check_requirements() -> bool:
        return bool(os.getenv("ALMA_SERVER_URL"))

    registry.register(
        name="alma_exec",
        toolset="alma",
        schema={
            "name": "alma_exec",
            "description": "Execute a shell command on a remote ALMA-managed PC. All operations on the remote PC go through this tool. The command runs as admin/SYSTEM on the target machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run on the remote PC (powershell, cmd, etc.)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait (default 300)",
                    },
                },
                "required": ["command"],
            },
        },
        handler=lambda args, **kw: alma_exec(
            command=args.get("command", ""),
            timeout=args.get("timeout", 300),
            task_id=kw.get("task_id"),
        ),
        check_fn=check_requirements,
        requires_env=["ALMA_SERVER_URL", "ALMA_CLIENT_NAME"],
    )
    print(f"[ALMA Plugin] Registered alma_exec tool", file=sys.stderr)

except ImportError:
    pass  # Not running inside Hermes


# ── Standalone CLI ────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ALMA_SERVER_URL=... ALMA_CLIENT_NAME=... python alma_exec.py <command>")
        sys.exit(1)

    cmd = " ".join(sys.argv[1:])
    result = alma_exec(command=cmd)
    parsed = json.loads(result)
    if parsed.get("stdout"):
        sys.stdout.write(parsed["stdout"])
    if parsed.get("stderr"):
        sys.stderr.write(parsed["stderr"])
    if parsed.get("error"):
        sys.stderr.write(f"ERROR: {parsed['error']}\n")
    sys.exit(parsed.get("exit_code", -1))
