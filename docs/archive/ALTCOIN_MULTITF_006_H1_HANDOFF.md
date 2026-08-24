# ALTCOIN_MULTITF_006 (H1 "Daily trend, long-biased") — handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`**.
Branch work continues on `phase6-h1-daily-trend`. Freeze proof: commit `fb5acc3`
(erratum `6e6e30d`, both pre-analysis), protocol doc
`docs/ALTCOIN_MULTITF_006_FROZEN_PROTOCOL.md`.

## Inputs

- Prior 005 inputs unchanged (primary `665ac7b7…83743d`, supplement v1 `a753585a…47bd5b`).
- New supplement v2 archive `altcoin-multitf-006-supplement.tar.gz`:
  **573,920,939 bytes, SHA-256 `487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56`**
  (BTC/ETH/DOT full history 2020-02..2026-08; all ten symbols for 2026-01..08;
  fresh public exchangeInfo snapshot at freeze time; deterministic normalization
  incl. new `1w` = 2016×5m buckets; raw-manifest sha256 in archive metadata).
- Merged tree v2 = primary + supplement v1 + supplement v2 under
  `<inputs-root>/merged` (no machine paths recorded).
- Composite manifest: `reports/artifacts/altcoin-multitf-006/input-manifest-v2.json`.

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **192** configurations |
| DEV sweep (accounting 2024; engine span from earliest history) | 192/192 valid, 0 invalid, 0 zero-trade, ~65 s wall |
| Eligibility | **3 of 192** pass all eligibility criteria |
| Statistical gates | none survive — min SPA p = **0.807** (≤0.05 required); max DSR probability = **0.308** (≥0.95); Holm = 1.0 |
| DEV verdict | `NO_SELECTION` (`verdict-dev.json`) |
| Confirmation stage | correctly not applicable (`verdict-final.json`: no DEV candidate) |

Best DEV candidate by protocol ordering (`66f887bd…`, hold=10d, side=both):
net +1.6 %/yr, annualized Sharpe 0.95, max DD −16 %, 172 trades, 10/10 assets,
concentration 0.18, 5/6 positive folds, median fold Sharpe 1.05 — economically
plausible-looking, statistically indistinguishable from noise once the search over
192 configurations is priced in.

## Interpretation (descriptive; nothing was tuned post-hoc)

1. Moving to daily horizon did remove the cost wall that killed ALT-MULTITF-005:
   friction is no longer the dominant term, and several configurations are net-positive.
2. One year of data with ~150–200 trades cannot statistically separate a weak edge
   (~Sharpe ≈ 1 point estimate) from zero after multiplicity correction. The frozen
   gates demand ≥95% confidence precisely to prevent noise-trading deployment.
3. Both windows remain honest: CONFIRM metrics were computed only inside the
   confirmation stage and only would have been for a DEV survivor.

## Where this leaves the research line

Options for any successor protocol must be decided BEFORE touching further data:
(a) accept the family as unproven and stop; (b) design a protocol with higher expected
per-trade edge or longer confirm horizons (more years, more symbols) so gates become
reachable; (c) widen the universe/timeframes within a NEW freeze. Re-running selection
on the same windows with adjusted parameters is prohibited by both protocols.

## Artifacts (`reports/artifacts/altcoin-multitf-006/`)

`input-manifest-v2.json` · `statistics-dev.json` · `eligibility-table-dev.json` ·
`selection-dossier-dev.json` · `verdict-dev.json` · `confirmation-report.json`(n/a) ·
`verdict-final.json` · `run-metadata-dev.json` · `development-metrics.csv` ·
`sweep-progress-dev.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                  # 37 passed
uv run python -m research.altcoin_multitf_phase6 --validate-grid   # count = 192
uv run python -m research.altcoin_multitf_phase6 --stage sweep    --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_multitf_phase6 --stage finalize --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_multitf_phase6 --stage confirm  --inputs-root <inputs>
```

Deterministic resume verified via checkpoint identity guard (schema/seed/grid count).
