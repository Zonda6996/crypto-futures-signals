# ALT-MULTITF-005 Phase 4 — Part 1 handoff

## Status

Part 1 is complete on branch `v0/phase4-engine-completion`. The saved Phase 3 baseline and Phase 4 draft were recovered from `v0/crypto-futures-signals-6e2ffb39`; no Phase 3 results were regenerated or changed.

The full frozen sweep is intentionally **not** part of this checkpoint. No holdout path was opened.

## Completed engine work

- TF-native decision clocks and next-open execution remain causal.
- Family A capped ranking now iterates until the cap residual is exhausted or no additional allocation is possible.
- Immutable `exchangeInfo.raw.json` filters are mandatory in runner execution; missing or malformed symbol filters are hard protocol violations.
- Development funding histories are loaded from normalized gzip CSV files with strict schema, ordering, finite-value, development-boundary, and mark-price validation.
- Funding cash flow is applied at publication timestamps crossed by each position and included in fill records.
- Entry and exit prices use adverse tick rounding; quantity uses step-size rounding; minimum quantity/notional and participation caps remain hard execution constraints.
- PnL, turnover, and costs are normalized to a fixed deterministic research equity of 1,000,000 quote units.
- Family A and Family B use the same execution-data contract for base, stress, and delay scenarios.
- Frozen checkpoint files remain atomic and resumable.

## Verified

```text
PYTHONPATH=. pytest -q tests/test_altcoin_multitf_phase3.py tests/test_altcoin_multitf_phase4.py
18 passed
```

`git diff --check` also passes.

## Part 2 exact continuation

1. Restore the immutable dataset using `docs/altcoin-multitf-005-blob.json`, and run the existing restore validator before evaluation.
2. Execute a small base/stress/delay smoke run for both families and inspect every hard violation. Do not weaken constraints to make the smoke pass.
3. Complete eligibility interval enforcement if the restored metadata proves that roster membership alone does not encode listing and perpetual status over time.
4. Run all 58,140 frozen base configurations with resume enabled.
5. Run mandatory stress, one-bar delay, and parameter-neighbor evaluations for selection-eligible candidates.
6. Replace collection placeholders with observed stress return and neighbor shares, then execute fold checks, DSR, Hansen SPA, liquidity, and concentration gates.
7. Produce leaderboards, statistics, verdict, artifact hashes, and the Phase 4 report. A winner is forbidden unless the sweep and every mandatory gate are complete.
8. Re-run verification from checkpoints and compare artifact hashes for reproducibility. Keep holdout sealed unless the frozen protocol explicitly authorizes opening it after development selection.

## Canonical commands

```bash
PYTHONPATH=. python -m research.altcoin_multitf_phase4_runner run --family A --dataset <dataset> --manifest reports/artifacts/altcoin-multitf-005-phase3/frozen-manifest.json --output reports/artifacts/altcoin-multitf-005-phase4
PYTHONPATH=. python -m research.altcoin_multitf_phase4_runner run --family B --dataset <dataset> --manifest reports/artifacts/altcoin-multitf-005-phase3/frozen-manifest.json --output reports/artifacts/altcoin-multitf-005-phase4
```

Use `--limit` only for smoke runs. Preserve the generated checkpoints between chats so Part 2 can resume rather than restart.
