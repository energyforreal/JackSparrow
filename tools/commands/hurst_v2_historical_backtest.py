#!/usr/bin/env python3
"""Historical hurst_60 vs hurst_60_v2 thesis fire-rate / EV backtest.

Replays 5m candles through production feature + thesis code (zero drift):

- ``feature_store.jacksparrow_v43_build_matrix.build_v43_feature_matrix``
  (``for_training=False`` dual-writes ``hurst_60_v2``)
- ``AgentThesisEngine.evaluate`` with ``settings.agent_thesis_use_hurst_v2`` toggled

This is a **directional read only** (no slippage/funding/execution). It does **not**
clear the production promotion gate by itself.

Examples::

    python tools/commands/hurst_v2_historical_backtest.py --fetch --days 60 \\
      --symbol BTCUSD --out data/investigation/hurst_v2_backtest_60d

    python tools/commands/hurst_v2_historical_backtest.py --candles path.json \\
      --out data/investigation/hurst_v2_backtest_60d

Candle JSON shapes accepted:
- list of OHLC dicts (``time``/``timestamp``/``t``, open, high, low, close, volume)
- ``{\"candles\": [...]}`` or ``{\"result\": [...]}`` (Delta-style)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core import config as cfg  # noqa: E402
from agent.core.agent_thesis_engine import AgentThesisEngine  # noqa: E402
from feature_store.jacksparrow_v43_build_matrix import (  # noqa: E402
    build_v43_feature_matrix,
)

DEFAULT_WARMUP = 400
DEFAULT_HORIZON = 12  # 12 * 5m = 1h forward return


def _ts_to_utc(val: Any) -> pd.Timestamp:
    if val is None:
        return pd.NaT
    if isinstance(val, (int, float)):
        # seconds vs ms
        v = float(val)
        if v > 1e12:
            v /= 1000.0
        return pd.to_datetime(v, unit="s", utc=True)
    return pd.to_datetime(val, utc=True, errors="coerce")


def candles_to_dataframe(candles: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """Normalize candle dicts to a 5m OHLC DataFrame with ``timestamp``."""
    rows: List[Dict[str, Any]] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        ts = c.get("timestamp", c.get("time", c.get("t", c.get("start"))))
        o = c.get("open", c.get("o"))
        h = c.get("high", c.get("h"))
        low = c.get("low", c.get("l"))
        cl = c.get("close", c.get("c"))
        vol = c.get("volume", c.get("v", 0.0))
        if o is None or h is None or low is None or cl is None:
            continue
        rows.append(
            {
                "timestamp": _ts_to_utc(ts),
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(cl),
                "volume": float(vol or 0.0),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).dropna(subset=["timestamp"]).sort_values("timestamp")
    return df.reset_index(drop=True)


def load_candles_json(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("candles", "result", "data"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict) and isinstance(val.get("candles"), list):
                return val["candles"]
    raise ValueError(f"Unrecognized candle JSON shape in {path}")


async def fetch_candles(*, symbol: str, days: int, bar_minutes: int = 5) -> List[Dict[str, Any]]:
    """Fetch candles in chunks (Delta caps ~4000 bars per request)."""
    from agent.data.delta_client import DeltaExchangeClient

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 3)  # warmup buffer
    # Stay under API cap: ~3500 five-minute bars ≈ 12 days
    chunk_days = max(1, min(12, days))
    client = DeltaExchangeClient()
    all_rows: List[Dict[str, Any]] = []
    seen: set[Any] = set()
    cursor_end = end
    try:
        while cursor_end > start:
            cursor_start = max(start, cursor_end - timedelta(days=chunk_days))
            resp = await client.get_candles(
                symbol=symbol,
                resolution=f"{bar_minutes}m",
                start=int(cursor_start.timestamp()),
                end=int(cursor_end.timestamp()),
            )
            result = resp.get("result") if isinstance(resp, dict) else None
            batch: List[Dict[str, Any]] = []
            if isinstance(result, list):
                batch = result
            elif isinstance(result, dict) and isinstance(result.get("candles"), list):
                batch = result["candles"]
            if not batch:
                break
            for row in batch:
                if not isinstance(row, dict):
                    continue
                key = row.get("time", row.get("timestamp", row.get("t")))
                if key in seen:
                    continue
                seen.add(key)
                all_rows.append(row)
            # Walk backward
            oldest = None
            for row in batch:
                ts = _ts_to_utc(row.get("time", row.get("timestamp", row.get("t"))))
                if pd.isna(ts):
                    continue
                if oldest is None or ts < oldest:
                    oldest = ts
            if oldest is None:
                break
            cursor_end = oldest.to_pydatetime() - timedelta(seconds=bar_minutes * 60)
            if len(batch) < 10:
                break
            await asyncio.sleep(0.05)
    finally:
        await client.close()

    def _sort_key(r: Dict[str, Any]) -> float:
        ts = _ts_to_utc(r.get("time", r.get("timestamp", r.get("t"))))
        if pd.isna(ts):
            return 0.0
        return float(ts.timestamp())

    all_rows.sort(key=_sort_key)
    return all_rows


def _row_features(row: pd.Series) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k in ("timestamp",):
            continue
        if pd.isna(v):
            continue
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            out[str(k)] = v
    return out


def _signal_side(signal: str) -> Optional[str]:
    s = str(signal or "HOLD").upper()
    if s in ("LONG", "BUY"):
        return "long"
    if s in ("SHORT", "SELL"):
        return "short"
    return None


def _forward_return_pct(closes: np.ndarray, i: int, horizon: int, side: str) -> Optional[float]:
    j = i + horizon
    if j >= len(closes):
        return None
    entry = float(closes[i])
    exit_px = float(closes[j])
    if entry <= 0:
        return None
    if side == "long":
        return (exit_px / entry - 1.0) * 100.0
    return (entry / exit_px - 1.0) * 100.0


def _summarize_arm(
    *,
    n_eval: int,
    fires: List[Dict[str, Any]],
) -> Dict[str, Any]:
    n_long = sum(1 for f in fires if f["side"] == "long")
    n_short = sum(1 for f in fires if f["side"] == "short")
    long_rets = [f["fwd_ret_pct"] for f in fires if f["side"] == "long" and f["fwd_ret_pct"] is not None]
    short_rets = [f["fwd_ret_pct"] for f in fires if f["side"] == "short" and f["fwd_ret_pct"] is not None]
    all_rets = long_rets + short_rets
    regimes = Counter(str(f.get("regime") or "unknown") for f in fires)

    def _ev(xs: List[float]) -> Optional[float]:
        if not xs:
            return None
        return round(float(np.mean(xs)), 4)

    return {
        "n_eval": n_eval,
        "n_fires": len(fires),
        "n_long": n_long,
        "n_short": n_short,
        "fire_rate_pct": round(100.0 * len(fires) / max(n_eval, 1), 3),
        "ev_long_pct": _ev(long_rets),
        "ev_short_pct": _ev(short_rets),
        "ev_combined_pct": _ev(all_rets),
        "n_long_labeled": len(long_rets),
        "n_short_labeled": len(short_rets),
        "regime_fire_counts": dict(regimes),
    }


def run_backtest(
    df_5m: pd.DataFrame,
    *,
    warmup: int = DEFAULT_WARMUP,
    horizon_bars: int = DEFAULT_HORIZON,
    window: Optional[int] = None,
    step: int = 1,
) -> Dict[str, Any]:
    """Compare legacy vs hurst_v2 thesis fires on historical 5m bars.

    Uses vectorized ``build_v43_feature_matrix`` (same Hurst formulas as
    ``build_v43_last_row``). When ``window`` is set, features are rebuilt on each
    sliding chunk of that length (bounded lookback); otherwise the full series
    is used once (O(n), live-parity with expanding history).
    """
    if df_5m is None or len(df_5m) < warmup + horizon_bars + 10:
        raise ValueError(
            f"Need at least {warmup + horizon_bars + 10} candles; got {0 if df_5m is None else len(df_5m)}"
        )

    settings = cfg.settings
    eng = AgentThesisEngine()
    orig_flag = bool(getattr(settings, "agent_thesis_use_hurst_v2", False))

    if window and window > 0:
        # Sliding-window rebuild for O(n) bounded lookback (plan default path).
        feat_frames: List[pd.DataFrame] = []
        indices: List[int] = []
        for i in range(max(warmup, window - 1), len(df_5m) - horizon_bars, step):
            chunk = df_5m.iloc[i - window + 1 : i + 1]
            mat = build_v43_feature_matrix(chunk, for_training=False)
            if mat.empty:
                continue
            feat_frames.append(mat.iloc[[-1]].reset_index(drop=True))
            indices.append(i)
        if not feat_frames:
            raise ValueError("No feature rows produced from sliding windows")
        feat_df = pd.concat(feat_frames, ignore_index=True)
        eval_indices = indices
    else:
        feat_df = build_v43_feature_matrix(df_5m, for_training=False)
        if feat_df.empty:
            raise ValueError("build_v43_feature_matrix returned empty")
        eval_indices = list(range(warmup, len(df_5m) - horizon_bars, step))
        # Align feature rows to df_5m index positions
        if len(feat_df) != len(df_5m):
            raise ValueError(
                f"Feature matrix length {len(feat_df)} != candle length {len(df_5m)}"
            )

    closes = df_5m["close"].astype(float).to_numpy()

    arms: Dict[str, List[Dict[str, Any]]] = {"legacy": [], "hurst_v2": []}
    n_eval = 0
    hurst_stats: Dict[str, List[float]] = {"hurst_60": [], "hurst_60_v2": []}

    try:
        for arm_name, use_v2 in (("legacy", False), ("hurst_v2", True)):
            settings.agent_thesis_use_hurst_v2 = use_v2
            fires: List[Dict[str, Any]] = []
            local_n = 0
            for pos, i in enumerate(eval_indices):
                if window and window > 0:
                    feat_row = feat_df.iloc[pos]
                else:
                    feat_row = feat_df.iloc[i]
                feats = _row_features(feat_row)
                if use_v2 is False and arm_name == "legacy":
                    # Collect hurst dist once on legacy pass
                    if feats.get("hurst_60") is not None:
                        hurst_stats["hurst_60"].append(float(feats["hurst_60"]))
                    if feats.get("hurst_60_v2") is not None:
                        hurst_stats["hurst_60_v2"].append(float(feats["hurst_60_v2"]))

                regime = str(feats.get("regime_label") or feats.get("regime") or "neutral")
                mc = {
                    "features": feats,
                    "regime": regime,
                    "v43_regime": regime,
                    "has_open_position": False,
                }
                verdict = eng.evaluate(regime, mc)
                local_n += 1
                side = _signal_side(verdict.signal)
                if side is None:
                    continue
                fwd = _forward_return_pct(closes, i, horizon_bars, side)
                fires.append(
                    {
                        "side": side,
                        "signal": verdict.signal,
                        "thesis_type": getattr(verdict, "thesis_type", None),
                        "regime": regime,
                        "fwd_ret_pct": fwd,
                        "bar_index": i,
                    }
                )
            arms[arm_name] = fires
            if arm_name == "legacy":
                n_eval = local_n
    finally:
        settings.agent_thesis_use_hurst_v2 = orig_flag

    def _dist(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"n": 0}
        arr = np.asarray(vals, dtype=float)
        return {
            "n": int(arr.size),
            "mean": round(float(arr.mean()), 6),
            "median": round(float(np.median(arr)), 6),
            "min": round(float(arr.min()), 6),
            "max": round(float(arr.max()), 6),
            "ge_0_52": int((arr >= 0.52).sum()),
            "eq_0": int((arr == 0.0).sum()),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_candles": len(df_5m),
        "warmup": warmup,
        "horizon_bars": horizon_bars,
        "window": window,
        "step": step,
        "n_eval": n_eval,
        "hurst_distribution": {
            "hurst_60": _dist(hurst_stats["hurst_60"]),
            "hurst_60_v2": _dist(hurst_stats["hurst_60_v2"]),
        },
        "legacy": _summarize_arm(n_eval=n_eval, fires=arms["legacy"]),
        "hurst_v2": _summarize_arm(n_eval=n_eval, fires=arms["hurst_v2"]),
        "production_flags_unchanged": True,
        "disclaimer": (
            "Directional read only — no slippage/funding/walk-forward. "
            "Does not clear promotion gate alone."
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    legs = ("legacy", "hurst_v2")
    lines = [
        "# Hurst v2 Historical Backtest",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Candles: {report.get('n_candles')} | eval bars: {report.get('n_eval')} | "
        f"horizon: {report.get('horizon_bars')} bars | window: {report.get('window')}",
        "",
        report.get("disclaimer", ""),
        "",
        "## Hurst distribution (eval bars)",
        "",
    ]
    hd = report.get("hurst_distribution") or {}
    for key in ("hurst_60", "hurst_60_v2"):
        d = hd.get(key) or {}
        lines.append(
            f"- `{key}`: n={d.get('n')} mean={d.get('mean')} median={d.get('median')} "
            f"≥0.52={d.get('ge_0_52')} eq0={d.get('eq_0')}"
        )
    lines.extend(["", "## Arm comparison", "", "| Arm | n_fires | n_long | n_short | fire% | EV long% | EV short% | EV combined% |",
                  "|-----|--------:|-------:|--------:|------:|---------:|----------:|-------------:|"])
    for arm in legs:
        r = report.get(arm) or {}
        lines.append(
            f"| {arm} | {r.get('n_fires')} | {r.get('n_long')} | {r.get('n_short')} | "
            f"{r.get('fire_rate_pct')} | {r.get('ev_long_pct')} | {r.get('ev_short_pct')} | "
            f"{r.get('ev_combined_pct')} |"
        )
    lines.extend(["", "## Regime fire counts (hurst_v2)", ""])
    for k, v in sorted(((report.get("hurst_v2") or {}).get("regime_fire_counts") or {}).items()):
        lines.append(f"- `{k}`: {v}")
    lines.extend(
        [
            "",
            "## Production posture",
            "",
            "- Do **not** enable `AGENT_THESIS_USE_HURST_V2` on live capital from this report alone.",
            "- Requires 7d+30d replay + shadow + approval vs baseline `0503847`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Fetch candles from Delta")
    parser.add_argument("--candles", type=Path, default=None, help="Pre-exported candle JSON")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--symbol", type=str, default="BTCUSD")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--horizon-bars", type=int, default=DEFAULT_HORIZON)
    parser.add_argument(
        "--window",
        type=int,
        default=0,
        help="Sliding lookback bars (0=full-series matrix once, recommended; 600=plan sliding window)",
    )
    parser.add_argument("--step", type=int, default=1, help="Evaluate every Nth bar")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "hurst_v2_backtest_60d",
    )
    args = parser.parse_args()

    if args.fetch:
        print(f"Fetching {args.days}d {args.symbol} 5m candles...", flush=True)
        candles = asyncio.run(fetch_candles(symbol=args.symbol, days=args.days))
        if not candles:
            print("Delta fetch returned no candles; use --candles", file=sys.stderr)
            return 1
    elif args.candles and args.candles.is_file():
        candles = load_candles_json(args.candles)
    else:
        print("Pass --fetch or --candles path.json", file=sys.stderr)
        return 1

    df = candles_to_dataframe(candles)
    print(f"Loaded {len(df)} candles", flush=True)
    window = None if args.window <= 0 else args.window

    t0 = time.time()
    # Full-series matrix is much faster for 60d; sliding window is O(n*window).
    # Default window=600 per plan; use step>1 if runtime is too high.
    report = run_backtest(
        df,
        warmup=args.warmup,
        horizon_bars=args.horizon_bars,
        window=window,
        step=max(1, args.step),
    )
    report["symbol"] = args.symbol
    report["days_requested"] = args.days
    report["elapsed_sec"] = round(time.time() - t0, 2)
    report["source"] = "delta_fetch" if args.fetch else str(args.candles)

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = out.with_suffix(".json") if out.suffix == "" else Path(str(out) + ".json")
    md_path = out.with_suffix(".md") if out.suffix == "" else Path(str(out) + ".md")
    # When --out is stem without suffix, with_suffix works; when path has no suffix Path treats last part as name
    if out.suffix:
        json_path = out.with_suffix(".json")
        md_path = out.with_suffix(".md")
    else:
        json_path = Path(str(out) + ".json")
        md_path = Path(str(out) + ".md")

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "hurst_v2": report.get("hurst_v2"), "legacy": report.get("legacy")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
