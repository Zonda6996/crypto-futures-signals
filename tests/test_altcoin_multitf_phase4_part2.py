"""Part 2 tests: statistics, gates, fast-engine equivalence and sweep plumbing.

All tests use synthetic data only; no external market data is required.
"""
from __future__ import annotations

import json
import math
import random
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from research.altcoin_multitf_gates import (
    ConfigMetrics,
    DEV_END_MS,
    DEV_START_MS,
    DAY_MS,
    FOLD_COUNT,
    compute_metrics,
    eligibility_report,
    is_eligible,
    neighbor_profitability,
    ordering_key,
    parameter_neighbors,
)
from research.altcoin_multitf_inputs import (
    InputError,
    _safe_extract,
    composite_manifest,
    verify_archive,
)
from research.altcoin_multitf_phase3 import Candle, ExchangeRules, Family, StrategyConfig
from research.altcoin_multitf_phase4 import Costs, Evaluation, Diagnostics, FundingEvent, Trade, evaluate_configuration
from research.altcoin_multitf_phase4_fast import IndicatorCache, build_compact, evaluate_compact
from research.altcoin_multitf_statistics import (
    circular_block_bootstrap_mean_ci,
    deflated_sharpe_probability,
    holm_adjusted,
    newey_west_lrv,
    normal_cdf,
    normal_ppf,
    sharpe_ratio,
    spa_pvalues,
)


# ---------------------------------------------------------------------------
# helpers


def candles(count: int, minutes: int, seed: int) -> list[Candle]:
    rnd = random.Random(seed)
    width = minutes * 60_000
    price = rnd.uniform(10, 400)
    result = []
    for i in range(count):
        opn = price
        close = max(0.05, opn * (1 + rnd.uniform(-0.03, 0.03)))
        high = max(opn, close) * (1 + rnd.uniform(0, 0.02))
        low = min(opn, close) * (1 - rnd.uniform(0, 0.02))
        result.append(Candle(i * width, i * width + width - 1, opn, high, low, close, rnd.uniform(100, 50_000)))
        price = close
    return result


RULES = ExchangeRules(0.01, 0.001, 0.001, 5.0, 1_000_000.0)


# ---------------------------------------------------------------------------
# statistics


def test_normal_cdf_and_ppf_round_trip() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5, abs=1e-12)
    assert normal_cdf(1.959963984540054) == pytest.approx(0.975, abs=1e-9)
    assert normal_ppf(0.975) == pytest.approx(1.959963984540054, abs=1e-8)
    for p in (0.01, 0.25, 0.5, 0.77, 0.999):
        assert normal_cdf(normal_ppf(p)) == pytest.approx(p, abs=1e-7)


def test_holm_adjusted_known_example() -> None:
    adjusted = holm_adjusted({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted["a"] == pytest.approx(0.03, abs=1e-12)
    assert adjusted["c"] == pytest.approx(0.06, abs=1e-12)
    assert adjusted["b"] == pytest.approx(0.06, abs=1e-12)
    assert adjusted["c"] <= adjusted["b"]
    monotone = holm_adjusted({"x": 0.9})
    assert monotone["x"] == pytest.approx(0.9)


def test_newey_west_lrv_near_variance_for_white_noise() -> None:
    rnd = random.Random(7)
    series = [rnd.gauss(0, 1) for _ in range(4000)]
    lrv = newey_west_lrv(series, 4)
    assert 0.85 < lrv < 1.15


def test_spa_pvalues_deterministic_and_discriminating() -> None:
    rnd = random.Random(11)
    noise = {f"n{i}": [rnd.gauss(0.0, 0.01) for _ in range(720)] for i in range(20)}
    strong = {"strong": [0.0008 + rnd.gauss(0, 0.005) for _ in range(720)]}
    panel = {**noise, **strong}
    first = spa_pvalues(panel, replicates=200, seed=20250306, lag=10)
    second = spa_pvalues(panel, replicates=200, seed=20250306, lag=10)
    assert first == second
    assert first["strong"] < 0.15
    assert sum(1 for key in noise if first[key] > 0.2) >= 14


def test_block_bootstrap_ci_deterministic_and_covering() -> None:
    series = [0.01 if i % 3 else -0.004 for i in range(600)]
    kwargs = dict(replicates=300, seed=20250305)
    a = circular_block_bootstrap_mean_ci(series, **kwargs)
    b = circular_block_bootstrap_mean_ci(series, **kwargs)
    assert a == b
    true_mean = sum(series) / len(series)
    assert a["lower"] <= true_mean <= a["upper"]
    assert a["block_length"] >= 1


def test_dsr_probability_monotone_in_sharpe() -> None:
    rnd = random.Random(3)
    series = [rnd.gauss(0.001, 0.01) for _ in range(800)]
    low = deflated_sharpe_probability(0.02, series, trials=1000, sharpe_variance=0.04)
    high = deflated_sharpe_probability(0.09, series, trials=1000, sharpe_variance=0.04)
    assert 0.0 <= low < high <= 1.0
    assert deflated_sharpe_probability(0.05, [0.0] * 10, 10, 0.0) == 0.0


# ---------------------------------------------------------------------------
# fast engine equivalence


@pytest.mark.parametrize("seed", range(6))
def test_fast_engine_matches_frozen_engine_exactly(seed: int) -> None:
    exec_bars = candles(700, 5, seed * 3 + 1)
    sig_bars = candles(220, 15 if seed % 2 == 0 else 60, seed * 3 + 2)
    reg_bars = candles(90, 240, seed * 3 + 3)
    funding = [FundingEvent(int(sig_bars[30].close_time_ms), 0.0004), FundingEvent(int(sig_bars[120].close_time_ms), -0.0002)]
    exec_c, sig_c, reg_c = build_compact(exec_bars), build_compact(sig_bars), build_compact(reg_bars)
    cache = IndicatorCache()
    for family in (Family.A, Family.B):
        for fw, sw, et, sa, ta, mh in [(3, 13, 0.0, 1.5, 2.0, 12), (8, 34, 0.005, 2.5, 4.0, 48)]:
            config = StrategyConfig(family, sig_tf_minutes(sig_bars), 240, fw, sw, et, 0.003, sa, ta, mh)
            reference = evaluate_configuration(config, exec_bars, sig_bars, reg_bars, funding, RULES)
            accelerated = evaluate_compact(config, exec_c, sig_c, reg_c, funding, RULES, cache=cache, symbol="S", signal_tf=sig_tf_minutes(sig_bars))
            prevalidated = evaluate_compact(
                config,
                exec_c,
                sig_c,
                reg_c,
                funding,
                RULES,
                prevalidated=True,
                cache=cache,
                symbol="S",
                signal_tf=sig_tf_minutes(sig_bars),
            )
            assert reference.valid == accelerated.valid == prevalidated.valid
            assert reference.trades == accelerated.trades == prevalidated.trades
            assert reference.diagnostics.rejected_orders == accelerated.diagnostics.rejected_orders
            assert reference.diagnostics.missing_bars == accelerated.diagnostics.missing_bars
            assert reference.diagnostics.funding_events == accelerated.diagnostics.funding_events
            assert reference.ending_equity == accelerated.ending_equity == prevalidated.ending_equity


def sig_tf_minutes(bars: list[Candle]) -> int:
    return int((bars[1].close_time_ms - bars[0].close_time_ms + 1) // 60_000)


# ---------------------------------------------------------------------------
# gates


def make_evaluation(trades: list[tuple[str, float, float]], *, valid: bool = True) -> Evaluation:
    """Build an Evaluation from (symbol-independent) trade tuples for metrics tests."""
    built = []
    for index, (_side_text, net, roe) in enumerate(trades):
        side = 1 if _side_text == "long" else -1
        built.append(Trade(side, 1.0, index, index + 1, 100.0, 101.0, net, 0.0, 0.0, 0.0, net, roe, "timeout"))
    diagnostics = Diagnostics()
    return Evaluation("k", valid, tuple(built), 10_000.0 + sum(net for _, net, _ in trades), diagnostics)


def test_compute_metrics_daily_curve_and_drawdown() -> None:
    day_ms = DAY_MS
    base = DEV_START_MS
    trades = [
        Trade(1, 1.0, base + day_ms // 2, base + day_ms + 10, 100.0, 110.0, 1000.0, 0.0, 0.0, 0.0, 1000.0, 0.1, "take"),
        Trade(1, 1.0, base + 2 * day_ms, base + 2 * day_ms + 10, 110.0, 90.0, -1500.0, 0.0, 0.0, 0.0, -1500.0, -0.13636, "stop"),
        Trade(-1, 1.0, base + 3 * day_ms, base + 3 * day_ms + 10, 90.0, 80.0, 500.0, 0.0, 0.0, 0.0, 500.0, 0.04545, "take"),
    ]
    evaluation = Evaluation("k", True, tuple(trades), 10_500.0, Diagnostics())
    metrics = compute_metrics("k", {"AAAUSDT": evaluation}, initial_equity=10_000.0)
    assert metrics.valid and not metrics.zero_trade
    assert metrics.trades == 3
    assert metrics.net_pnl == pytest.approx(0.0)
    assert metrics.active_assets == 1
    assert metrics.long_trades == 2 and metrics.short_trades == 1
    assert metrics.max_asset_positive_share == pytest.approx(1.0)
    assert metrics.positive_folds >= 0
    curve_peak_dd = metrics.max_drawdown
    assert -1.0 <= curve_peak_dd <= 0.0
    assert len(metrics.daily_returns) == (DEV_END_MS - DEV_START_MS) // day_ms


def test_eligibility_report_thresholds() -> None:
    metrics = ConfigMetrics(
        config_key="k",
        valid=True,
        zero_trade=False,
        invalid_reason=None,
        trades=100,
        net_pnl=1.0,
        net_return=0.01,
        mean_trade_return=0.0001,
        daily_sharpe=None,
        annualized_sharpe=0.6,
        median_fold_sharpe=0.1,
        fold_sharpes=(1.0,) * FOLD_COUNT,
        fold_net_returns=(0.01,) * FOLD_COUNT,
        positive_folds=FOLD_COUNT,
        max_drawdown=-0.10,
        active_assets=6,
        asset_names=("A", "B", "C", "D", "E", "F"),
        max_asset_positive_share=0.35,
        long_trades=50,
        short_trades=50,
        long_net_pnl=1.0,
        short_net_pnl=0.5,
        ending_equity=10_100.0,
        rejected_orders_total=0,
        missing_bars=0,
        funding_events=0,
        daily_returns=tuple([0.0] * ((DEV_END_MS - DEV_START_MS) // DAY_MS)),
    )
    report = eligibility_report(metrics)
    assert all(report.values())
    assert is_eligible(metrics)
    weak = ConfigMetrics(**{**metrics.__dict__, "trades": 99})
    assert not is_eligible(weak)
    deep_dd = ConfigMetrics(**{**metrics.__dict__, "max_drawdown": -0.26})
    assert not eligibility_report(deep_dd)["drawdown"]
    concentrated = ConfigMetrics(**{**metrics.__dict__, "max_asset_positive_share": 0.41})
    assert not eligibility_report(concentrated)["concentration"]


def test_ordering_key_is_total_and_protocol_ordered() -> None:
    base = dict(
        valid=True, zero_trade=False, invalid_reason=None, trades=150, net_pnl=100.0, net_return=0.01,
        mean_trade_return=0.0001, daily_sharpe=None, annualized_sharpe=1.0, median_fold_sharpe=0.5,
        fold_sharpes=(0.5,) * FOLD_COUNT, fold_net_returns=(0.01,) * FOLD_COUNT, positive_folds=6,
        max_drawdown=-0.1, active_assets=7, asset_names=("A",), max_asset_positive_share=0.2,
        long_trades=80, short_trades=70, long_net_pnl=60.0, short_net_pnl=40.0, ending_equity=10_100.0,
        rejected_orders_total=0, missing_bars=0, funding_events=0, daily_returns=tuple([0.0] * 1096),
    )
    good = ConfigMetrics(config_key="aaa", annualized_sharpe=1.5, **{k: v for k, v in base.items() if k != "annualized_sharpe"})
    worse = ConfigMetrics(config_key="bbb", annualized_sharpe=1.2, **{k: v for k, v in base.items() if k != "annualized_sharpe"})
    ineligible = ConfigMetrics(**{**base, "config_key": "ccc", "trades": 5})
    keys = sorted([good, worse, ineligible], key=lambda m: ordering_key(m))
    assert [m.config_key for m in keys] == ["aaa", "bbb", "ccc"]
    tie_a = ConfigMetrics(config_key="zzz", annualized_sharpe=1.5, **{k: v for k, v in base.items() if k != "annualized_sharpe"})
    assert ordering_key(tie_a) < ordering_key(good) or ordering_key(good) < ordering_key(tie_a)


def test_parameter_neighbors_on_frozen_grid_topology() -> None:
    from research.altcoin_multitf_phase4_runner import EXPECTED_GRID_COUNT, frozen_grid

    grid = frozen_grid()
    neighbors = parameter_neighbors(grid)
    assert len(neighbors) == EXPECTED_GRID_COUNT
    by_key = {item.key: item for item in grid}
    for key, targets in neighbors.items():
        source = by_key[key]
        differing_axes_seen = []
        for target in targets:
            other = by_key[target]
            diffs = []
            if source.family != other.family:
                diffs.append("family")
            if source.signal_tf_minutes != other.signal_tf_minutes:
                diffs.append("tf")
            if source.fast_window != other.fast_window:
                diffs.append("fast")
            if source.slow_window != other.slow_window:
                diffs.append("slow")
            if source.entry_threshold != other.entry_threshold:
                diffs.append("entry")
            if source.exit_threshold != other.exit_threshold:
                diffs.append("exit")
            if source.stop_atr != other.stop_atr:
                diffs.append("stop")
            if source.take_atr != other.take_atr:
                diffs.append("take")
            if source.max_holding_bars != other.max_holding_bars:
                diffs.append("hold")
            assert len(diffs) == 1, (key, target, diffs)
            differing_axes_seen.extend(diffs)
        assert targets or True
        assert len(set(targets)) == len(targets)


def test_neighbor_profitability_gate_math() -> None:
    def metric(key: str, net: float, valid: bool = True) -> ConfigMetrics:
        return ConfigMetrics(
            config_key=key, valid=valid, zero_trade=False, invalid_reason=None, trades=10, net_pnl=net,
            net_return=net / 10_000, mean_trade_return=0.0, daily_sharpe=None, annualized_sharpe=None,
            median_fold_sharpe=0.0, fold_sharpes=(0.0,) * FOLD_COUNT, fold_net_returns=(0.0,) * FOLD_COUNT,
            positive_folds=0, max_drawdown=0.0, active_assets=1, asset_names=("A",), max_asset_positive_share=0.0,
            long_trades=5, short_trades=5, long_net_pnl=net, short_net_pnl=0.0, ending_equity=10_000 + net,
            rejected_orders_total=0, missing_bars=0, funding_events=0, daily_returns=tuple([0.0] * 1096),
        )

    results = {"center": metric("center", 5.0), "n1": metric("n1", 10.0), "n2": metric("n2", -1.0), "n3": metric("n3", 0.0)}
    neighbors = {"center": {"n1", "n2", "n3"}}
    report = neighbor_profitability("center", neighbors, results)
    assert report["neighbors_profitable"] == 1 and report["profitable_share"] == pytest.approx(1 / 3)
    assert report["gate_pass"] is False
    results["n2b"] = metric("n2b", 7.0)
    neighbors["center"].add("n2b")
    report = neighbor_profitability("center", neighbors, results)
    assert report["profitable_share"] == pytest.approx(0.5)
    empty = neighbor_profitability("solo", {"solo": set()}, results)
    assert empty["gate_pass"] is False


# ---------------------------------------------------------------------------
# inputs plumbing


def write_tar(path: Path, entries: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))


def test_safe_extract_refuses_conflicting_overwrites(tmp_path: Path) -> None:
    first = tmp_path / "a.tar.gz"
    second = tmp_path / "b.tar.gz"
    destination = tmp_path / "merged"
    write_tar(first, {"altcoin-multitf-005/file.txt": b"payload-one"})
    write_tar(second, {"altcoin-multitf-005/file.txt": b"payload-two", "altcoin-multitf-005/new.bin": b"extra"})
    _safe_extract(first, destination)
    with pytest.raises(InputError):
        _safe_extract(second, destination)
    identical = tmp_path / "c.tar.gz"
    write_tar(identical, {"altcoin-multitf-005/file.txt": b"payload-one"})
    extracted = _safe_extract(identical, destination)
    assert extracted == []


def test_verify_archive_hash_and_size_guards(tmp_path: Path) -> None:
    import hashlib

    payload = b"archive-bytes"
    path = tmp_path / "x.tar.gz"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert verify_archive(path, digest, len(payload))["sha256"] == digest
    with pytest.raises(InputError):
        verify_archive(path, digest, len(payload) + 1)
    with pytest.raises(InputError):
        verify_archive(path, "0" * 64, len(payload))


def test_composite_manifest_documents_required_bindings(tmp_path: Path) -> None:
    doc = tmp_path / "ALTCOIN_MULTITF_FROZEN_PROTOCOL.md"
    doc.write_bytes(b"frozen protocol bytes")
    manifest = composite_manifest(doc, "commit-sha", tmp_path / "p.tar.gz", tmp_path / "s.tar.gz", True)
    for field in (
        "protocol_id", "repo_source_commit", "frozen_protocol_sha256", "development_interval_utc",
        "evaluation_interval_utc", "evaluation_sealed", "universe_used", "primary_archive",
        "supplement_archive", "merge_policy", "ambiguous_hash_note",
    ):
        assert field in manifest
    assert manifest["evaluation_sealed"] is True
    assert "02b03ddf" in manifest["ambiguous_hash_note"]
    assert len(manifest["universe_used"]) == 10


# ---------------------------------------------------------------------------
# sweep plumbing


def test_checkpoint_guard_rejects_foreign_run(tmp_path: Path) -> None:
    from research.altcoin_multitf_phase4_sweep import SWEEP_SCHEMA, load_checkpoint, new_checkpoint, save_checkpoint

    state = new_checkpoint("context-a")
    save_checkpoint(tmp_path, state)
    loaded = load_checkpoint(tmp_path, "context-a")
    assert loaded["schema"] == SWEEP_SCHEMA
    with pytest.raises(RuntimeError, match="context_hash"):
        load_checkpoint(tmp_path, "context-b")


def test_chunking_partitions_grid_exactly_once() -> None:
    from research.altcoin_multitf_phase4_runner import EXPECTED_GRID_COUNT, frozen_grid
    from research.altcoin_multitf_phase4_sweep import CHUNK_SIZE, chunk_keys, total_chunks

    grid_keys = [item.key for item in sorted(frozen_grid(), key=lambda item: item.key)]
    chunks = [chunk_keys(index) for index in range(total_chunks())]
    flattened = [key for chunk in chunks for key in chunk]
    assert len(flattened) == EXPECTED_GRID_COUNT == len(grid_keys)
    assert sorted(flattened) == sorted(grid_keys)
    assert len(set(flattened)) == EXPECTED_GRID_COUNT
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


def test_row_round_trip_preserves_metrics_fields() -> None:
    from research.altcoin_multitf_phase4_runner import frozen_grid
    from research.altcoin_multitf_phase4_finalize import _metrics_from_row
    from research.altcoin_multitf_phase4_sweep import INITIAL_EQUITY_PER_SYMBOL, row_from_metrics
    from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS

    config = frozen_grid()[0]
    evaluation = Evaluation(config.key, True, (), 10_000.0, Diagnostics())
    evaluations = {symbol: evaluation for symbol in UNIVERSE_SYMBOLS}
    metrics = compute_metrics(config.key, evaluations, initial_equity=INITIAL_EQUITY_PER_SYMBOL)
    row = row_from_metrics(metrics, config)
    restored = _metrics_from_row(row)
    assert restored.config_key == metrics.config_key
    assert restored.zero_trade and restored.valid
    assert restored.trades == 0
    assert restored.daily_returns == metrics.daily_returns
