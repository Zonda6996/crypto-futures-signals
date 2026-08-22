from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.error
from dataclasses import asdict
from pathlib import Path

from research.altcoin_multitf_compact_005 import (
    PROTOCOL_ID, ROOT_NAME, FileRecord, archive_url, assert_development_path,
    atomic_write, canonical, fetch, months, sha256_file,
)

FROZEN_ROSTER = (
    "XRPUSDT", "SOLUSDT", "ZECUSDT", "HYPEUSDT", "TRUMPUSDT", "DOGEUSDT", "ENAUSDT", "1000PEPEUSDT",
    "BNBUSDT", "SUIUSDT", "ADAUSDT", "BCHUSDT", "PUMPUSDT", "LINKUSDT", "WLDUSDT", "NEARUSDT",
    "ASTERUSDT", "AAVEUSDT", "BEATUSDT", "TAOUSDT", "AVAXUSDT", "ONDOUSDT", "WLFIUSDT", "HEMIUSDT",
    "UNIUSDT", "PENGUUSDT", "1000SHIBUSDT", "XLMUSDT", "ONGUSDT", "LTCUSDT", "LITUSDT", "DASHUSDT",
    "GALAUSDT", "FILUSDT", "ETCUSDT", "ACEUSDT", "BOMEUSDT", "TUTUSDT", "BTWUSDT", "POLUSDT",
)


def rebuild(root: Path, workers: int) -> dict:
    base = root / ROOT_NAME
    assert_development_path(base / "development")
    metadata = base / "metadata"
    snapshot = {
        "protocol_id": PROTOCOL_ID,
        "selection": "frozen roster restored from committed ALT-MULTITF-004 data-phase report; never reselected",
        "symbol_count": len(FROZEN_ROSTER),
        "symbols": list(FROZEN_ROSTER),
        "restored_at": "2026-08-22T00:00:00Z",
    }
    atomic_write(metadata / "roster.snapshot.json", canonical(snapshot))
    plan = [(s, d, y, m, start, end, archive_url(s, d, y, m)) for s in FROZEN_ROSTER for d in ("klines", "funding") for y, m, start, end in months()]
    atomic_write(metadata / "acquisition.plan.json", canonical(plan))

    def one(item: tuple) -> FileRecord | None:
        symbol, datatype, year, month, start, end, url = item
        target = base / "development" / "raw" / datatype / symbol / Path(url).name
        if not target.exists():
            try:
                atomic_write(target, fetch(url))
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise
        return FileRecord(str(target.relative_to(root)), target.stat().st_size, sha256_file(target), symbol, datatype, "5m" if datatype == "klines" else None, start, end, (url,), "frozen-restore")

    records: list[FileRecord] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in plan]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            record = future.result()
            if record:
                records.append(record)
            if index % 250 == 0:
                print(f"checked {index}/{len(futures)}, present {len(records)}", flush=True)
    records.sort(key=lambda item: item.path)
    present_urls = {record.source_inputs[0] for record in records}
    missing = [
        {"symbol": symbol, "datatype": datatype, "year": year, "month": month, "url": url}
        for symbol, datatype, year, month, _start, _end, url in plan
        if url not in present_urls
    ]
    manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "created_at": "2026-08-22T00:00:00Z", "files": [asdict(item) for item in records]}
    path = metadata / "raw-development-manifest.json"
    atomic_write(path, canonical(manifest))
    result = {
        "protocol_id": PROTOCOL_ID,
        "symbols": len(FROZEN_ROSTER),
        "files": len(records),
        "bytes": sum(row.size for row in records),
        "manifest_sha256": sha256_file(path),
        "missing_count": len(missing),
        "prior_revision_reference": {"protocol_id": "ALT-MULTITF-004", "files": 3291, "bytes": 568466246},
        "inventory_difference": {"files": len(records) - 3291, "bytes": sum(row.size for row in records) - 568466246},
    }
    atomic_write(metadata / "rebuild-provenance.json", canonical({
        **result,
        "scope": {"start": "2020-01-01T00:00:00Z", "end_exclusive": "2026-01-01T00:00:00Z", "markets": "Binance USD-M perpetual", "klines_timeframe": "5m", "datatypes": ["klines", "funding"]},
        "roster_rule": "immutable carry-forward of the ALT-MULTITF-004 pre-acquisition frozen roster; no reselection and no performance inputs",
        "missing_archives": missing,
        "holdout_read": False,
    }))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.root, args.workers), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
