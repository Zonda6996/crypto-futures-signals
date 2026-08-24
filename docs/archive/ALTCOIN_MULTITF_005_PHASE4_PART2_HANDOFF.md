# ALTCOIN_MULTITF_005 Phase 4 Part 2 handoff

Status: **full deterministic development sweep completed** on branch
`phase4-part2-full-sweep` (baseline commit `e8497929470ffdcba884c9c0eaaba7496b60f1db`).
The evaluation interval was never opened; every number below is development-only.

## Inputs (all immutable, SHA-256 verified before use)

| Input | Size (bytes) | SHA-256 |
| --- | --- | --- |
| Primary archive `altcoin-multitf-005.tar.gz` (revision ALT-MULTITF-005, source commit `f9ee53d7d0009b573bbeba0811b70712e49de3d2`) | 1,541,152,490 | `665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d` |
| Supplement archive `altcoin-multitf-005-supplement.tar.gz` (BTCUSDT, ETHUSDT, DOTUSDT; dev interval only) | 113,083,086 | `a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b` |

- Primary checkpoint config hash: `b63129f81b0bfcff4283b53a67aea2644e96016c4db5818d06b8899f8aee1474`.
- Primary raw manifest hash: `72f575297cf9565a0124cedafee0d939a9139954c5f5c3e5b34d661f410181f5`.
- Merged tree: 3,858 files, digest `8515e68a8cf024ee8b8de91e8c3bed4368459365d920b98ffdde4fbf0d0f97a8`
  (`reports/artifacts/altcoin-multitf-005-phase4/input-manifest.json`, per-file hashes in
  `<inputs-root>/input-verification.json`).
- Frozen protocol document hash is recorded inside the composite manifest.
- **Role of `sha256:02b03ddf…`**: this string from the assignment matches no artifact in this
  run (not the primary archive, not its raw manifest, not the build config hash). It is recorded
  verbatim in the composite manifest's `ambiguous_hash_note` and was NOT used as an input hash.
- Supplement sources (public, no credentials): Binance Vision monthly klines/fundingRate zips +
  one public `exchangeInfo` snapshot covering all ten frozen-universe symbols (the primary archive
  does not embed exchangeInfo). Supplement contains raw zips, normalized 5m/15m/30m/1h/2h/4h/1d
  csv.gz, normalized funding, audit quality report, manifests with per-file size+SHA-256, exact
  UTC bounds and source URLs. It adds symbols/files only; the merge refuses any overwrite or
  conflicting duplicate by construction.

## Critical data-contract finding (documented deviation guard)

The primary archive's normalized series span 2020-01..2025-12, i.e. they contain the *sealed*
2024 evaluation year. Loaders therefore hard-clip every series/funding event to
`[2021-01-01T00:00:00Z, 2024-01-01T00:00:00Z)` at load time and verify exact boundary coverage;
a post-sweep assertion confirmed **0** trades outside the development interval. No evaluation data
was hashed as a working input, analysed, or used.

## What was run (exact commands)

```bash
uv sync --frozen --group dev
uv run python -m pytest                                   # 37 passed (14 frozen + 23 new)
uv run python -m research.altcoin_multitf_phase4_runner --validate-grid   # count = 5,832
uv run python -m research.altcoin_multitf_phase4_sweep --validate-grid    # count = 5,832
# supplement build (public sources only):
uv run python research/altcoin_multitf_supplement.py --workspace <ws> --workers 6
# input verification + merge:
uv run python -m research.altcoin_multitf_phase4_sweep --prepare-inputs \
  --primary <primary.tar.gz> --supplement <supplement.tar.gz> \
  --inputs-root <inputs-root> --artifacts reports/artifacts/altcoin-multitf-005-phase4
# FULL sweep (all 5,832 configs; resumable atomic checkpoints):
uv run python -m research.altcoin_multitf_phase4_sweep --full-sweep \
  --inputs-root <inputs-root> --cache-dir <cache-dir> \
  --artifacts reports/artifacts/altcoin-multitf-005-phase4 --workers 12
# statistics + gates + verdict:
uv run python -m research.altcoin_multitf_phase4_sweep --finalize \
  --inputs-root <inputs-root> --artifacts reports/artifacts/altcoin-multitf-005-phase4
```

Paths above are placeholders; no machine-specific path is stored anywhere in git.

## Engine acceleration without semantic change

The full sweep uses a compact column-store fast path
(`research/altcoin_multitf_phase4_fast.py`) that reproduces the frozen engine's expressions
verbatim (identical operand order; verified after a fees-rounding mismatch was caught and fixed).
Equivalence against `evaluate_configuration` is enforced by differential tests: **400/400 exact
matches** on randomized synthetic datasets plus dedicated pytest cases, covering stop/take/
timeout paths, rejected orders, missing-bar branches, funding accrual and invalid inputs.
Rolling statistics reuse `statistics.fmean` over identical slices, so results are bit-for-bit
identical to the frozen engine.

## Results summary

**Final decision: `NO_SELECTION`** (`verdict.json`). The full sweep ran to completion —
**5,832 / 5,832 configurations evaluated**, zero invalid, zero zero-trade:

| Stage | Outcome |
| --- | --- |
| Engine validity | 5,832 valid / 0 invalid / 0 zero-trade |
| Trades per config | ~8k–60k aggregate trades each |
| Eligibility | **0 of 5,832 pass** — every configuration fails the very first frozen criterion (`positive_net_return`); best net return is **−3.2478 %** (`579f013fe88375a8df31`, annualized Sharpe −0.371, max DD −62.1 %) |
| SPA (complete valid space) | minimum p-value = 1.000 across all 5,832 |
| Deflated Sharpe | maximum probability ≈ 0.0057 vs required ≥ 0.95 (N = 5,832 trials) |
| Holm layer | computed for all keys; moot given the above |
| Bootstrap CI / neighbors / stress / temporal / long–short | vacuously empty — no candidate survived eligibility, so no finalist stage ran (machinery itself is covered by deterministic unit tests) |

`rejection-reasons.json` records the first-failure histogram:
`{"non_positive_net_return": 5832}`. Because zero candidates passed, the pre-registered
tie-breaking rule never had to disambiguate anything. Criteria were not relaxed anywhere;
per the frozen contract this outcome is exactly one of the two permitted results.

Sweep execution facts (from `sweep-completion.json`, `sweep-progress-checkpoint.json`,
`run-metadata.json`): seed `20250304`, 24 chunks × 243 configs, wall time **2,680 s** on
12 worker processes, atomic checkpoint after every chunk. Resume verification re-run reports
`pending_chunks=0` and completes in seconds without recomputation. A second independent
finalize run produced a byte-identical `statistical-tests.json` (SHA-256 match), confirming
pipeline determinism. Evaluation-seal audit (`evaluation-seal-verification.json`):
4,529,160 bars and 32,925 funding events inspected post-hoc through the loaders —
**0 violations** outside `[2021-01-01T00:00:00Z, 2024-01-01T00:00:00Z)`.

Observed frozen-grid property worth noting: configurations differing only in `exit_threshold`
produce identical evaluation output because the frozen causal engine never consumes that axis;
both grid entries remain distinct configurations and both appear in every table.

## Artifact inventory (committed under `reports/artifacts/altcoin-multitf-005-phase4/`)

- `input-manifest.json` — composite manifest (primary+supplement SHAs, protocol hash,
  merged-tree digest, ambiguous-hash note, universe, intervals)
- `grid-manifest.json` — full list of all 5,832 frozen configurations with parameters
- `development-metrics.csv` — compact per-config development metrics (all 5,832 rows)
- `statistical-tests.json` — SPA / naive / Holm / DSR per configuration + method metadata
- `eligibility-table.json` — per-config criterion flags and protocol ordering ranks
- `rejection-reasons.json` — first-failure histogram + best-by-return reference point
- `selection-dossier.json` — gate examination log (empty by construction here)
- `verdict.json` — deterministic final decision
- `run-metadata.json` — counts, timings, platform, seeds
- `evaluation-seal-verification.json` — seal audit evidence
- `sweep-progress-checkpoint.json`, `sweep-completion.json` — sweep progress/checkpoint metadata
- `repro-commands.txt` — exact reproduction recipe (placeholder paths only)

## Interpretation choices (conservative, fixed BEFORE results were inspected)

1. Sharpe gates use daily returns annualized by sqrt(365); ordering unaffected (uniform scale).
2. DSR effective trials N = all valid configurations (including zero-trade); SR variance across
   active configurations; population moments; probability via Bailey-Lopez de Prado PSR formula.
3. SPA: Hansen (2005) stationary bootstrap, mean block length floor(T^(1/3)), screened
   consistent p-values, seed `20250306`, 1,000 replicates, balanced panel of daily returns.
4. Holm correction applied across the same complete valid family as an additional layer;
   candidates must pass both SPA and Holm at alpha=0.05 (strictly stronger than protocol minimum).
5. Block bootstrap CI: circular blocks over trade net-PnL ordered by entry time,
   block length round(n^(1/3)), seed `20250305`, 2,000 replicates; gate on scaled lower bound > 0.
6. Neighbors: differ in exactly one grid axis (family/signal TF/windows/thresholds/ATR multiples/
   holding); denominator = valid evaluated neighbors; zero-trade neighbors count as failures.
7. Stress: fee x2 (8 bps), slippage x3 (6 bps), funding magnitude x2, funding sign-flip x2;
   each scenario must keep aggregate net positive.
8. Temporal consistency: median fold Sharpe > 0 AND >= 4 of 6 half-year folds positive.
9. Long/short gate: both sides present and both side nets strictly positive.
10. Tie-breaking: pre-registered protocol ordering itself resolves multi-passer cases
    (rank-1 wins); recorded here before results were generated.
11. Per-symbol sleeves of 10k initial equity each; portfolio net return normalized by 100k.

## Limitations

- Exchange filter metadata (tick/step/minQty/minNotional) necessarily comes from a current
  public snapshot; historical point-in-time filters are not publicly available. Same methodology
  as the original acquisition pipeline.
- The primary blob URL returned HTTP 403 ("Your store is blocked") during Part 2; the byte-exact
  primary archive was recovered from the GitHub Actions checkpoint artifact of run 32588704578
  and verified against the committed SHA-256 before use.
