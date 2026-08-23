# Research reporting standard (binding for any human or AI assistant)

This repository runs pre-registered research protocols. To keep results honest and
readable across sessions, ANY assistant or team member who executes a protocol (or
resumes work on one) MUST finish with the following, in this order:

## 1. Verdict first

State the final decision in one line before anything else:
`SELECT <key>` or `NO_SELECTION (<short reason>)`, plus which protocol/freeze produced it.

## 2. Simple comparison tables

- One row per configuration: parameters, net return, annualized Sharpe, max drawdown,
  positive folds, SPA p, DSR probability, Holm p, eligibility YES/no.
- Reference rows (bare baselines) in a separate small table for comparison.
- Numbers rounded for humans (percent, two decimals); exact values live in artifacts.

## 3. Plain-language interpretation

After the tables: 3–8 bullet points explaining WHAT happened and WHY, without jargon.
Every statistical gate mentioned in chat must be translated ("SPA 0.056 — не хватило
до лимита 0.05" not just "spa_p_above_limit").

## 4. Honest caveats

Explicitly list what blocks deployment (which gates failed, by how much) and what was
NOT tested. Never soften a `NO_SELECTION`.

## 5. Next steps

Concrete options with a recommendation; remind about PR links if a branch is unmerged.

## Hard rules

- Interim/block reports are descriptive only; selection happens exactly once, at
  finalize, on the complete frozen grid (no sequential peeking).
- Never report numbers that are not backed by committed artifacts under
  `reports/artifacts/<protocol>/`.
- The user communicates in Russian; chat reports must be in Russian unless asked
  otherwise. Repository docs stay in English.
- If a session ends mid-protocol, say explicitly what stage remains and how to resume.

Any AI starting work in this repo should read: `docs/HANDOFF.md` (current state),
`docs/RESEARCH_REPORTING_STANDARD.md` (this file), and the frozen protocol it executes.
