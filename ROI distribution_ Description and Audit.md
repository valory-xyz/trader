jenslee/predict-825-fix-roi-audit-issues**Audit of ROI and agent performance Trader code**

Scope reviewed: ROI, agent performance, profit-over-time, mech-cost attribution, and position-details handling in the agent\_performance\_summary\_abci flow on origin/main at commit a223e0e5.

**High Severity**

1. The Omen/OLAS ROI path is configured against a staging subgraph proxy (predict-omen and olas\_mech\_subgraph), whereas the Polymarket ROI path uses a production-looking dedicated subgraph endpoint. This may be intentional, but it introduces an environment-consistency risk: data freshness, schema stability, or reliability may differ across platforms, which could affect comparability of reported performance metrics.
   Code: [skill.yaml\#L74-L88](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/skill.yaml#L74-L88), [skill.yaml\#L89-L103](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/skill.yaml#L89-L103), [skill.yaml\#L149-L163](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/skill.yaml#L149-L163), [skill.yaml\#L179-L193](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/skill.yaml#L179-L193)

   Mariapia Moscatiello
9:48 PM Mar 3
There is no "no-staging" predict-omen subgraph yet, so only mm should be fixed atm
https://valory-workspace.slack.com/archives/C0AD7F94X7S/p1772554637451999?thread_ts=1772226684.885899&cid=C0AD7F94X7S
Mariapia Moscatiello
Mariapia Moscatiello
9:01 PM Mar 12
Plan:
- tanya made some fixes
- I need to audit the subgraph before having it in prod
- agent code needs to be adjusted to use the new subgraph
- the prod can be made

   **Status: BLOCKED** — waiting on Mariapia to audit the new subgraph before prod switch.



2. Reported "Total ROI" is not a true total-capital or staking ROI.
   The implementation adds OLAS rewards to the numerator but never includes staked principal in the denominator. As a result, the metric is not a rigorous combined ROI and not a valid staking ROI; it is effectively trading ROI augmented by staking rewards. This can materially overstate returns when staking rewards are large relative to trading volume.
   Code: [behaviours.py\#L451-L480](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L451-L480)

   Mariapia Moscatiello
Mariapia Moscatiello
6:35 PM Mar 13
this was a design choice
Mariapia Moscatiello
Mariapia Moscatiello
6:44 PM Mar 13
NOT FIX

   **Status: WON'T FIX** — design choice per Mariapia.

3. Mech request attribution is keyed by title rather than a stable market or bet identifier, which is unsafe for known multi-bet behavior.
   Mech requests are aggregated as questionTitle \-\> count and later matched back to trading activity by title. Since agents are known to place multiple bets on some markets, this design collapses multiple request/bet relationships into a shared title bucket and then reallocates them heuristically instead of linking costs to the actual bet instances that consumed them. This can distort placed/unplaced counts, daily mech fee attribution, and downstream profit reporting.
   Code: [behaviours.py\#L968-L1000](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L968-L1000), [behaviours.py\#L1002-L1019](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1002-L1019), [behaviours.py\#L1054-L1101](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1054-L1101), [behaviours.py\#L1153-L1186](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1153-L1186)

   **Status: DEFERRED (Phase 2)** — structural change to rekey mech attribution from title to market/bet ID.

4. Prediction accuracy is materially distorted by known multi-bet behavior because it is computed per bet, not per market. Both Omen and Polymarket calculate accuracy as a simple win rate over individual bets, so markets with multiple bets are counted multiple times. Since agents are known to place multiple bets on the same market, the displayed "Prediction accuracy" can overweight a small number of repeatedly traded markets and diverge substantially from true market-level forecasting accuracy. This makes the metric misleading as an indicator of predictive quality.
   Code: [behaviours.py\#L493-L576](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L493-L576)

   **Status: WON'T FIX** — all bets, even on the same market, are independent decisions. Per-bet accuracy is the correct metric since each bet represents a separate prediction the agent chose to make. Deduplicating by market would discard real signal.

5. It is worth mentioning that gas fees are never accounted for in roi calculations.

   Mariapia Moscatiello
Mariapia Moscatiello
6:37 PM Mar 13
design choice for the moment

   **Status: WON'T FIX** — design choice per Mariapia.


6. Initial profit-over-time backfill can return no data when mech lookup is empty, even if trading profit data exists. After successfully fetching non-empty daily\_stats, \_perform\_initial\_backfill() aborts to an empty result when \_build\_mech\_request\_lookup() returns no entries, rather than proceeding with zero mech fees. This makes profit-over-time availability incorrectly dependent on mech subgraph availability.
   Code: [behaviours.py\#L1273-L1310](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1273-L1310)

   Mariapia Moscatiello
6:41 PM Mar 13
discuss better with team

   **Status: DEFERRED** — needs team discussion on whether to proceed with zero fees.

7. Incremental profit-over-time updates are not platform-aware when extracting titles for mech reconciliation.
   Although \_fetch\_daily\_profit\_statistics() correctly switches between Omen and Polymarket daily-stat queries, \_perform\_incremental\_update() always extracts titles from profitParticipants.question using Omen-specific parsing. Polymarket daily stats expose titles under profitParticipants.metadata.title instead. As a result, Polymarket incremental updates can fail to build mech lookup deltas, causing mech fees and net profit to be understated after the initial backfill.
   Code: [requests.py\#L461-L469](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/requests.py#L461-L469), [queries.py\#L398-L417](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/queries.py#L398-L417), [behaviours.py\#L1450-L1457](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1450-L1457)

   **Status: FIXED** — `_perform_incremental_update()` now checks `self.params.is_running_on_polymarket` and extracts from `metadata.title` for Polymarket, matching the pattern used in `_collect_placed_titles()` and `_calculate_mech_fees_for_day()`. Test: `TestPolymarketIncrementalTitleExtraction::test_polymarket_titles_extracted_in_incremental_update`.

8. Performance endpoint ignores requested window/currency while echoing them as applied.
   The /api/v1/agent/performance endpoint accepts window and currency, validates them, and echoes them in the response, but it always returns the same stored lifetime performance snapshot. This does not prevent the separate profit-over-time chart endpoint from changing shape across 7d/30d/90d/all-time views; however, it means aggregate metrics such as ROI and all-time profit are not recalculated per window even when the request implies that they are. Consumers may therefore incorrectly assume the summary metrics are window-specific.

Code: [handlers.py\#L424-L476](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/handlers.py#L424-L476)

   **Status: FIXED** — removed unused `window` and `currency` query parameters from the performance endpoint. The response now always returns `"window": "lifetime"` and `"currency": "USD"`, matching the actual data. No consumer was passing these parameters.

**Medium Severity**

1. Omen prediction accuracy counts invalid or unusable resolved bets in the denominator but excludes them from wins. \_calculate\_omen\_accuracy() sets total\_bets before filtering out invalid markets (INVALID\_ANSWER\_HEX) and bets with missing outcomeIndex, then skips those cases only when incrementing wins. This causes invalid or unusable resolved bets to reduce the reported accuracy rather than being excluded from the metric entirely.
   Code: [behaviours.py\#L517-L538](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L517-L538)

   **Status: FIXED** — `total_bets` is now incremented inside the loop after validation (matching Polymarket's pattern). Invalid/unusable bets are excluded from both numerator and denominator. Tests: `TestCalculateOmenAccuracy::test_invalid_answer_hex_excluded_from_denominator`, `test_bet_answer_none_excluded_from_denominator`, `test_all_invalid_returns_none`, `test_mixed_invalid_and_valid`.

2. Position-details responses are single-bet scoped rather than fully market-aggregated. In both the Omen and Polymarket helpers, the endpoint resolves one bet\_id, builds totals from that selected bet, and returns a one-element bets array. For markets with multiple bets, this can under-represent the full position and misstate market-level totals.

Omen: [predictions\_helper.py\#L373-L390](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/predictions_helper.py#L373-L390)
Polymarket: [polymarket\_predictions\_helper.py\#L474-L483](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py#L474-L483), [polymarket\_predictions\_helper.py\#L522-L588](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py#L522-L588), [polymarket\_predictions\_helper.py\#L675-L738](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py#L675-L738)

   **Status: BUG (both platforms)** — The endpoint is designed to show details for a specific bet, but `total_payout` and `net_profit` are overstated in multi-bet scenarios on both platforms.

   **Polymarket:** Uses `participant.totalPayout` (aggregating ALL bets on the market) directly as the single bet's payout. Confirmed with real data: a 9-bet participant ($20.72 traded, $25.97 total payout) reports net_profit=$23.47 for a single $2.50 bet instead of the correct ~$0.63 (37x overstatement).

   **Omen:** The proportional formula `payout_share = total_payout * (bet_amount / winning_total)` is correct in the **prediction history** path (where `_build_market_context` sees all bets). But in `fetch_position_details`, `GET_SPECIFIC_MARKET_BETS_QUERY` filters to 1 bet via `where: { id: $betId }`, so `winning_total = bet_amount` and the proportion collapses to 1.0, returning the full participant-level payout. Confirmed with real data: a 143-bet agent (0.025 xDAI each, 1.225 xDAI total payout) would report net_profit=1.20 for a single 0.025 bet instead of the correct -0.016.

3. Multi-bet mech reconciliation uses heuristic equal distribution across days.
   For repeated titles across multiple days, mech requests are evenly split across those days. For known multi-bet markets, this is only a heuristic and may materially misstate day-level fee attribution when requests cluster around specific bet placements. This weakens the reliability of profit-over-time and any day-based performance analysis.
   Code: [behaviours.py\#L1039-L1052](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1039-L1052), [behaviours.py\#L1054-L1101](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1054-L1101)

   **Status: DEFERRED (Phase 2)** — part of multi-bet structural fix.


4. Legitimate zero values are serialized as null in performance metrics.
   Exact zero values for fields such as breakeven profit, zero locked funds, or zero available funds are converted to null, making valid zero states indistinguishable from missing data. This reduces API correctness and can mislead UI logic or downstream consumers.
   Code: [behaviours.py\#L706-L721](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L706-L721)

   **Status: FIXED** — changed truthiness checks (`if value`) to explicit `is not None` checks. Zero values now correctly serialize as `0.0`. Test: `TestCalculatePerformanceMetrics::test_zero_values_preserved_not_null`.

5. Settled mech-request count conflates a state-based reference with an allocation-based series, and the mismatch can be structural rather than corrective.

The implementation uses two different notions of "settled mech requests":

* Reference settled count (state-based): computed as total\_mech\_requests \- open\_mech\_requests (a snapshot derived from current open markets/positions).

* Series settled count (allocation-based): computed implicitly as the sum of per-day daily\_mech\_requests in ProfitOverTimeData (derived from title-based joins plus heuristic distribution for unplaced and multi-day markets).

  These two quantities are not guaranteed to match even when subgraph data is correct, because daily mech fee attribution is performed via heuristics (e.g., even distribution of unplaced requests across available days, and splitting multi-day titles across days). Therefore, a mismatch between the stored series sum and the reference snapshot can be a normal outcome of the chosen attribution model, not evidence of data inconsistency.
  As a result, the "settled mech mismatch detected" path can trigger full profit-over-time rebuilds even when no underlying correction occurred, potentially causing unnecessary recomputation and unstable persistence behaviour across updates (e.g., when the open-market set changes, or when daily stats coverage changes).
  Code: [behaviours.py\#L1188-L1267](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1188-L1267) (rebuild decision in \_build\_profit\_over\_time\_data()), [behaviours.py\#L1320-L1416](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1320-L1416) and [behaviours.py\#L1515-L1586](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L1515-L1586) (series construction and incremental settled count updates).

   **Status: DEFERRED (Phase 2)** — part of multi-bet structural fix.

6. The profit-over-time chart endpoint applies window filtering, but its contract remains ambiguous.
   The endpoint resets cumulative profit to zero at the start of the selected window, which is valid if the intended contract is window-relative cumulative PnL. However, it returns that series under the field name delta\_profit while sourcing from lifetime cumulative data, so consumers may still misinterpret what the plotted values represent.
   Code: [handlers.py\#L645-L653](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/handlers.py#L645-L653) and [handlers.py\#L714-L746](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/handlers.py#L714-L746).

   **Status: FIXED** — renamed `delta_profit` to `cumulative_profit` in the API response. **Breaking change**: consumers must update to read `cumulative_profit` instead of `delta_profit`.

**Low Severity**

1. Mech-fee comments and naming in agent\_performance\_summary\_abci are misleading on Polygon. The code uses DEFAULT\_MECH\_FEE \= 1e16 and divides by 1e18, which correctly yields a fixed cost of 0.01 per request when interpreted as an 18-decimal scaled constant. However, several comments describe this as native-token/ETH/xDAI-style conversion, which can lead reviewers to incorrectly infer that Polygon mech costs are modeled in POL rather than as a fixed scaled fee amount. The implementation would be clearer if comments explicitly stated that the fee is stored as a value scaled to 18 decimals and normalized back to 0.01 during calculation.
   Code: [behaviours.py\#L73](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L73), [behaviours.py\#L424-L439](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/behaviours.py#L424-L439), [handlers.py\#L73](https://github.com/valory-xyz/trader/blob/a223e0e5/packages/valory/skills/agent_performance_summary_abci/handlers.py#L73)

   **Status: FIXED** — the old comments read `# 0.01 ETH`, `# 0.01 xDAI in wei (1e16)`, and `# (For Gnosis: xDAI ≈ USD, for Polygon: POL ≈ USD approximation)`, implying the fee is denominated in a specific native token. Updated to `# Fixed fee per mech request, scaled to 18 decimals (0.01 when divided by 1e18)` and `# Fixed 0.01 fee per request (DEFAULT_MECH_FEE is scaled to 18 decimals)`, which accurately describes the chain-agnostic constant.

---

**Fix Summary (Phase 1 — this PR)**

| Issue | Severity | Status |
|-------|----------|--------|
| M-1: Omen accuracy denominator | Medium | FIXED |
| M-4: Zero values as null | Medium | FIXED |
| H-7: Polymarket incremental titles | High | FIXED |
| L-1: Misleading mech-fee comments | Low | FIXED |

**Phase 2 (FIXED — timestamp-based mech-to-bet attribution)**

| Issue | Severity | Status |
|-------|----------|--------|
| H-3: Mech attribution by title | High | FIXED |
| M-3: Heuristic day distribution | Medium | FIXED |
| M-5: Settled mech mismatch rebuilds | Medium | FIXED |

Replaced heuristic even-distribution with deterministic 1:1 timestamp matching. Each mech request is assigned to its actual bet day via greedy chronological consumption of `blockTimestamp`. Unplaced requests land on the day the mech call was made. The settled count is now deterministic, eliminating spurious mismatch rebuilds.

Future improvement (not in scope): `feeUSD` / `finalFeeUSD` fields exist on both subgraphs and could replace the hardcoded fee constant with actual per-request fees. However, these fields are **null for historical requests** (pre-2024 on Gnosis), so a fallback to `DEFAULT_MECH_FEE` would still be needed. Consider adopting once historical data is no longer relevant or if the subgraph backfills old records.

**Remaining (Phase 3 — API/UX, needs product input)**

| Issue | Severity | Status |
|-------|----------|--------|
| H-8: Window/currency ignored | High | FIXED |
| M-6: Chart field naming | Medium | FIXED |

**Not fixing**

| Issue | Severity | Reason |
|-------|----------|--------|
| H-1: Staging subgraph | High | Blocked on subgraph audit |
| H-2: ROI excludes staked principal | High | Design choice |
| H-4: Per-bet accuracy | High | By design — bets are independent decisions |
| H-5: Gas fees not in ROI | High | Design choice |
| H-6: Backfill aborts on empty mech | High | Needs team discussion |
| M-2: Single-bet position details | Medium | Bug on both platforms — participant-level totalPayout attributed to single bet |
