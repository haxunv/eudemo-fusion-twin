"""Print the renderer heartbeat without importing NVIDIA packages."""
import json
import socket
from pathlib import Path

root = Path(__file__).resolve().parents[1]
status_file = root / "runtime" / "renderer.json"
status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {"ready": False}
try:
    with socket.create_connection(("127.0.0.1", 49100), timeout=1):
        status["signaling_port_open"] = True
except OSError:
    status["signaling_port_open"] = False
print(json.dumps(status, ensure_ascii=False, indent=2))
