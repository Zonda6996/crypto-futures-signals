from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path


def verify(metadata_path: Path) -> dict:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("protocol_id") != "ALT-MULTITF-005" or metadata.get("access") != "public": raise RuntimeError("unexpected Blob metadata")
    request = urllib.request.Request(metadata["url"], headers={"User-Agent": "ALT-MULTITF-005-anonymous-verify/1.0"})
    if request.has_header("Authorization"): raise RuntimeError("anonymous verification cannot use Authorization")
    digest = hashlib.sha256(); size = 0
    with urllib.request.urlopen(request, timeout=300) as response:
        while chunk := response.read(8 * 1024 * 1024): digest.update(chunk); size += len(chunk)
    actual = digest.hexdigest()
    if size != metadata["size"] or actual != metadata["sha256"]: raise RuntimeError(f"anonymous Blob mismatch: size={size} sha256={actual}")
    return {**metadata, "anonymous_verification": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("metadata", type=Path); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    result = verify(args.metadata); args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print("anonymous verification PASS"); return 0


if __name__ == "__main__": raise SystemExit(main())
