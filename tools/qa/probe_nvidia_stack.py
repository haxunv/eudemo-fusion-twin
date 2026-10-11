"""Run inside Kit to verify the installed NVIDIA workflow/CAE stack."""
import asyncio
import importlib
import json
import os
from pathlib import Path

import omni.kit.app


async def probe():
    app = omni.kit.app.get_app()
    for _ in range(5):
        await app.next_update_async()
    manager = app.get_extension_manager()
    names = ["omni.rtwt.controller", "omni.rtwt.inference", "omni.cae.viz",
             "omni.cae.index", "omni.cae.simdata", "omni.cae.delegate.npz",
             "omni.cae.delegate.nvdb"]
    result = {"extensions": {name: manager.get_enabled_extension_id(name) for name in names}}
    try:
        for module in ("omni.cae.viz", "omni.cae.schema", "omni.rtwt.controller.manifest"):
            importlib.import_module(module)
        import warp
        result["warp"] = warp.__version__
        result["ok"] = all(result["extensions"].values())
    except Exception as exc:
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    Path(os.environ["FUSION_STACK_PROBE_OUT"]).write_text(json.dumps(result, indent=2), encoding="utf-8")
    app.post_quit(0 if result["ok"] else 1)


asyncio.ensure_future(probe())
