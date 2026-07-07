#!/usr/bin/env bash
# ALMA Exec — wrapper for Hermes to execute commands on ALMA clients
# Usage: alma-exec <pc-name> <command>
# Env (optional): ALMA_SERVER_URL (default: http://localhost:8765)

SERVER="${ALMA_SERVER_URL:-http://localhost:8765}"
PC="${1?Usage: alma-exec <pc-name> <command>}"
shift
CMD="$*"

if [ -z "$CMD" ]; then
    echo "Usage: alma-exec <pc-name> <command>" >&2
    exit 1
fi

curl -s -X POST "$SERVER/api/clients/$PC/exec-sync" \
    -H "Content-Type: application/json" \
    -d "{\"command\": \"$CMD\", \"timeout\": 300}" \
    --max-time 360 | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('stdout'): print(d['stdout'])
if d.get('stderr'): print(d['stderr'], file=sys.stderr)
if d.get('error'): print('ERROR: '+d['error'], file=sys.stderr)
sys.exit(d.get('exit_code',-1))
"
