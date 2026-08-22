from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs" / "test-opening-hashes.json"
FROZEN_SHA = "81f5ea590edbc04fadce762452801c1d365470d0"
TEST_START = "2025-01-01T00:00:00Z"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _source_path(symbol: str, record: dict) -> Path:
    period = record["period"]
    if record["kind"] == "klines":
        return ROOT / "data" / "cache" / "klines" / "1h" / symbol / f"{symbol}-1h-{period}.zip"
    return ROOT / "data" / "cache" / "funding" / symbol / f"{symbol}-fundingRate-{period}.zip"


def verify_all(require_source_cache: bool = False) -> dict:
    manifest = load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["frozen_research_commit"] == FROZEN_SHA
    assert manifest["test_boundary"] == TEST_START
    assert manifest["scope"] == "pre-TEST-only"

    research_paths = [item["path"] for item in manifest["research_artifacts"]]
    governance_paths = [item["path"] for item in manifest["governance_artifacts"]]
    assert research_paths == sorted(research_paths)
    assert governance_paths == sorted(governance_paths)
    paths = research_paths + governance_paths
    assert len(paths) == len(set(paths))
    assert all(not path.startswith("data/") and "2025" not in path for path in paths)
    for item in manifest["research_artifacts"] + manifest["governance_artifacts"]:
        payload = (ROOT / item["path"]).read_bytes()
        assert len(payload) == item["size"]
        assert sha256_bytes(payload) == item["sha256"]

    source_count = 0
    for symbol in sorted(manifest["pretest_sources"]):
        source = manifest["pretest_sources"][symbol]
        assert source["years"] == [2021, 2024]
        assert source["interval"] == "1h"
        records = source["files"]
        assert [(x["period"], x["kind"]) for x in records] == sorted((x["period"], x["kind"]) for x in records)
        assert all(record["period"] < "2025-01" for record in records)
        for record in records:
            assert len(record["sha256"]) == 64
            path = _source_path(symbol, record)
            if require_source_cache:
                assert path.exists(), f"missing frozen pre-TEST source: {path}"
                assert sha256_bytes(path.read_bytes()) == record["sha256"]
            source_count += 1
    assert source_count == manifest["pretest_source_file_count"] == 192
    return {"ok": True, "research_and_governance_artifacts": len(paths), "pretest_source_files": source_count}


if __name__ == "__main__":
    print(json.dumps(verify_all(require_source_cache=False), indent=2))
