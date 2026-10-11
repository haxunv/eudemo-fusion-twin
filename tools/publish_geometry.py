"""Publish verified derived geometry by atomic replacement, preserving mapped USD readers."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    destination = ROOT / "assets"
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    entry = candidate / manifest["stage"]
    if not entry.is_file() or not entry.resolve().is_relative_to(candidate / "scene"):
        raise ValueError("Candidate does not contain its declared scene")
    files = sorted(path for path in (candidate / "scene").rglob("*") if path.is_file() and path != entry)
    files.extend((entry, candidate / "manifest.json"))
    for source in files:
        target = destination / source.relative_to(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".publish")
        shutil.copyfile(source, temporary)
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(temporary.read_bytes()).digest():
            raise RuntimeError(f"Candidate copy mismatch: {target}")
        os.replace(temporary, target)
    print(json.dumps({"published_files": len(files), "parts": manifest["total_part_count"],
                      "triangles": manifest["total_triangle_count"]}))


if __name__ == "__main__":
    main()
