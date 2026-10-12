"""Capture the shipped view cards from the running RTX renderer."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/ui")
    parser.add_argument("--view", choices=("overview", "front", "top", "section", "divertor"))
    args = parser.parse_args()

    def request(route, body=None):
        req = Request(args.base + "/api/" + route,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    def wait_ready():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            s = request("state")
            r = s["renderer"]
            if r.get("error") or r.get("volume_error"):
                raise RuntimeError(r.get("error") or r.get("volume_error"))
            if (r.get("ready") and r.get("server_epoch") == s["server_epoch"]
                    and r.get("applied_revision") == s["revision"]
                    and r.get("applied_field_key") == s["field_ref"]["key"]
                    and (s["state"]["mode"] != "volume" or
                         (not r.get("volume_pending") and r.get("applied_volume_field_key") == s["field_ref"]["key"]))):
                return s
            time.sleep(.1)
        raise TimeoutError("Renderer did not commit the requested view")

    def action(kind, **payload):
        s = wait_ready()
        command = request("action", {"type": kind, "request_id": uuid.uuid4().hex,
                          "server_epoch": s["server_epoch"], "renderer_epoch": s["renderer"]["renderer_epoch"], **payload})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            record = request("actions/" + command["request_id"])
            if record["status"] == "completed":
                return record
            if record["status"] in ("failed", "cancelled"):
                raise RuntimeError(record)
            time.sleep(.1)
        raise TimeoutError("Native capture did not complete")

    original = request("state")["state"]
    manifest = request("manifest")
    neutral = {"design": "conventional", "equilibrium": "sof", "heating": 50, "neon": False,
               "power": 2000, "flow": 1, "inlet": 300, "phase": 1, "scenario": "nominal",
               "mode": "volume", "heatScale": "log", "volumeStyle": "plasma", "cutaway": 80,
               "explode": 0, "opacity": 1, "fieldLines": True, "lineMotion": False,
               "orbit": False, "playing": False, "selected": "",
               "visible": {c["id"]: c.get("default_visible", True) for c in manifest["components"]}}
    entries = [("cameras/" + view + ".png", {"view": view}) for view in
               ([args.view] if args.view else ("overview", "front", "top", "section", "divertor"))]
    if not args.view:
        entries += [("designs/" + design + ".png", {"view": "divertor", "design": design,
                    "mode": "heatflux", "fieldLines": False}) for design in ("conventional", "longleg")]
    records = []
    try:
        for filename, patch in entries:
            request("state", {**neutral, **patch})
            s = wait_ready()
            action("reset_camera", view=s["state"]["view"])
            time.sleep(2)
            record = action("capture")
            with urlopen(args.base + record["result"]["capture_url"], timeout=30) as response:
                png = response.read()
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Renderer did not return PNG")
            target = args.output / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
            records.append({"path": filename, "sha256": hashlib.sha256(png).hexdigest(),
                            "capture_request_id": record["request_id"],
                            "state": s["state"], "field_ref": s["field_ref"],
                            "renderer": s["renderer"]["engine"], "source": "native RTX capture"})
            print(filename, len(png), flush=True)
        (args.output / ("manifest-" + args.view + ".json" if args.view else "manifest.json")).write_text(
            json.dumps({"cards": records, "scene_sha256": hashlib.sha256((ROOT / "assets/scene/fusion.usda").read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    finally:
        request("state", original)


if __name__ == "__main__":
    main()
