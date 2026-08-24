# ALTCOIN_MULTITF_005 Phase 4 Part 1 handoff

## Delivered

Part 1 reconstructs the missing baseline contract and implements the causal TF-native engine, Family A/B signals, next-bar execution, adverse tick/step rounding, exchange filters, fee/slippage/funding accounting, normalized returns, deterministic aggregation, frozen-grid generation and resumable chunk checkpoints. It does **not** run or claim the full sweep.

The prior historical Phase 3/Part 1 branch was unavailable. Consequently, `manifest.json` and `verdict.json` explicitly identify this as a reconstructed, non-empirical baseline. This limitation must remain visible in all Part 2 reporting.

## Verification commands

```bash
python -m pytest
python -m research.altcoin_multitf_phase4_runner --validate-grid
python -m research.altcoin_multitf_phase4_runner --dry-run --output /tmp/altcoin-phase4-part1
pnpm build
git diff --check
```

The authoritative frozen count is **5,832**. The earlier approximate count of 58,140 came from unavailable materials and is not reproducible; Part 2 must stop if `frozen_grid()` does not return 5,832.

## Part 2 entry gate

1. Start from this document's branch and commit; require a clean tree.
2. Verify tests and grid count before editing.
3. Acquire immutable development datasets and exchange metadata, hash every input, and leave evaluation sealed.
4. Extend the runner for the full dataset-backed sweep without changing engine semantics or grid topology.
5. Produce all statistical, robustness, selection and reproducibility artifacts required by the frozen protocol.
6. Return `NO_SELECTION` unless exactly one candidate passes every mandatory gate.

The Part 2 output directory is `reports/artifacts/altcoin-multitf-005-phase4/`. Large raw datasets, caches and transient chunks do not belong in git; manifests, diagnostics, compact result tables, verdict and checksums do.
