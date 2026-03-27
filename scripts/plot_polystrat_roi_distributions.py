"""Generate ROI distribution plots for the Polystrat Kelly replay."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Plot actual vs counterfactual agent ROI distributions."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the replay JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where plots will be written.",
    )
    return parser.parse_args()


def _pct(values: list[float]) -> list[float]:
    """Convert decimal ROI values to percentages."""
    return [value * 100 for value in values]


def _summary(values: list[float]) -> dict[str, float]:
    """Build a compact numeric summary."""
    ordered = sorted(values)
    n = len(ordered)
    return {
        "count": n,
        "mean_pct": round(mean(ordered), 3),
        "median_pct": round(median(ordered), 3),
        "min_pct": round(ordered[0], 3),
        "max_pct": round(ordered[-1], 3),
        "p10_pct": round(ordered[max(0, math.floor((n - 1) * 0.10))], 3),
        "p90_pct": round(ordered[min(n - 1, math.floor((n - 1) * 0.90))], 3),
    }


def main() -> int:
    """Generate plots and a stats summary."""
    args = parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(input_path.read_text())
    summaries = [
        row
        for row in data.get("agent_summaries", [])
        if row.get("actual_roi") is not None and row.get("counterfactual_roi") is not None
    ]
    actual = _pct([float(row["actual_roi"]) for row in summaries])
    counterfactual = _pct([float(row["counterfactual_roi"]) for row in summaries])
    delta = [cf - act for act, cf in zip(actual, counterfactual)]

    stats = {
        "actual": _summary(actual),
        "counterfactual": _summary(counterfactual),
        "delta": _summary(delta),
    }
    (output_dir / "roi_distribution_summary.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bins = 24

    plt.figure(figsize=(10, 6))
    plt.hist(actual, bins=bins, alpha=0.55, label="Actual ROI", color="#2f6db2")
    plt.hist(
        counterfactual,
        bins=bins,
        alpha=0.55,
        label="Counterfactual ROI",
        color="#d57a1f",
    )
    plt.axvline(mean(actual), color="#2f6db2", linestyle="--", linewidth=1.5)
    plt.axvline(mean(counterfactual), color="#d57a1f", linestyle="--", linewidth=1.5)
    plt.title("Polystrat Agent ROI Distribution")
    plt.xlabel("ROI (%)")
    plt.ylabel("Agent count")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "roi_histogram_overlay.png", dpi=180)
    plt.close()

    plt.figure(figsize=(8, 6))
    plt.boxplot(
        [actual, counterfactual],
        labels=["Actual ROI", "Counterfactual ROI"],
        patch_artist=True,
        boxprops={"facecolor": "#dfe8f5"},
        medianprops={"color": "#1f1f1f"},
    )
    plt.axhline(0, color="#888888", linestyle="--", linewidth=1)
    plt.ylabel("ROI (%)")
    plt.title("Polystrat Agent ROI Boxplot")
    plt.tight_layout()
    plt.savefig(output_dir / "roi_boxplot.png", dpi=180)
    plt.close()

    plt.figure(figsize=(9, 6))
    plt.hist(delta, bins=bins, alpha=0.8, color="#2b9b5f")
    plt.axvline(mean(delta), color="#1f1f1f", linestyle="--", linewidth=1.5)
    plt.axvline(0, color="#888888", linestyle=":", linewidth=1.2)
    plt.title("Polystrat Agent ROI Delta Distribution")
    plt.xlabel("Counterfactual ROI - Actual ROI (percentage points)")
    plt.ylabel("Agent count")
    plt.tight_layout()
    plt.savefig(output_dir / "roi_delta_histogram.png", dpi=180)
    plt.close()

    plt.figure(figsize=(8, 8))
    min_axis = min(min(actual), min(counterfactual))
    max_axis = max(max(actual), max(counterfactual))
    plt.scatter(actual, counterfactual, alpha=0.75, color="#7b4ab8")
    plt.plot([min_axis, max_axis], [min_axis, max_axis], linestyle="--", color="#444444")
    plt.xlabel("Actual ROI (%)")
    plt.ylabel("Counterfactual ROI (%)")
    plt.title("Per-Agent ROI: Actual vs Counterfactual")
    plt.tight_layout()
    plt.savefig(output_dir / "roi_scatter.png", dpi=180)
    plt.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
