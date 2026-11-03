# Audit fixes implementation plan

> For agentic workers: execute the independent audit domains with the systematic-debugging, test-driven-development and dispatching-parallel-agents workflows. Root owns integration and review.

**Goal:** Correct all 27 findings and additional consistency issues in the user-approved audit.
**Spec:** [Audit findings and fixes](../../audit-fixes-2026-11-03.md), covering the audit of baseline `7b35046`.
**Architecture:** Preserve Python standard-library CLI interfaces, replace incorrect mathematics, require adequate input coverage, and expose assumptions rather than invent unavailable market facts.
**Tech stack:** Python, unittest, mocked CLI fixtures.

## Constraints and rulings
- Work on `fix/audit-20261103`; publish the tested changes as a PR against `main`, as subsequently requested by the user. Leave merging to the maintainer.
- Existing audit supplies concrete inputs and expected outcomes; no new product design approval is needed for these authorized corrections.
- Do not access brokerage accounts or live market feeds. Git branch publication and PR creation are within the requested scope.
- No third-party runtime dependency. Preserve Python 3.8-compatible syntax and postponed annotations.
- Each domain owns its source directories and a separate new regression test file. Root alone edits `scripts/common.py` and top-level documentation.
- Financial heuristics are labeled as heuristics; insufficient or stale data must not become affirmative evidence.
- Existing tests that lock in erroneous behavior must be updated to the corrected documented contract, with the reason recorded.

## Tasks
- [x] Shared data: nonfinite rejection, identity preservation, BS deterministic limits, dividend parsing, market-aware time helpers, explicit capital unit/flow semantics.
- [x] Options: analytical payoff extrema and roots, GEX direction, EM labeling, payout multiplier, valid strategy strikes, fresh/comparable IV history, model caveats.
- [x] Decisions/technical: coverage gating, event risk adjustment, consistent entry price, mandatory pending gates, unrounded RR, aligned B8, prior-bar channels, strict dated RS, quant comparison validity, volume and argument guards.
- [x] Fundamentals/market/intraday: anomaly weights, as-of dividends, financial account/period validity, insider and tick semantics, missing short/VWAP data, zero consensus and A/H interpretation.
- [x] Documentation and full integration: correct formulas and claims, annotate compatibility changes, trace all findings to fixes/tests, independent review, run complete suite and command smoke checks.

## Verification protocol
Each implementer first adds meaningful assertions using the audit counterexamples and confirms failure. Then implement and run its focused tests. Root runs `python -m unittest discover -s tests`, investigates every failure, runs CLI help and offline demo/JSON checks, and checks `git diff --check`.

## Review focus
- Mixed missing/valid values and nonfinite fields must not manufacture strength/health.
- Old dates, market midnight and stale observations must remain explicit.
- Standard contract multipliers and identity fields must survive normalization.
- Text and JSON must describe the same corrected result.
- Legacy fixtures must not silently reinstate the previous incorrect policy.

## Progress
- Baseline at 7b35046: 232 tests passed in preceding audit; checkout clean before branch creation.
- PR preparation rerun: 310 tests pass in 26.837 seconds on Python 3.13.15; 72 CLI help commands pass, offline demo text and strict JSON pass, 74 sources parse in Python 3.8 syntax mode, and diff whitespace check passes.
- Independent review identified six additional boundary issues, all fixed and rechecked; reviewer reran 55 domain regressions successfully. Final assessment: no outstanding blocking calculation issue.
- Full audit mapping, interface changes and remaining empirical limitations: `docs/audit-fixes-2026-11-03.md`.

## PR preparation
- Synchronize both READMEs, SKILL, formula/interface references and all domain records with final behavior.
- Verify local documentation links, Python command options, version and test counts before publishing.
- Include audit mapping, compatibility changes, regression evidence and empirical limits in the PR.
