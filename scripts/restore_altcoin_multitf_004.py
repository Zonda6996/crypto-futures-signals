from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

EXPECTED_ROOT = "altcoin-multitf-004"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != EXPECTED_ROOT:
            raise RuntimeError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError(f"unsupported archive member: {member.name}")
    return members


def restore(root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != "ALT-MULTITF-004":
        raise RuntimeError("unexpected protocol")
    root.mkdir(parents=True, exist_ok=True)
    target = root / EXPECTED_ROOT
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing dataset: {target}")
    fd, temporary_name = tempfile.mkstemp(prefix="altcoin-multitf-004-", suffix=".tar")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(manifest["url"], headers={"User-Agent": "ALT-MULTITF-004-restore/1.0"})
        with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
            while chunk := response.read(8 * 1024 * 1024):
                output.write(chunk)
        actual = sha256(temporary)
        if temporary.stat().st_size != manifest["size"] or actual != manifest["sha256"]:
            raise RuntimeError(f"bundle mismatch: size={temporary.stat().st_size} sha256={actual}")
        with tarfile.open(temporary, "r") as archive:
            archive.extractall(root, members=safe_members(archive), filter="data")
        return {"restored": str(target), "bundle_sha256": actual, "size": temporary.stat().st_size}
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--manifest", type=Path, default=Path("docs/altcoin-multitf-004-blob.json"))
    args = parser.parse_args()
    print(json.dumps(restore(args.root, args.manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
