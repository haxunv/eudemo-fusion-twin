"""Register the project's codeless OpenUSD workflow API."""
from pathlib import Path
from pxr import Plug
from omni.cae.viz import Controller

Plug.Registry().RegisterPlugins(str(Path(__file__).resolve().parents[3] / "resources"))
Controller.add_schema_regex(r"^FusionTwin")
