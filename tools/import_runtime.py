"""Snapshot an installed Kit/CAE runtime without retaining source-build junctions."""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("kit", "extscache", "exts", "kit-cae/exts", "kit-cae/apps")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-build", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source, destination = args.source_build.resolve(), args.destination.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        parser.error("Source and destination must be separate directories")
    if destination.exists():
        parser.error("Destination already exists; choose a new versioned directory")
    for folder in FOLDERS:
        if not (source / folder).is_dir():
            parser.error(f"Missing installed runtime directory: {folder}")
    for folder in FOLDERS:
        print(f"Copying {folder}", flush=True)
        shutil.copytree(source / folder, destination / folder, symlinks=False,
                        ignore=shutil.ignore_patterns("__pycache__"))
    executable = destination / "kit/kit.exe"
    if not executable.is_file():
        raise RuntimeError("Snapshot has no Kit executable")
    record = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "source_build": str(source), "folders": list(FOLDERS),
              "source_links_materialized": True}
    (destination / "installation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    config = {"python": sys.executable, "kit_executable": str(executable),
              "extension_folders": [str(destination / folder) for folder in FOLDERS[1:]]}
    temporary = ROOT / "runtime.local.json.tmp"
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary.replace(ROOT / "runtime.local.json")
    print(f"Configured independent runtime: {destination}", flush=True)


if __name__ == "__main__":
    main()
