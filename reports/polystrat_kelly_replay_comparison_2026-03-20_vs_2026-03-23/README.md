# Polystrat Kelly Comparison Note

This note compares the 4-day replay (`2026-03-23` to `2026-03-26` UTC), the 7-day replay (`2026-03-20` to `2026-03-26` UTC), and the 2-week replay (`2026-03-12` to `2026-03-26` UTC) using the same replay methodology and the same parameter set.

The goal here is to separate two different questions:

- is the optimizer doing better on its intended utility function when evaluated on historical data?
- does that improvement translate into better realized ROI and capital usage on the 4-day, 7-day, and 2-week windows?

## Compared reports

- 4-day report: [README.md](/Users/mariapia/DocumentsLocal/github/trader/reports/polystrat_kelly_replay_2026-03-23_2026-03-26/README.md)
- 7-day report: [README.md](/Users/mariapia/DocumentsLocal/github/trader/reports/polystrat_kelly_replay_2026-03-20_2026-03-26/README.md)
- 2-week report: [README.md](/Users/mariapia/DocumentsLocal/github/trader/reports/polystrat_kelly_replay_2026-03-12_2026-03-26/README.md)

## Shared configuration

```json
{
  "bankroll_usdc": 15.0,
  "floor_balance_usdc": 0.0,
  "min_bet_usdc": 1.0,
  "max_bet_usdc": 2.5,
  "n_bets": 1,
  "min_edge": 0.01,
  "min_oracle_prob": 0.1,
  "fee_per_trade_usdc": 0.0,
  "mech_fee_usdc": 0.01,
  "grid_points": 500
}
```

## 1. Optimizer log-utility result on historical data

The first thing worth stating clearly is that, on the historical replay rows, the optimizer usually does better on its own modeled utility objective.

More explicitly, the model being optimized here is the expected log-utility model, i.e. the expected log growth of bankroll under sequential betting. In the replay output, `g_improvement = utilityLog(b_new_model) - utilityLog(b_placed)` means the difference between the counterfactual Kelly choice and the historical actual bet size under that modeled log-utility objective.

4-day window:

- rows where `g_improvement` is defined: `315`
- counterfactual with positive `g_improvement`: `243` (`77.1%`)
- zero `g_improvement`: `72` (`22.9%`)

7-day window:

- rows where `g_improvement` is defined: `1045`
- counterfactual with positive `g_improvement`: `727` (`69.6%`)
- zero `g_improvement`: `318` (`30.4%`)

2-week window:

- rows where `g_improvement` is defined: `3297`
- counterfactual with positive `g_improvement`: `2364` (`71.7%`)
- zero `g_improvement`: `933` (`28.3%`)

Interpretation:

- this is a positive implementation signal
- the Kelly optimizer is usually selecting a stake with higher modeled log utility than the historical actual bet size
- in that narrow sense, the optimizer utility functions are behaving as intended on historical data

But the important caveat is this:

- log-growth here means exactly that, if we were placing bets sequentially, the modeled result is better for long-run bankroll growth
- that statement only holds under the replay inputs
- in particular, it assumes the input probability, and here especially `p_yes`, is sensible

So a better log-growth score does not automatically mean better realized ROI. It means the counterfactual is better under the model. If `p_yes` is not well calibrated, the optimizer can still look good on its objective while the realized backtest remains weak.

## 2. ROI and capital-spend analysis across 4 days, 7 days, and 2 weeks

### Latest 4 days

- Actual traded: `769.328328` USDC
- Counterfactual traded: `387.054003` USDC
- Capital reduction: `49.689%`
- Actual ROI: `-26.7021%`
- Counterfactual ROI: `-19.3897%`
- ROI delta: `+7.3124` percentage points

### Latest 7 days

- Actual traded: `2515.407016` USDC
- Counterfactual traded: `1085.532801` USDC
- Capital reduction: `56.845%`
- Actual ROI: `-15.1001%`
- Counterfactual ROI: `-19.8752%`
- ROI delta: `-4.7751` percentage points

### Latest 2 weeks

- Actual traded: `7763.722558` USDC
- Counterfactual traded: `3689.214529` USDC
- Capital reduction: `52.485%`
- Actual ROI: `-11.3266%`
- Counterfactual ROI: `-13.2457%`
- ROI delta: `-1.9191` percentage points

Interpretation:

- on both windows the Kelly replay spends much less capital
- on the latest 4 days that lower exposure comes with better realized ROI
- on the latest 7 days that lower exposure is not enough to improve the result, and realized ROI is worse than the historical actual baseline
- on the 2-week window the same pattern remains: capital spend is much lower, but realized ROI is still worse than the historical actual baseline

So the broad picture is:

- the optimizer is consistently more conservative in capital deployment
- the realized ROI result is unstable across windows
- the positive 4-day result does not generalize to the longer 7-day and 2-week samples

### What changes if neg-risk markets are removed?

The later neg-risk segmentation pass makes the cross-window result easier to interpret.

First, none of these windows is mostly non-neg-risk:

- 2-week window: `3297` total, `2943` neg-risk (`89%`), `354` non-neg-risk (`11%`)
- 7-day window: `1045` total, `902` neg-risk (`86%`), `143` non-neg-risk (`14%`)
- 4-day window: `315` total, `217` neg-risk (`69%`), `98` non-neg-risk (`31%`)

So the latest 4-day slice is still majority neg-risk, but it contains a materially larger non-neg-risk share than the 7-day and 2-week windows.

More importantly, if we remove neg-risk markets and keep only non-neg-risk rows under the original `min_oracle_prob = 0.1` setup, both the optimizer-readout and the ROI picture improve materially.

Optimizer reliability on non-neg-risk only, measured by the share of rows with positive `g_improvement`:

- 2-week non-neg-risk: `270 / 354` (`76.3%`) positive
- 7-day non-neg-risk: `97 / 143` (`67.8%`) positive
- 4-day non-neg-risk: `81 / 98` (`82.7%`) positive

So even after removing neg-risk markets, the new implementation still optimizes better than the historical sizing in a clear majority of cases.

ROI on non-neg-risk only under the same `mop=0.1` replay:

- 2-week non-neg-risk: actual ROI `-24.5%`, counterfactual ROI `-14.8%`, delta `+9.7` percentage points
- 7-day non-neg-risk: actual ROI `-20.3%`, counterfactual ROI `+3.7%`, delta `+23.9` percentage points
- 4-day non-neg-risk: actual ROI `-17.9%`, counterfactual ROI `+7.7%`, delta `+25.6` percentage points

So if neg-risk markets are excluded, the remaining non-neg-risk sample looks much better than the mixed sample on both dimensions:

- the optimizer still looks mechanically reliable
- the ROI result turns positive relative to baseline across all three windows

This strongly suggests that neg-risk market exposure is a major reason the aggregate mixed-window results look unstable and weak.

## 3. Why does this Kelly still produce better log utility in some small but unusual cases?

The short answer is:

- sometimes yes, fine-grid and rounding effects are part of it
- but no, that is not the main explanation

What the replay shows:

- in the 4-day window, only `20 / 243` positive-log-utility rows have a counterfactual bet within `5` cents of the historical actual bet
- in the 7-day window, only `57 / 727` positive-log-utility rows have a counterfactual bet within `5` cents of the historical actual bet
- tiny improvements do exist near the minimum stake, for example historical amounts like `0.999999` USDC being snapped to `1.0` USDC

So there are definitely some rows where the improvement is basically quantization:

- actual bet is effectively `1.0`
- Kelly returns `1.0`
- and the replay records a very small positive `g_improvement`

But that is only a small subset of the wins. Most positive `g_improvement` rows are not just small numerical improvements caused by fine-grid effects. They come from materially different stake sizes.

It is also useful to separate the rows where the historical bet was above the new replay cap of `2.5` USDC, because those are constrained comparisons.

Distribution of counterfactual sizes for rows with historical bet `> 2.5` USDC:


| Window | Rows  | `0`  | `(0, 1]` | `(1, 2]` | `(2, 2.5]` | Avg actual | Avg counterfactual |
| ------ | ----- | ---- | -------- | -------- | ---------- | ---------- | ------------------ |
| 4-day  | `41`  | `11` | `5`      | `18`     | `7`        | `4.7346`   | `1.1768`           |
| 7-day  | `167` | `55` | `29`     | `68`     | `15`       | `4.6364`   | `0.9828`           |


This suggests that the cap matters for fairness of comparison, but it is not the main story. In these rows the new optimizer usually does not push all the way to the new cap. It more often shrinks the old large bet into the `1` to `2` USDC range, or declines the trade entirely.

Direct old-vs-new log-utility comparison under the same constrained replay model:

4-day window:

- comparable rows: `242`
- new better: `230` (`95.0%`)
- old better: `12` (`5.0%`)
- ties: `0` (`0.0%`)

7-day window:

- comparable rows: `808`
- new better: `767` (`94.9%`)
- old better: `38` (`4.7%`)
- ties: `3` (`0.4%`)

2-week window:

- comparable rows: `2581`
- new better: `2324` (`90.0%`)
- old better: `227` (`8.8%`)
- ties: `30` (`1.2%`)

My current read is:

- fine-grid / discretization explains some of the tiny positive cases
- it does not explain the overall pattern where the optimizer usually improves modeled log utility
- the bigger issue is not grid search resolution
- when the older approach gives a larger optimizer value in some rows, that usually means that, under the replay inputs for that row, the historical bet size happened to sit closer to the local optimum of the log-utility objective than the new counterfactual size
- in other words, the optimizer ranking can still favor the old choice in some individual cases because the row-level inputs, especially `p_yes`, execution-price approximation, and fee assumptions, may make that historical size look better under the model
- the broader issue is that the modeled objective and the realized outcomes are not perfectly aligned, most likely because of probability quality and replay simplifications

## Practical conclusion

The most accurate summary is:

- the optimizer looks mechanically consistent with its intended log-utility objective on historical replay data
- that objective is meaningful only if `p_yes` is sensible
- the latest 4-day slice gives a positive ROI signal with much lower capital spend
- the latest 7-day slice does not confirm that signal
- the 2-week slice also does not confirm that signal, although the ROI penalty is smaller than in the 7-day run
- we do not currently see evidence that the 4-day advantage is explained by clearly better `p_yes` reliability
- some tiny Kelly wins are due to grid/rounding effects, but that is not the main reason the optimizer scores better on log utility

## Next steps

- run a proper `p_yes` calibration analysis by bucket, agent, tool, and date slice
- check whether the 4-day window is compositionally different from the 7-day window rather than simply "better predicted"
- test sensitivity to `grid_points` directly to quantify how much of the tiny `g_improvement` mass is discretization noise
- keep the optimizer, but treat probability quality and replay realism as the main validation bottlenecks
