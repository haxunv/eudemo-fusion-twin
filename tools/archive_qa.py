"""Inspect QA image usage, or explicitly archive one QA directory before removing its files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024


def _plain_path(root, path):
    current = root
    for part in ("", *path.relative_to(root).parts):
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Links and junctions cannot be archived")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path leaves the project directory")
    return info


def _digest(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def verify_archive(path, expected):
    """Reopen the completed ZIP and independently verify every byte against the manifest."""
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest != expected:
            raise ValueError("Archive manifest differs from the source inventory")
        names = ["manifest.json", "source/"]
        names += ["source/" + directory + "/" for directory in manifest["directories"]]
        names += ["source/" + entry["path"] for entry in manifest["files"]]
        if sorted(archive.namelist()) != sorted(names):
            raise ValueError("Archive inventory differs from the manifest")
        for entry in manifest["files"]:
            digest, size = hashlib.sha256(), 0
            with archive.open("source/" + entry["path"]) as stream:
                for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if (size, digest.hexdigest()) != (entry["size"], entry["sha256"]):
                raise ValueError("Archive file checksum mismatch")


def archive_qa(root, relative, *, execute=False):
    root, relative = Path(root).resolve(), Path(relative)
    if relative.anchor or not relative.parts or ".." in relative.parts:
        raise ValueError("Choose a relative directory strictly inside runtime/qa")
    if relative.parts[0].rstrip(" .").casefold() in ("archive", "archives"):
        raise ValueError("The archive directory cannot be archived")
    qa = root / "runtime/qa"
    source = qa / relative
    if not stat.S_ISDIR(_plain_path(root, source).st_mode):
        raise ValueError("QA source must be a directory")
    resolved_source, resolved_qa = source.resolve(), qa.resolve()
    if not resolved_source.is_relative_to(resolved_qa) or resolved_source == resolved_qa:
        raise ValueError("Choose a directory strictly inside runtime/qa")
    if resolved_source.relative_to(resolved_qa).parts[0].casefold() in ("archive", "archives"):
        raise ValueError("The archive directory cannot be archived")
    files, directories = [], []

    def walk_error(error):
        raise error

    for current, children, names in os.walk(source, followlinks=False, onerror=walk_error):
        for name in sorted(children + names):
            path = Path(current) / name
            info = _plain_path(root, path)
            item = path.relative_to(source).as_posix()
            if stat.S_ISDIR(info.st_mode):
                directories.append(item)
            elif stat.S_ISREG(info.st_mode):
                files.append((item, path, info.st_size))
            else:
                raise ValueError("Only ordinary files and directories can be archived")
    files.sort()
    directories.sort()
    archive_path = qa / "archives" / ("--".join(relative.parts) + ".zip")
    report = {"mode": "archive" if execute else "dry_run", "source": relative.as_posix(),
              "file_count": len(files), "total_bytes": sum(size for _, _, size in files),
              "png_count": sum(path.suffix.casefold() == ".png" for _, path, _ in files),
              "png_bytes": sum(size for _, path, size in files if path.suffix.casefold() == ".png"),
              "archive": archive_path.relative_to(qa).as_posix()}
    if not execute:
        return report
    if archive_path.parent.exists() or archive_path.parent.is_symlink():
        _plain_path(root, archive_path.parent)
    archive_path.parent.mkdir(exist_ok=True)
    _plain_path(root, archive_path.parent)
    manifest = {"schema_version": 1, "source_directory": relative.as_posix(),
                "directories": directories, "files": []}
    # Exclusive creation never replaces an earlier archive, including a failed attempt.
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.mkdir("source/")
        for directory in directories:
            archive.mkdir("source/" + directory + "/")
        for item, path, _ in files:
            _plain_path(root, path)
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as stream, archive.open("source/" + item, "w", force_zip64=True) as output:
                for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            manifest["files"].append({"path": item, "size": size, "sha256": digest.hexdigest()})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    verify_archive(archive_path, manifest)

    def unchanged(entry):
        path = source / entry["path"]
        _plain_path(root, path)
        if _digest(path) != (entry["size"], entry["sha256"]):
            raise ValueError("Source changed during archiving; keep source files and the archive")
        return path

    # Check the whole original inventory before deleting, then each file at removal.
    for entry in manifest["files"]:
        unchanged(entry)
    for entry in manifest["files"]:
        unchanged(entry).unlink()
    report.update(verified=True, removed_files=len(files), archive_bytes=archive_path.stat().st_size)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", help="Directory relative to runtime/qa; inspect only")
    parser.add_argument("--archive", metavar="DIRECTORY", help="Verify a ZIP, then remove only its unchanged source files")
    args = parser.parse_args(argv)
    if bool(args.directory) == bool(args.archive):
        parser.error("Specify a directory for dry-run, or --archive DIRECTORY")
    print(json.dumps(archive_qa(ROOT, args.archive or args.directory, execute=args.archive is not None),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
