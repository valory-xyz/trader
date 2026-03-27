# Production Readiness Note

The change is not yet ready for production from my point of view.

Two things are still missing:

1. Proper backtesting and QA. We need to validate, for a fixed set of parameters, whether the new pricing improves the log-growth optimization objective, and then whether that improvement actually translates into better ROI relative to capital spent.
2. Backward-compatibility and rollback analysis. As Jenslee pointed out, this looks like a structural change, and it may not be reversible by changing the hash alone. That makes the rollout riskier without the validation above.

What we will produce today:

- a short backtesting note on whether the new pricing improves the log-growth objective
- a short QA note on whether it improves ROI versus capital spent
- a short rollback note on whether the change can be safely reversed

Progress so far is good on implementation, but production evidence is still incomplete. The main gap is not code delivery, but proof that the change is better and safe to roll back if needed.
