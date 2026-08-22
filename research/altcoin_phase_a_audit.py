from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

HOLDOUT_START_ISO = "2026-01-01T00:00:00Z"
HOLDOUT_START_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
DAY_MS = 86_400_000
RANKING_WINDOW_MS = 30 * DAY_MS
MIN_LISTING_AGE_MS = 90 * DAY_MS
MIN_COVERAGE = 0.95
TOP_N = 30

STABLE_BASES = frozenset({"USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "USDE"})
WRAPPED_BASES = frozenset({"WBTC", "BTCB", "WETH"})
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


@dataclass(frozen=True)
class ContractRecord:
    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    onboard_ms: int
    delist_ms: int | None
    status: str
    provenance: str
    observed_at_ms: int


@dataclass(frozen=True)
class VolumeObservation:
    symbol: str
    open_time_ms: int
    quote_volume: float


@dataclass(frozen=True)
class UniverseMember:
    rank: int
    symbol: str
    trailing_quote_volume: float
    coverage: float


def assert_pre_holdout(*timestamps_ms: int | None) -> None:
    for timestamp in timestamps_ms:
        if timestamp is not None and timestamp >= HOLDOUT_START_MS:
            raise RuntimeError(f"sealed HOLDOUT access rejected: {timestamp} >= {HOLDOUT_START_MS}")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def guarded_fetch(
    url: str,
    *,
    start_ms: int,
    end_exclusive_ms: int,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> bytes:
    """Fetch only an explicitly bounded pre-HOLDOUT interval.

    The guard runs before the injected opener, allowing tests to prove that a
    prohibited request never reaches the network.
    """
    assert_pre_holdout(start_ms)
    if end_exclusive_ms > HOLDOUT_START_MS:
        raise RuntimeError("request interval crosses the sealed HOLDOUT boundary")
    request = urllib.request.Request(url, headers={"User-Agent": "altcoin-phase-a-audit/1.0"})
    with opener(request, timeout=60) as response:  # type: ignore[attr-defined]
        return response.read()  # type: ignore[no-any-return]


def write_guarded_json(path: Path, value: object, *, max_timestamp_ms: int) -> str:
    assert_pre_holdout(max_timestamp_ms)
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def read_guarded_json(path: Path, *, timestamp_fields: Sequence[str]) -> object:
    payload = path.read_bytes()
    value = json.loads(payload)

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in timestamp_fields and nested is not None:
                    assert_pre_holdout(int(nested))
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return value


def exclusion_reason(contract: ContractRecord) -> str | None:
    if contract.contract_type != "PERPETUAL":
        return "not_perpetual"
    if contract.quote_asset != "USDT":
        return "not_usdt_quoted"
    if contract.base_asset in STABLE_BASES:
        return "stablecoin_base"
    if contract.base_asset in WRAPPED_BASES:
        return "wrapped_or_pegged_duplicate"
    if contract.base_asset.endswith(LEVERAGED_SUFFIXES):
        return "leveraged_token"
    return None


def registry_issues(records: Sequence[ContractRecord]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for record in records:
        assert_pre_holdout(record.onboard_ms, record.delist_ms)
        if record.symbol in seen:
            issues.append(f"duplicate registry symbol: {record.symbol}")
        seen.add(record.symbol)
        if not record.provenance.strip():
            issues.append(f"missing provenance: {record.symbol}")
        if record.observed_at_ms >= HOLDOUT_START_MS:
            issues.append(f"post-HOLDOUT metadata observation: {record.symbol}")
        if record.delist_ms is not None and record.delist_ms <= record.onboard_ms:
            issues.append(f"invalid lifecycle: {record.symbol}")
    if records and all(record.provenance == "current_exchange_info" for record in records):
        issues.append("current exchange roster cannot establish a historical registry")
    if not any(record.delist_ms is not None for record in records):
        issues.append("registry contains no recoverable delisted contracts")
    return issues


def select_point_in_time_universe(
    records: Sequence[ContractRecord],
    observations: Sequence[VolumeObservation],
    *,
    decision_ms: int,
    expected_hourly_bars: int = 30 * 24,
    top_n: int = TOP_N,
) -> tuple[list[UniverseMember], dict[str, str]]:
    assert_pre_holdout(decision_ms)
    window_start = decision_ms - RANKING_WINDOW_MS
    by_symbol: dict[str, list[VolumeObservation]] = {}
    for row in observations:
        assert_pre_holdout(row.open_time_ms)
        if window_start <= row.open_time_ms < decision_ms:
            by_symbol.setdefault(row.symbol, []).append(row)

    exclusions: dict[str, str] = {}
    candidates: list[tuple[float, int, str, float]] = []
    for contract in records:
        reason = exclusion_reason(contract)
        if reason is None and contract.onboard_ms > decision_ms - MIN_LISTING_AGE_MS:
            reason = "listing_age_below_90d"
        if reason is None and contract.delist_ms is not None and decision_ms >= contract.delist_ms:
            reason = "already_delisted"
        if reason is None and contract.onboard_ms > decision_ms:
            reason = "not_yet_listed"
        rows = by_symbol.get(contract.symbol, [])
        coverage = len({row.open_time_ms for row in rows}) / expected_hourly_bars
        if reason is None and coverage < MIN_COVERAGE:
            reason = "trailing_coverage_below_95pct"
        if reason is not None:
            exclusions[contract.symbol] = reason
            continue
        volume = sum(max(0.0, row.quote_volume) for row in rows)
        candidates.append((-volume, contract.onboard_ms, contract.symbol, coverage))

    candidates.sort()
    members = [
        UniverseMember(index + 1, symbol, -negative_volume, coverage)
        for index, (negative_volume, _, symbol, coverage) in enumerate(candidates[:top_n])
    ]
    return members, exclusions


def artifact_manifest(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_bytes(path.read_bytes()) for path in sorted(paths, key=lambda item: str(item))}


def audit_fixture(
    records: Sequence[ContractRecord],
    observations: Sequence[VolumeObservation],
    decisions_ms: Sequence[int],
) -> dict:
    issues = registry_issues(records)
    memberships = []
    for decision_ms in decisions_ms:
        members, exclusions = select_point_in_time_universe(records, observations, decision_ms=decision_ms)
        memberships.append({
            "decision_ms": decision_ms,
            "members": [asdict(member) for member in members],
            "exclusions": exclusions,
        })
    verdict = "PASS" if not issues and memberships else "STOP"
    return {
        "phase": "ALTCOIN_PHASE_A",
        "holdout_loaded": False,
        "holdout_start": HOLDOUT_START_ISO,
        "strategy_or_pnl_computed": False,
        "registry_issues": issues,
        "memberships": memberships,
        "verdict": verdict,
    }


def run_capability_audit() -> dict:
    """Emit the no-download Phase A capability verdict.

    Existing project inputs provide current/archive symbol files only when a
    symbol is already known. They do not include a dated, complete historical
    USD-M contract registry. Therefore silently seeding from today's roster
    would create survivorship and post-HOLDOUT leakage.
    """
    return {
        "phase": "ALTCOIN_PHASE_A",
        "protocol_id": "ALT-XSMOM-001-A",
        "generated_at": "2026-08-21",
        "holdout_start": HOLDOUT_START_ISO,
        "holdout_loaded": False,
        "network_requests_made": 0,
        "strategy_or_pnl_computed": False,
        "sources_assessed": [
            {
                "source": "Binance Vision USD-M monthly klines and funding archives",
                "availability": "symbol-addressed archives can verify coverage after a symbol is known",
                "limitation": "the existing downloader has no point-in-time complete listing/delisting registry",
            },
            {
                "source": "Binance USD-M exchangeInfo/current roster",
                "availability": "current metadata only",
                "limitation": "retrieving it now is post-HOLDOUT and cannot recover omitted delisted contracts",
            },
            {
                "source": "Open interest history",
                "availability": "not present as a complete project history",
                "limitation": "cannot support a historical OI eligibility filter",
            },
        ],
        "coverage": {
            "historical_contract_registry": "unavailable",
            "delisted_contract_discovery": "unavailable",
            "klines": "potentially available only for a pre-established symbol registry",
            "quote_volume": "available in kline archives only for a pre-established symbol registry",
            "funding": "potentially available with symbol/month gaps to audit",
            "open_interest": "complete point-in-time history unavailable",
        },
        "survivorship_risk": "material and unresolved",
        "blocking_findings": [
            "A complete dated pre-HOLDOUT USD-M perpetual registry is not committed or otherwise available to this audit.",
            "Starting from the current exchange roster would omit historical delistings and use post-HOLDOUT information.",
            "Archive URLs are symbol-addressed, so archive coverage alone cannot prove that omitted symbols do not exist.",
            "Point-in-time Top 30 membership cannot be certified until the historical registry is independently supplied.",
        ],
        "verdict": "STOP",
        "next_required_input": "A complete independently sourced, dated pre-2026 contract lifecycle registry including delisted USD-M perpetuals; then rerun Phase A only.",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "reports" / "altcoin-phase-a" / "audit.json"
    report = run_capability_audit()
    write_guarded_json(output, report, max_timestamp_ms=HOLDOUT_START_MS - 1)
    print(json.dumps({"verdict": report["verdict"], "holdout_loaded": False}, sort_keys=True))


if __name__ == "__main__":
    main()
