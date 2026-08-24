"""Export daily return series of the FINAL-001 SELECT configuration.

Reads the committed sweep artifact (sweep-progress.json), extracts the winner's
2,007 daily returns over DECIDE 2021-01-01..2026-06-30, and writes a standalone
CSV + JSON artifact for future portfolio analysis with the external D6 line.
Reads nothing outside the DECIDE window; the monitor reserve is untouched.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ART = Path("reports/artifacts/altcoin-carry-final-001")
SELECT_KEY = "699326dc4971c5d9e437"
DECIDE_START_MS = 1_609_459_200_000
DECIDE_END_EXCLUSIVE_MS = 1_782_864_000_000
DAY_MS = 86_400_000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    payload = json.loads((ART / "sweep-progress.json").read_text(encoding="utf-8"))
    row = payload["rows"][SELECT_KEY]
    assert row["valid"] is True
    returns = row["daily_returns"]
    days = [d for d in range(DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS)]
    assert len(days) == len(returns) == 2007

    dates = [datetime.fromtimestamp(d / 1000, tz=timezone.utc).date().isoformat() for d in days]
    cfg = row["config"]

    csv_path = ART / "select-daily-returns.csv"
    lines = ["date,daily_return,equity_multiple"] 
    eq = 1.0
    for d, r in zip(dates, returns):
        eq *= 1.0 + r
        lines.append(f"{d},{r:.10f},{eq:.10f}")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    doc = {
        "purpose": "daily return series of the FINAL-001 SELECT config for portfolio analysis with the external D6 line (SMC-Research-Engine)",
        "protocol_id": "ALTCOIN_CARRY_FINAL-001",
        "selected_key": SELECT_KEY,
        "config": cfg,
        "frozen_spec": {
            "core": "A(3/3/1): 3d trailing-mean-funding rank, short top-3 / long bottom-3, daily rebalance",
            "weights": "inverse-volatility (30d sigma, gross 1.0)",
            "stop": "3 x Wilder ATR(14) from entry, daily close checks",
            "take": "full position at +1 x stop distance, single-shot",
            "hedge": "BTC-perp, notional = -(90d held-beta) x gross, resized daily",
        },
        "window_utc": ["2021-01-01", "2026-06-30"],
        "observations": len(returns),
        "in_sample_stats": {
            "net_return": row["net_return"],
            "annualized_sharpe": row["annualized_sharpe"],
            "max_drawdown": row["max_drawdown"],
            "positive_folds": row["positive_folds"],
        },
        "sources": {
            "sweep_progress": "reports/artifacts/altcoin-carry-final-001/sweep-progress.json",
            "sweep_progress_sha256": sha(ART / "sweep-progress.json"),
            "frozen_protocol_sha256": sha(Path("docs/ALTCOIN_CARRY_FINAL_001_FROZEN_PROTOCOL.md")),
            "engine": "research/altcoin_carry_final_001.py",
        },
        "caveats": [
            "in-sample series (DECIDE window only); forward validation pending",
            "heritage DSR at N=6090 is 0.019 (report-only) — moderate confidence",
            "monitor reserve 2026-07..08 intentionally absent",
        ],
        "daily_returns": returns,
        "dates": dates,
    }
    json_path = ART / "select-daily-returns.json"
    json_path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "csv": str(csv_path), "json": str(json_path),
        "observations": len(returns), "net_return": row["net_return"],
        "csv_sha256": sha(csv_path), "json_sha256": sha(json_path),
    }, indent=1))


if __name__ == "__main__":
    main()
