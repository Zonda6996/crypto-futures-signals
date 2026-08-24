# ALTCOIN_MULTITF_005 Phase 3 baseline specification

The original Phase 3 empirical artifacts were unavailable at reconstruction time. The machine-readable manifest and verdict in `reports/artifacts/altcoin-multitf-005-phase3/` therefore establish provenance only and make no performance claim.

Phase 4 inherits the frozen universe, intervals, market-data schema, execution costs and deterministic seeds from `ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`. Development and evaluation timestamps are disjoint; APIs used for configuration selection must receive development data only. Input datasets must be supplied by Part 2 and recorded by SHA-256 before any sweep.

The shared model in `research/altcoin_multitf_phase3.py` rejects malformed candles, unordered intervals, unsupported sides and invalid timeframe/window topology. JSON and hashing utilities are deterministic and intended for manifests and completion markers.
