from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path); parser.add_argument("summary", type=Path)
    parser.add_argument("source_commit"); parser.add_argument("run_id")
    args = parser.parse_args()
    build = json.loads((args.workspace / "release" / "build-result.json").read_text())
    release = json.loads((args.workspace / "release" / "verified-release.json").read_text())
    text = f"""# ALT-MULTITF-005 release

- Revision: `ALT-MULTITF-005`
- Source commit: `{args.source_commit}`
- Public pathname: `{release['pathname']}`
- Public URL: `{release['url']}`
- Archive size: `{release['size']}` bytes
- Archive SHA-256: `{release['sha256']}`
- Anonymous full-download verification: **{release['anonymous_verification']}**
- Frozen roster: 40 symbols inherited from ALT-MULTITF-004
- Raw files: {build['acquisition']['files']} ({build['acquisition']['bytes']} bytes)
- Checkpoint config hash: `{build['config_hash']}`

## Restore

Download the `alt-multitf-005-release-{args.run_id}` artifact from this run, copy `verified-release.json` to `docs/altcoin-multitf-005-blob.json`, then run:

```bash
python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data
```

Restore verifies archive size/SHA-256, safe paths, and every normalized manifest file. No Blob secret is required.

## Boundaries

This run performed data acquisition, normalization, eligibility, packaging and publication only. It did **not** run Phase 2, signals, backtests, PnL, parameter search, or read sealed holdout data.
"""
    args.summary.write_text(text, encoding="utf-8"); return 0


if __name__ == "__main__": raise SystemExit(main())
