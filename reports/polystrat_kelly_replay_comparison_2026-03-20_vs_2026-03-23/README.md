# Polystrat Kelly Comparison Note

This note compares the 4-day replay (`2026-03-23` to `2026-03-26` UTC) with the 7-day replay (`2026-03-20` to `2026-03-26` UTC) using the same historical-approximation methodology and the same parameter set.

It is written to separate two different claims clearly:

- realized performance claim: whether the new sizing improved realized replay ROI versus actual historical behavior
- optimizer-intent claim: whether the new sizing is doing a better job of maximizing the modeled expected log-growth objective under the replay assumptions

## Compared reports

- 4-day report: [README.md](/Users/mariapia/DocumentsLocal/github/trader/reports/polystrat_kelly_replay_2026-03-23_2026-03-26/README.md)
- 7-day report: [README.md](/Users/mariapia/DocumentsLocal/github/trader/reports/polystrat_kelly_replay_2026-03-20_2026-03-26/README.md)

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

## Realized ROI comparison

4-day window:

- Actual ROI: `-26.7021%`
- Counterfactual ROI: `-19.3897%`
- ROI delta: `+7.3124` percentage points

7-day window:

- Actual ROI: `-15.1001%`
- Counterfactual ROI: `-19.8752%`
- ROI delta: `-4.7751` percentage points

Interpretation:

- The short 4-day window gives a positive realized signal.
- The broader 7-day window does not confirm that signal.
- So the new sizing is not currently supported as a production candidate by the broader realized-ROI evidence.

## Distribution comparison

4-day per-agent distribution:

- Actual mean ROI: `-24.000%`
- Counterfactual mean ROI: `-18.977%`
- Mean delta: `+5.023` percentage points
- Actual median ROI: `-25.333%`
- Counterfactual median ROI: `-24.314%`
- Median delta: `-1.556` percentage points

7-day per-agent distribution:

- Actual mean ROI: `-14.479%`
- Counterfactual mean ROI: `-20.074%`
- Mean delta: `-5.595` percentage points
- Actual median ROI: `-16.410%`
- Counterfactual median ROI: `-25.850%`
- Median delta: `-6.545` percentage points

Interpretation:

- On the broader 7-day window, the center of the ROI distribution moves in the wrong direction.
- This is consistent with the aggregate ROI result.

## Optimizer-intent comparison

The following check asks a different question:

- conditional on the replay assumptions,
- conditional on the estimated `p_yes`,
- conditional on the execution-price proxy,

did the Kelly grid search actually select a bet with higher expected log-growth than the historical actual bet size?

This does not prove the inputs are correct. It only tests whether the new sizing is internally consistent with the objective it was designed to optimize, given the replay inputs, especially the recovered mech `p_yes` values and the execution-price approximation.

### 4-day window

- rows with both valid actual and counterfactual log-growth values: `196`
- counterfactual higher than actual: `186`
- actual higher than counterfactual: `10`
- mean gap `G(counterfactual) - G(actual)`: `+1.001304`
- counterfactual negative log-growth improvements: `0`

### 7-day window

- rows with both valid actual and counterfactual log-growth values: `572`
- counterfactual higher than actual: `533`
- actual higher than counterfactual: `36`
- ties: `3`
- mean gap `G(counterfactual) - G(actual)`: `+0.948211`
- counterfactual negative log-growth improvements: `0`

Interpretation:

- On both windows, the new sizing is usually doing a better job of maximizing the modeled log-growth objective than the historical actual bet size.
- So the grid optimizer appears to be doing its intended job.
- The mismatch comes later: better modeled log-growth under the recovered mech `p_yes` inputs and the replay execution approximation does not reliably translate into better realized ROI on the broader window.

## Accurate conclusion

The most accurate statement is not:

- "the new algorithm is doing better overall"

The most accurate statement is:

- "the new algorithm is more faithful to its intended optimization objective under the model assumptions, but that improvement in modeled log-growth does not currently translate into better realized replay ROI on the broader 7-day sample"

This is still an important positive result for the implementation:

- the optimizer is not obviously broken
- the failure is more likely due to input quality, calibration, or model mismatch than to the grid search not maximizing the intended objective

In other words:

- the log-growth optimizer is saying that, if the replay inputs are good enough, the chosen counterfactual bet size should be better for long-run growth than the historical actual bet size
- the current comparison suggests that this internal optimization claim is mostly true
- but the broader realized ROI result suggests that the replay inputs, especially the recovered mech `p_yes` values and market-state approximation, are not yet reliable enough for that theoretical advantage to show up consistently in realized outcomes

## Practical implication

If the goal is production readiness, the current evidence supports:

- the optimizer mechanics are sound enough to keep iterating on
- but the current parameterization and/or modeling assumptions are not yet validated by the broader realized-ROI backtest

So the next step should be:

- improve calibration and robustness testing,
- not discard the optimizer as mechanically incorrect.
