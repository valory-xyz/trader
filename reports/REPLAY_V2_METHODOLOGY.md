### Replay Analysis Improvements — Working Document

**Date:** 2026-03-26
**Branch:** codex/analysis-replay
**Author:** Jose / Claude

---

#### Context

The existing replay analysis (commit `6a27319c`) replays historical Polystrat bets
against the new Kelly criterion using the realized fill price as a proxy for the
CLOB orderbook. This document tracks improvements to address fundamental issues
and extend the analysis to negRisk markets.

---

#### Issues in the Current Approach

**Issue 1 (Critical): Asymmetric spread not captured in counterfactual pricing**

The synthetic orderbook uses `price_no = 1 - executed_price_yes`. In reality,
`Ask_YES + Ask_NO > 1.0` (the market maker spread). Our log analysis showed
spreads of 20%+ on stock-range markets. This means:
- Counterfactual NO bets are systematically underpriced
- A historical YES fill at 0.40 creates a synthetic NO ask at 0.60, but the real
  NO ask may have been 0.85

**Fix:** Historical CLOB orderbooks and prices are not available (markets are
resolved, CLOB returns 0/1). The Gamma API search is unreliable. The best
available proxy remains the executed price, but we should:
- Document this limitation prominently
- Compute a spread estimate per bet: for bets where the actual side has
  executed_price c, assume the other side's best ask was at least
  `max(1 - c, c + 0.05)` (conservative spread estimate)
- Flag bets where the counterfactual switches sides (these are most affected)

**Issue 2 (Moderate): min_oracle_prob=0.1 masks the negRisk filtering problem**

The replay uses `min_oracle_prob=0.1`, allowing YES bets on markets where
`p_yes` is as low as 0.10. Production uses 0.5. The replay results don't reflect
production behavior — specifically, most negRisk range markets have `p_yes < 0.5`
and would be filtered in production but not in the replay.

**Fix:** Run replays at both `min_oracle_prob=0.1` (current) and `0.5` (production).
Compare how many bets each config takes and on which side.

**Issue 3 (Minor): Fixed bankroll doesn't track P&L across bets**

Each bet uses `bankroll=15.0` regardless of cumulative wins/losses. This slightly
overstates the counterfactual performance.

**Status:** Acknowledged but not fixing in this iteration. Would require sequential
replay with bankroll state, which changes the analysis structure significantly.

**Issue 4 (Minor): Grid search is degenerate with single-level synthetic book**

The 500-point grid always walks the same flat book. Not wrong, but the replay
doesn't exercise the multi-level book walk that matters in production.

**Status:** Inherent limitation of not having historical orderbooks. No fix possible
without historical CLOB data.

---

#### Plan

##### Phase 1: Improve pricing accuracy

1. For each bet in the snapshot, attempt to fetch both-side prices from the
   Polymarket Gamma API using the condition_id or market_id.
2. If available, use actual `outcomePrices` (YES and NO mid-prices) instead of
   inferring one from the other.
3. If not available (market may be delisted), fall back to the current
   `1 - executed_price` proxy but flag it.
4. Compute the spread for each bet: `Ask_YES + Ask_NO - 1.0`.

##### Phase 2: negRisk market segmentation

1. For each bet, determine if the market is negRisk (multi-outcome event) by
   checking the Gamma API `negRisk` field.
2. Tag each bet in the snapshot with `is_neg_risk: bool`.
3. Run the replay and produce separate statistics for:
   - All markets (combined)
   - negRisk markets only
   - Non-negRisk (standalone binary) markets only
4. Report: how many bets are negRisk? What's the ROI for each segment?

##### Phase 3: min_oracle_prob sensitivity for negRisk YES bets

1. Run replays with `min_oracle_prob` at 0.1, 0.3, 0.5 (production default).
2. For each config, report:
   - Total bets taken (YES vs NO)
   - negRisk bets taken (YES vs NO)
   - Aggregate ROI
   - ROI by segment (negRisk vs non-negRisk)
3. Specifically analyze: when `min_oracle_prob=0.5`, how many negRisk YES bets
   are filtered that would have been profitable?

##### Phase 4: New reports

1. Generate reports in `reports/polystrat_kelly_replay_v2_YYYY-MM-DD/`
2. Include:
   - `snapshot_enriched.json` — snapshot with negRisk tags and both-side prices
   - `replay_mop_01.json` — replay at min_oracle_prob=0.1
   - `replay_mop_03.json` — replay at min_oracle_prob=0.3
   - `replay_mop_05.json` — replay at min_oracle_prob=0.5
   - `README.md` — methodology, results, comparison with v1
   - Plots: ROI distributions split by negRisk/non-negRisk

---

#### Test Plan

Tests go in `tests/replay/test_polystrat_kelly.py` (extend existing).

New tests needed:

1. `test_synthesize_clob_inputs_uses_both_side_prices` — verify that when both-side
   prices are available, the synthetic book uses them directly instead of
   `1 - price`.

2. `test_replay_tags_neg_risk_markets` — verify negRisk tagging propagates through
   the replay pipeline.

3. `test_replay_segments_by_neg_risk` — verify that the summary can be split by
   negRisk and non-negRisk.

4. `test_min_oracle_prob_sensitivity` — verify that changing min_oracle_prob
   changes which bets are taken (especially YES on negRisk markets).

5. `test_counterfactual_no_side_uses_actual_no_price` — verify that when the
   counterfactual bets NO, it uses the actual NO ask price, not `1 - yes_price`.

---

#### Progress

- [x] Phase 1: Improve pricing accuracy
  - [x] Attempted Gamma API -- unreliable for historical markets
  - [x] CLOB API works for negRisk tagging but not historical prices
  - [x] Documented limitation: historical orderbooks unavailable
  - [ ] Add spread estimate column (deferred -- no reliable data source)
- [x] Phase 2: negRisk segmentation
  - [x] Fetched negRisk from CLOB API for 435 unique condition_ids
  - [x] Tagged 3297 bets: 2943 negRisk, 354 non-negRisk
  - [x] Split summary statistics by segment
- [x] Phase 3: min_oracle_prob sensitivity
  - [x] Ran replays at mop=0.1, 0.3, 0.5
  - [x] Compared: negRisk Kelly doesn't help (-0.4pp), non-negRisk helps at mop=0.1 (+23.9pp)
- [x] Phase 4: Reports
  - [x] Generated v2 reports in polystrat_kelly_replay_v2_2026-03-12_2026-03-26/
  - [x] README with methodology and findings
