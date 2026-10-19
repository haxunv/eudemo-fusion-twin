"""Delete field packets that no snapshot, command or renderer can still reference."""

from pathlib import Path


class FieldCache:
    def __init__(self, runtime: Path, publications=(), keep=16):
        self.runtime = Path(runtime)
        self.keep = keep
        self.publications = {item["key"]: dict(item) for item in publications}

    def record(self, reference, snapshot_revision):
        if reference:
            key = reference["key"]
            self.publications.pop(key, None)
            self.publications[key] = {"key": key, "path": reference["path"], "snapshot_revision": snapshot_revision}

    def saved(self):
        return list(self.publications.values())

    def collect(self, *, current_key, server_epoch, renderer, extra_protected=()):
        if renderer.get("server_epoch") != server_epoch or not renderer.get("ready"):
            return {"deleted": [], "bytes": 0}
        watermark = renderer.get("applied_revision", -1)
        protected = {current_key, renderer.get("applied_field_key"), renderer.get("applied_volume_field_key"),
                     renderer.get("pending_volume_field_key")}
        protected.update(extra_protected)
        protected.update(list(self.publications)[-self.keep:])
        for key, item in self.publications.items():
            if item["snapshot_revision"] > watermark:
                protected.add(key)
        deleted, reclaimed = [], 0
        for key, item in list(self.publications.items()):
            if key in protected:
                continue
            path = (self.runtime / item["path"]).resolve()
            if not path.is_relative_to((self.runtime / "fields").resolve()) or path.name != key + ".npz":
                continue
            try:
                size = path.stat().st_size if path.exists() else 0
                path.unlink(missing_ok=True)
            except PermissionError:
                continue
            self.publications.pop(key)
            deleted.append(key)
            reclaimed += size
        return {"deleted": deleted, "bytes": reclaimed}
