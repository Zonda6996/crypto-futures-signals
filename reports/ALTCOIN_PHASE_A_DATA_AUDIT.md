# ALTCOIN Phase A — data availability and survivorship audit

**Date:** 21 August 2026  
**Protocol:** [`ALT-XSMOM-001-A`](../docs/ALTCOIN_PROTOCOL.md)  
**Verdict:** **STOP**

## Scope and safety

This phase assessed only whether an unbiased point-in-time Top 30 USD-M perpetual universe can be reconstructed. It did not calculate momentum, returns, PnL, or strategy parameters. It made zero network requests and loaded no observations or metadata at or after the sealed HOLDOUT boundary `2026-01-01T00:00:00Z`.

The rejected ETH strategy and its 2025 TEST were not imported, executed, inspected for tuning, or changed.

## Sources assessed

| Source | What it can establish | Material limitation |
|---|---|---|
| Binance Vision monthly USD-M klines | Hourly bars and quote volume for a symbol/month already known | Symbol-addressed files do not reveal a complete historical roster or prove omitted symbols do not exist |
| Binance Vision monthly funding | Funding records for known symbol/month pairs | Coverage and gaps still require a complete independent symbol registry |
| Binance USD-M `exchangeInfo` | Current contract metadata | A roster retrieved now is post-HOLDOUT and omits contracts delisted earlier; it cannot be a historical registry |
| Open-interest history | Potential liquidity diagnostic | No complete point-in-time series is present in the project |

## Audit implementation

`research.altcoin_phase_a_audit` adds isolated controls for:

- rejection of requests, cache writes, and cache reads that touch the HOLDOUT;
- explicit contract lifecycle and provenance records;
- deterministic stablecoin, leveraged-token, wrapped/duplicate, age, delisting, and coverage exclusions;
- trailing 30-day quote-volume ranking using observations strictly before each decision;
- deterministic volume/onboard/symbol tie-breaking;
- rejection of a current-only roster as a historical registry;
- canonical JSON and SHA-256 artifact manifests.

The implementation is independent of the old ETH pipeline and imports neither `research.test_opening` nor strategy search code.

## Survivorship assessment

The repository does not contain a complete dated pre-2026 lifecycle registry of all Binance USD-M perpetual contracts, including delisted instruments. Starting from the current roster would condition the sample on survival and would also reveal post-HOLDOUT membership. Trying archive URLs only for currently known symbols cannot discover omitted delisted contracts and therefore cannot close this gap.

Consequently, historical Top 30 membership cannot yet be certified. Coverage, late listings, delistings, renames/migrations, and archive gaps can be audited only after an independent registry supplies the candidate set. No synthetic membership examples are presented as empirical market results.

## Coverage result

| Requirement | Result |
|---|---|
| Historical contract registry | Unavailable |
| Delisted-contract discovery | Unavailable |
| Point-in-time Top 30 | Not certifiable |
| Klines / quote volume | Potentially available after registry is known |
| Funding | Potentially available; gaps remain to audit |
| Complete historical OI | Unavailable |
| HOLDOUT remained sealed | Yes |

## Verdict

**STOP.** Material survivorship risk is unresolved. Phase B signal implementation and parameter search are prohibited.

The only admissible next input is a complete, independently sourced and dated pre-2026 contract lifecycle registry containing listings and delistings. After owner review, Phase A may be rerun against that registry while keeping the HOLDOUT sealed; this does not authorise strategy work.

## Reproduction

Phase A only:

```bash
python3 -m unittest tests.test_altcoin_phase_a_audit -v
python3 -m research.altcoin_phase_a_audit
```

Machine result: [`reports/altcoin-phase-a/audit.json`](./altcoin-phase-a/audit.json).  
Checksums: [`reports/altcoin-phase-a/manifest.json`](./altcoin-phase-a/manifest.json).
