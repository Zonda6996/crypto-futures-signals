# ALTCOIN_CARRY_WIDE_001 frozen protocol (H-CARRY-WIDE, exploratory 100-symbol carry)

Status: **frozen before any live evaluation**. Committed to git prior to the first
wide-universe run. This protocol adds a THIRD forward arm — **WIDE** — alongside the
published SAFE (SELECT FINAL-001) and RISK (SL-001) arms. Status: **EXPLORATORY** —
the arm makes no SELECT claim and passes no program gates; its purpose is universe
diversity for the TIDAL product and forward data accumulation. No parameter may be
changed after this commit.

## Hypothesis (exploratory)

The funding-carry premium is cross-sectional and scales with breadth: ranking 100
liquid perps instead of 10 surfaces more extreme-funding names and diversifies the
book. This arm observes, forward-only, whether that holds live.

## Universe rule (owner-approved list, frozen)

The universe is the explicit owner-approved list of **99 symbols** recorded in
`reports/artifacts/altcoin-carry-wide-001/universe-final.json` and documented in
`docs/WIDE-UNIVERSE-FINAL.md` (generated from Binance USDT-M PERPETUAL, TRADING,
quote=USDT, age ≥ 365 days, ranked by 24h quote volume, with owner decisions):

- **Returned by owner** (memes kept deliberately; inv-vol sizing limits their risk):
  PUMP, 1000PEPE, PENGU, FARTCOIN, 1000SHIB, 1000BONK;
- **Forced in by owner**: GRT (rank #130), **ASTER** (owner override — age 340 days
  < 365; first candidate for removal if forward shows pathological funding);
- **Removed by owner**: ESPORTS, DEXE, RED, LSK, SKYAI, MOVE, GPS, SPK, COW, BICO,
  PUNDIX, H, HOME;
- **Memes out** (not returned): TRUMP, MUBARAK, TUT, VELVET, PAXG, KOMA, NEIRO,
  1000FLOKI, POPCAT, BOME;
- The ten frozen universe symbols are all included.

Owner retains the right to remove overly volatile symbols during the forward; every
removal is journaled with date and reason. The list is stored in the forward state
with its discovery timestamp; re-discovery only refreshes volumes/ages for the SAME
symbol set (composition changes require a freeze amendment).

## Arm specification

Identical to the SELECT SAFE arm mechanics, with two declared differences:

- **K = 5 per side** (10 positions; breadth arm);
- Weights inverse-volatility normalized over the held book (gross = 1);
- Stop 3×Wilder-ATR(14) daily; full take at 1×stop-distance (single-shot);
- BTC beta-hedge (90d betas) as in SAFE;
- Costs 4+2 bps on turnover (accounting mark).

## Forward-only contract

- No in-sample backtest is run for this arm (zero DECIDE-window reads beyond the
  shared warmup bars of the runner, zero heritage cost);
- Journal: `forward/trades.jsonl` with `mode: WIDE`, state `forward/state.json`,
  same report section as SAFE/RISK;
- Warmup bars come from the live REST (160 daily bars per symbol) — no local storage
  beyond the journal/state;
- The sealed monitor reserve is never evaluated, as everywhere.

## Reporting

WIDE appears in `forward/report.md` with the same table (weight, entry, stop, take,
mark, PnL, equity hit). All WIDE statistics are labelled `exploratory` and are NOT
comparable to SELECT-grade results until (and unless) a future freeze promotes the
family with a full backtest.

## Prohibitions

No parameter changes (K, filters, windows) without a new freeze; no promotion of WIDE
statistics to SELECT-grade language in reports; the SAFE/RISK arms are untouched.

Artifacts: shared forward journal of `altcoin-carry-final-001/forward/`.
