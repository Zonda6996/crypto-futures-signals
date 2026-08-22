from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

EXPECTED_ROOT = "altcoin-multitf-005"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != EXPECTED_ROOT: raise RuntimeError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk() or member.isdev(): raise RuntimeError(f"unsupported archive member: {member.name}")
    return members


def verify_dataset(root: Path) -> dict:
    base = root / EXPECTED_ROOT; manifest_path = base / "metadata" / "normalized-development-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")); mismatches = []
    if manifest.get("protocol_id") != "ALT-MULTITF-005": raise RuntimeError("unexpected normalized manifest protocol")
    for record in manifest["files"]:
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != record["size"] or sha256(path) != record["sha256"]: mismatches.append(record["path"])
    if mismatches: raise RuntimeError(f"normalized manifest mismatch: {mismatches[:5]}")
    return {"verified_files": len(manifest["files"]), "manifest_sha256": sha256(manifest_path)}


def restore(root: Path, metadata_path: Path, overwrite: bool = False) -> dict:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("protocol_id") != "ALT-MULTITF-005" or metadata.get("access") != "public" or metadata.get("anonymous_verification") != "PASS": raise RuntimeError("unverified or unexpected release metadata")
    root.mkdir(parents=True, exist_ok=True); target = root / EXPECTED_ROOT
    if target.exists() and not overwrite: raise FileExistsError(f"refusing to overwrite existing dataset: {target}")
    fd, name = tempfile.mkstemp(prefix=f"{EXPECTED_ROOT}-", suffix=".tar.gz"); os.close(fd); temporary = Path(name)
    try:
        request = urllib.request.Request(metadata["url"], headers={"User-Agent": "ALT-MULTITF-005-restore/1.0"})
        with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
            while chunk := response.read(8 * 1024 * 1024): output.write(chunk)
        actual = sha256(temporary)
        if temporary.stat().st_size != metadata["size"] or actual != metadata["sha256"]: raise RuntimeError(f"bundle mismatch: size={temporary.stat().st_size} sha256={actual}")
        if target.exists():
            import shutil
            shutil.rmtree(target)
        with tarfile.open(temporary, "r:gz") as archive: archive.extractall(root, members=safe_members(archive), filter="data")
        verification = verify_dataset(root)
        return {"restored": str(target), "bundle_sha256": actual, "size": temporary.stat().st_size, **verification}
    except Exception:
        if target.exists():
            import shutil
            shutil.rmtree(target)
        raise
    finally: temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path("data")); parser.add_argument("--metadata", type=Path, default=Path("docs/altcoin-multitf-005-blob.json")); parser.add_argument("--overwrite", action="store_true"); args = parser.parse_args()
    print(json.dumps(restore(args.root, args.metadata, args.overwrite), indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
