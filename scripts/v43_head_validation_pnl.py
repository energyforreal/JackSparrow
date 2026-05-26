#!/usr/bin/env python3
"""Per-head validation P&L summary from exported metadata (scalp vs primary head).

Uses ``long_candidates`` / ``short_candidates`` net stats from ``metadata_v43.json``.
For full cumulative curves, re-run the Colab notebook validation cell with
``multi_bundle.get_head(2)`` or pass ``--feature-csv`` (future: replay predictions).

Usage:
  python scripts/v43_head_validation_pnl.py
  python scripts/v43_head_validation_pnl.py --head scalp_10m --plot-out reports/scalp_pnl.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEYS, V43_HORIZON_KEY_TO_BARS


def _default_metadata_path() -> Path:
    return (
        _REPO
        / "agent"
        / "model_storage"
        / "JackSparrow_v43_models_BTCUSD"
        / "metadata_v43.json"
    )


def _head_summary(block: Dict[str, Any]) -> Dict[str, Any]:
    vm = block.get("validation_metrics") or {}
    long_c = vm.get("long_candidates") or {}
    short_c = vm.get("short_candidates") or {}
    rtc = float(vm.get("round_trip_cost_pct") or 0.0016)
    n_val = int((block.get("split") or {}).get("rows_validation") or 0)
    long_n = int(long_c.get("count") or 0)
    short_n = int(short_c.get("count") or 0)
    long_net = float(long_c.get("net_mean_return") or 0.0)
    short_net = float(short_c.get("net_mean_return") or 0.0)
    # Approximate combined active-bar return (long + short sleeves, non-overlapping proxy)
    active = long_n + short_n
    if active > 0:
        blended_net = (long_n * long_net + short_n * short_net) / active
    else:
        blended_net = 0.0
    approx_total_return = blended_net * active
    return {
        "forward_bars": int(block.get("forward_bars") or 0),
        "validation_corr": vm.get("validation_corr"),
        "dynamic_threshold": vm.get("dynamic_threshold"),
        "threshold_percentile": vm.get("threshold_percentile"),
        "long_coverage": long_c.get("coverage"),
        "long_net_mean": long_net,
        "long_hit_net": long_c.get("hit_rate_net_positive"),
        "short_net_mean": short_net,
        "short_hit_net": short_c.get("hit_rate_net_positive"),
        "max_drawdown_proxy": min(
            float(long_c.get("max_drawdown_proxy") or 0.0),
            float(short_c.get("max_drawdown_proxy") or 0.0),
        ),
        "blended_net_per_trade": blended_net,
        "approx_cumulative_return": approx_total_return,
        "round_trip_cost_pct": rtc,
        "rows_validation": n_val,
    }


def _resolve_head_key(head_arg: str) -> str:
    h = head_arg.strip().lower()
    if h in V43_HORIZON_KEYS:
        return h
    try:
        fb = int(h)
        for key, bars in V43_HORIZON_KEY_TO_BARS.items():
            if bars == fb:
                return key
    except ValueError:
        pass
    raise ValueError(f"unknown head {head_arg!r}; use {list(V43_HORIZON_KEYS)} or 2/6/12/24")


def _print_report(meta: Dict[str, Any], focus_key: str | None) -> List[Tuple[str, Dict[str, Any]]]:
    primary_fb = int(meta.get("primary_execution_horizon_bars") or 6)
    horizons = meta.get("horizons") or {}
    rows: List[Tuple[str, Dict[str, Any]]] = []
    print(f"target_definition={meta.get('target_definition')}")
    print(f"primary_execution_horizon_bars={primary_fb} (runtime primary)")
    print()
    print(
        f"{'head':<16} {'IC':>8} {'long_net':>10} {'short_net':>10} "
        f"{'blend_net':>10} {'~cum_ret':>10} {'maxDD':>10}"
    )
    print("-" * 78)
    for key in V43_HORIZON_KEYS:
        block = horizons.get(key)
        if not isinstance(block, dict):
            continue
        s = _head_summary(block)
        rows.append((key, s))
        ic = s["validation_corr"]
        ic_s = f"{float(ic):.4f}" if ic is not None else "n/a"
        marker = " *" if key == focus_key else ""
        primary_mark = " [PRIMARY]" if s["forward_bars"] == primary_fb else ""
        print(
            f"{key:<16} {ic_s:>8} {s['long_net_mean']:>10.6f} {s['short_net_mean']:>10.6f} "
            f"{s['blended_net_per_trade']:>10.6f} {s['approx_cumulative_return']:>10.4f} "
            f"{s['max_drawdown_proxy']:>10.4f}{primary_mark}{marker}"
        )
    print()
    scalp = next((s for k, s in rows if k == "scalp_10m"), None)
    intra = next((s for k, s in rows if k == "intraday_30m"), None)
    if scalp and intra:
        print("scalp_10m vs intraday_30m (validation candidate economics at export thresholds):")
        print(
            f"  scalp blend_net/trade={scalp['blended_net_per_trade']:.6f}  "
            f"30m={intra['blended_net_per_trade']:.6f}"
        )
        print(
            f"  scalp ~cum_ret={scalp['approx_cumulative_return']:.4f}  "
            f"30m={intra['approx_cumulative_return']:.4f}"
        )
        if scalp["blended_net_per_trade"] > intra["blended_net_per_trade"]:
            print("  => scalp_10m is less negative per trade at current export thresholds.")
        else:
            print("  => intraday_30m is less negative per trade at current export thresholds.")
    return rows


def _maybe_plot(rows: List[Tuple[str, Dict[str, Any]]], out_path: Path, focus_key: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"(matplotlib not installed — skip plot {out_path})", file=sys.stderr)
        return
    labels = [k for k, _ in rows]
    vals = [s["blended_net_per_trade"] * 10000 for _, s in rows]  # bps
    colors = ["#2ca02c" if k == focus_key else "#1f77b4" for k in labels]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, vals, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("blended net mean return (bps per active trade)")
    ax.set_title("v43 validation — net return per trade by head (metadata)")
    plt.xticks(rotation=15, ha="right")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"Wrote plot: {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="v43 per-head validation P&L from metadata")
    parser.add_argument("--metadata", type=Path, default=_default_metadata_path())
    parser.add_argument(
        "--head",
        default="scalp_10m",
        help="Focus head key or forward_bars (default scalp_10m / 2)",
    )
    parser.add_argument(
        "--plot-out",
        type=Path,
        default=None,
        help="Optional PNG path for blended net return by head",
    )
    args = parser.parse_args()
    with args.metadata.open(encoding="utf-8") as f:
        meta = json.load(f)
    focus_key = _resolve_head_key(args.head)
    rows = _print_report(meta, focus_key)
    if args.plot_out:
        _maybe_plot(rows, args.plot_out, focus_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
