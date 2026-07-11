#!/usr/bin/env python3
"""Counterfactual replay: realized labels + scenario simulation from decision telemetry."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402

SCENARIOS = (
    "current",
    "ml_adopt_flat",
    "ml_adopt_flat_score50",
    "ml_only",
    "no_adx",
    "no_thesis_veto",
    "neutral_mild_trend",
)

ENTRY_SIGNALS = frozenset({"LONG", "SHORT", "BUY", "SELL", "STRONG_BUY", "STRONG_SELL"})


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _nested(row: Dict[str, Any], *keys: str) -> Any:
    cur: Any = row
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _ml_direction(row: Dict[str, Any]) -> Optional[str]:
    sigs = row.get("signals") if isinstance(row.get("signals"), dict) else {}
    ml = sigs.get("ml_gated")
    if ml in ("LONG", "SHORT"):
        return str(ml)
    reject = _nested(row, "extra", "reject") or row.get("reject")
    if reject == "gates_passed_long":
        return "LONG"
    if reject == "gates_passed_short":
        return "SHORT"
    gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
    if gates.get("g1_raw_long"):
        return "LONG"
    if gates.get("g1_raw_short"):
        return "SHORT"
    if _nested(row, "extra", "final_long"):
        return "LONG"
    if _nested(row, "extra", "final_short"):
        return "SHORT"
    return None


def _is_flat_thesis(row: Dict[str, Any]) -> bool:
    codes = row.get("policy_reason_codes") or []
    if not isinstance(codes, list):
        return False
    return any(
        c in codes
        for c in (
            "thesis_type=flat",
            "hypothesis_no_rule_fired",
            "thesis_no_rule_fired",
        )
    )


def _regime_bucket(row: Dict[str, Any]) -> str:
    codes = row.get("policy_reason_codes") or []
    if isinstance(codes, list):
        for c in codes:
            if str(c).startswith("regime="):
                return str(c).split("=", 1)[1].lower()
    for key in ("regime", "market_type"):
        v = row.get(key)
        if v:
            return str(v).lower()
    return "unknown"


def _ml_gate_passed(row: Dict[str, Any]) -> bool:
    return _ml_direction(row) is not None


# Reason codes are emitted as "key=value" (see agent_thesis_engine.py, e.g.
# f"adx_14={adx:.2f}"). Mirrors the parser in
# scripts/signal_recovery/decision_evidence.py._parse_code_features.
_CODE_VALUE_RE = re.compile(r"^([a-z0-9_]+)=(-?\d+(?:\.\d+)?)$", re.I)


def _core_features_from_row(row: Dict[str, Any]) -> Dict[str, float]:
    """Best-effort feature extraction: extra.features (Phase 6 telemetry
    hardening, see agent/core/signal_recovery_telemetry.py) first, reason-code
    key=value pairs as fallback for rows recorded before that hardening shipped.
    """
    out: Dict[str, float] = {}
    feats = _nested(row, "extra", "features")
    if isinstance(feats, dict):
        for k, v in feats.items():
            try:
                out[str(k).lower()] = float(v)
            except (TypeError, ValueError):
                continue
    codes = row.get("policy_reason_codes") or []
    if isinstance(codes, list):
        for c in codes:
            m = _CODE_VALUE_RE.match(str(c).strip())
            if not m:
                continue
            key = m.group(1).lower()
            if key in out:
                continue  # extra.features (if present) takes precedence
            try:
                out[key] = float(m.group(2))
            except ValueError:
                continue
    return out


def _neutral_mild_trend_fires(
    row: Dict[str, Any], regime: str, *, adx_max: float = 22.0
) -> bool:
    """Replay of agent_thesis_engine._eval_neutral_mild_trend_long (LONG only,
    prototype rule gated by AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED=false).
    Requires adx_14, h1_trend, h_trend to all be observed — rows without full
    core-feature coverage are excluded, not defaulted.
    """
    if regime != "neutral":
        return False
    feats = _core_features_from_row(row)
    if not all(k in feats for k in ("adx_14", "h1_trend", "h_trend")):
        return False
    return feats["adx_14"] <= adx_max and feats["h1_trend"] > 0 and feats["h_trend"] > 0


def _trade_score(row: Dict[str, Any]) -> float:
    v = row.get("trade_score")
    if v is None:
        v = _nested(row, "scores", "trade_score")
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def extract_candidates(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    handlers = [r for r in rows if r.get("event") == "handler_outcome"]
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("event") != "v43_prediction_complete":
            continue
        if not _ml_gate_passed(r):
            continue
        ts = _parse_ts(r.get("ts"))
        handler = None
        if ts:
            for h in handlers:
                h_ts = _parse_ts(h.get("ts"))
                if h_ts is None:
                    continue
                delta = (h_ts - ts).total_seconds()
                if 0 <= delta <= 30.0:
                    handler = h
                    break
        ml_dir = _ml_direction(r)
        regime = _regime_bucket(r)
        out.append(
            {
                "ts": r.get("ts"),
                "symbol": r.get("symbol") or "BTCUSD",
                "ml_direction": ml_dir,
                "policy_signal": str(r.get("signal") or "HOLD"),
                "trade_score": _trade_score(r),
                "thesis_signal": r.get("thesis_signal"),
                "flat_thesis": _is_flat_thesis(r),
                "regime": regime,
                "handler_reject": (
                    handler.get("handler_reject_reason") if handler else None
                ),
                "expected_return": r.get("expected_return") or r.get("proba"),
                "neutral_mild_trend_fires": _neutral_mild_trend_fires(r, regime),
                "raw_row": r,
            }
        )
    return out


def compute_directional_stability(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    directions = [c["ml_direction"] for c in candidates if c.get("ml_direction")]
    n = len(directions)
    if n < 2:
        return {"sample_count": n, "note": "insufficient data"}

    transitions: Counter = Counter()
    flips = 0
    runs: List[int] = []
    run_len = 1
    for i in range(1, n):
        prev, cur = directions[i - 1], directions[i]
        key = f"{prev}->{cur}"
        transitions[key] += 1
        if prev != cur:
            flips += 1
            runs.append(run_len)
            run_len = 1
        else:
            run_len += 1
    runs.append(run_len)

    flip_rate = flips / (n - 1)
    counts = Counter(directions)
    probs = [c / n for c in counts.values()]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)

    return {
        "sample_count": n,
        "flip_rate": round(flip_rate, 4),
        "mean_run_length": round(sum(runs) / len(runs), 2),
        "max_run_length": max(runs),
        "direction_counts": dict(counts),
        "transition_matrix": dict(transitions),
        "directional_entropy": round(entropy, 4),
    }


async def _fetch_candles(
    *,
    symbol: str,
    start_ts: int,
    end_ts: int,
    bar_minutes: int,
) -> List[Dict[str, Any]]:
    from agent.data.delta_client import DeltaExchangeClient

    client = DeltaExchangeClient()
    resp = await client.get_candles(
        symbol=symbol,
        resolution=f"{bar_minutes}m",
        start=start_ts,
        end=end_ts,
    )
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and isinstance(result.get("candles"), list):
        return result["candles"]
    return []


def _sl_tp_prices(
    *,
    side: str,
    entry_price: float,
    atr_14: Optional[float],
    sl_mult: float,
    tp_mult: float,
    stop_pct: float,
    take_pct: float,
    use_atr: bool,
) -> Tuple[float, float]:
    is_long = side.upper() in ("LONG", "BUY")
    if use_atr and atr_14 is not None and atr_14 > 0:
        sl_dist = max(entry_price * stop_pct, atr_14 * sl_mult)
        tp_dist = max(entry_price * take_pct, atr_14 * tp_mult)
    else:
        sl_dist = entry_price * stop_pct
        tp_dist = entry_price * take_pct
    if is_long:
        return entry_price - sl_dist, entry_price + tp_dist
    return entry_price + sl_dist, entry_price - tp_dist


def _net_pnl_pct(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> float:
    slip = slippage_bps / 10000.0
    fee_rt = taker_fee_rate * 2.0
    is_long = side.upper() in ("LONG", "BUY")
    if is_long:
        eff_entry = entry_price * (1.0 + slip)
        eff_exit = exit_price * (1.0 - slip)
        gross = (eff_exit - eff_entry) / eff_entry
    else:
        eff_entry = entry_price * (1.0 - slip)
        eff_exit = exit_price * (1.0 + slip)
        gross = (eff_entry - eff_exit) / eff_entry
    return (gross - fee_rt) * 100.0


async def label_candidate(
    cand: Dict[str, Any],
    *,
    horizon_bars: int,
    bar_minutes: int,
    economic: bool,
    cache: Dict[Tuple[str, int, int], List[Dict[str, Any]]],
    fetch_candles: Optional[Any] = None,
) -> Dict[str, Any]:
    from agent.core.config import settings
    from agent.persistence.trade_excursions import compute_excursions

    ts = _parse_ts(cand.get("ts"))
    ml_dir = cand.get("ml_direction")
    if ts is None or ml_dir not in ("LONG", "SHORT"):
        return {**cand, "label_error": "missing_ts_or_direction"}

    symbol = str(cand.get("symbol") or "BTCUSD")
    start_ts = int(ts.timestamp())
    end_ts = int((ts + timedelta(minutes=horizon_bars * bar_minutes)).timestamp())
    cache_key = (symbol, start_ts, end_ts)
    candles = cache.get(cache_key)
    if candles is None:
        try:
            if fetch_candles is not None:
                candles = await fetch_candles(symbol, start_ts, end_ts)
            else:
                candles = await _fetch_candles(
                    symbol=symbol,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    bar_minutes=bar_minutes,
                )
            cache[cache_key] = candles
        except Exception as exc:
            return {**cand, "label_error": str(exc)}

    if not candles:
        er = cand.get("expected_return")
        if er is not None:
            try:
                er_f = float(er)
                gross = er_f * 100.0 if ml_dir == "LONG" else -er_f * 100.0
                return {
                    **cand,
                    "entry_price": None,
                    "forward_return_pct": round(gross, 4),
                    "net_return_pct": round(gross, 4),
                    "would_have_won_net": gross > 0,
                    "label_source": "expected_return_fallback",
                }
            except (TypeError, ValueError):
                pass
        return {**cand, "label_error": "no_candles"}

    entry_price = float(candles[0].get("close") or candles[0].get("open") or 0)
    if entry_price <= 0:
        return {**cand, "label_error": "invalid_entry_price"}

    side = "buy" if ml_dir == "LONG" else "sell"
    sl = tp = None
    if economic:
        atr = None
        sl, tp = _sl_tp_prices(
            side=ml_dir,
            entry_price=entry_price,
            atr_14=atr,
            sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
            tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
            stop_pct=float(getattr(settings, "stop_loss_percentage", 0.01) or 0.01),
            take_pct=float(getattr(settings, "take_profit_percentage", 0.015) or 0.015),
            use_atr=bool(getattr(settings, "use_atr_scaled_sl_tp", False)),
        )

    exc = compute_excursions(
        side=side, entry_price=entry_price, candles=candles, sl=sl, tp=tp
    )
    last_close = float(candles[-1].get("close") or entry_price)
    is_long = ml_dir == "LONG"
    gross_pct = (
        (last_close - entry_price) / entry_price * 100.0
        if is_long
        else (entry_price - last_close) / entry_price * 100.0
    )

    if economic and sl is not None and tp is not None:
        if exc.get("sl_would_hit"):
            exit_price = sl
            outcome = "sl_hit"
        elif exc.get("tp_would_hit"):
            exit_price = tp
            outcome = "tp_hit"
        else:
            exit_price = last_close
            outcome = "time_exit"
        net_pct = _net_pnl_pct(
            side=ml_dir,
            entry_price=entry_price,
            exit_price=float(exit_price),
            taker_fee_rate=float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005),
            slippage_bps=float(getattr(settings, "slippage_bps", 5.0) or 5.0),
        )
    else:
        outcome = "time_exit"
        net_pct = gross_pct

    return {
        **cand,
        "entry_price": entry_price,
        "outcome": outcome,
        "gross_return_pct": round(gross_pct, 4),
        "net_return_pct": round(net_pct, 4),
        "would_have_won_net": net_pct > 0,
        "forward_mfe_pct": exc.get("mfe_pct"),
        "forward_mae_pct": exc.get("mae_pct"),
        "bars_held": exc.get("bars_held"),
        "label_source": "candles",
    }


async def label_all(
    candidates: List[Dict[str, Any]],
    *,
    horizon_bars: int,
    bar_minutes: int,
    economic: bool,
    concurrency: int,
) -> List[Dict[str, Any]]:
    from agent.data.delta_client import DeltaExchangeClient

    cache: Dict[Tuple[str, int, int], List[Dict[str, Any]]] = {}
    client = DeltaExchangeClient()
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_cached(
        symbol: str, start_ts: int, end_ts: int
    ) -> List[Dict[str, Any]]:
        key = (symbol, start_ts, end_ts)
        if key in cache:
            return cache[key]
        resp = await client.get_candles(
            symbol=symbol,
            resolution=f"{bar_minutes}m",
            start=start_ts,
            end=end_ts,
        )
        result = resp.get("result") if isinstance(resp, dict) else None
        candles: List[Dict[str, Any]] = []
        if isinstance(result, list):
            candles = result
        elif isinstance(result, dict) and isinstance(result.get("candles"), list):
            candles = result["candles"]
        cache[key] = candles
        return candles

    async def _one(c: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            return await label_candidate(
                c,
                horizon_bars=horizon_bars,
                bar_minutes=bar_minutes,
                economic=economic,
                cache=cache,
                fetch_candles=_fetch_cached,
            )

    return list(await asyncio.gather(*[_one(c) for c in candidates]))


def _scenario_included(name: str, c: Dict[str, Any]) -> bool:
    ml = c.get("ml_direction")
    policy = str(c.get("policy_signal") or "HOLD").upper()
    score = float(c.get("trade_score") or 0)
    flat = bool(c.get("flat_thesis"))
    handler = str(c.get("handler_reject") or "")

    if name == "current":
        if policy not in ENTRY_SIGNALS:
            return False
        if handler == "hold_at_synthesis":
            return False
        if handler == "v15_adx_trending_filter":
            return False
        return True

    if name == "ml_adopt_flat":
        return (
            ml in ("LONG", "SHORT")
            and flat
            and score >= 55.0
        )

    if name == "ml_adopt_flat_score50":
        return ml in ("LONG", "SHORT") and flat and score >= 50.0

    if name == "ml_only":
        return ml in ("LONG", "SHORT")

    if name == "no_adx":
        if policy in ENTRY_SIGNALS and handler != "hold_at_synthesis":
            return True
        if (
            ml in ("LONG", "SHORT")
            and flat
            and score >= 55.0
            and handler == "v15_adx_trending_filter"
        ):
            return True
        return False

    if name == "no_thesis_veto":
        return ml in ("LONG", "SHORT")

    if name == "neutral_mild_trend":
        # Prototype rule is LONG-only (agent_thesis_engine._eval_neutral_mild_trend_long).
        if not c.get("neutral_mild_trend_fires") or ml != "LONG":
            return False
        # Isolate the incremental candidate set the rule would newly enter —
        # exclude rows the current policy already entered, to avoid double
        # counting against the `current` scenario.
        if policy in ENTRY_SIGNALS and handler not in (
            "hold_at_synthesis",
            "v15_adx_trending_filter",
        ):
            return False
        return True

    return False


def _scenario_metrics(
    trades: List[Dict[str, Any]],
    *,
    size_fraction: float = 0.05,
) -> Dict[str, Any]:
    rets = [
        float(t["net_return_pct"])
        for t in trades
        if t.get("net_return_pct") is not None and not t.get("label_error")
    ]
    n = len(rets)
    if n == 0:
        return {
            "trades": 0,
            "win_pct": None,
            "profit_factor": None,
            "ev_pct": 0.0,
            "max_dd_pct": 0.0,
            "exposure": 0.0,
            "avg_hold_bars": None,
        }

    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    win_pct = len(wins) / n * 100.0
    gross_win = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else None
    ev = sum(rets) / n

    equity = 100.0
    peak = equity
    max_dd = 0.0
    for r in rets:
        equity += r * size_fraction
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    holds = [
        float(t["bars_held"])
        for t in trades
        if t.get("bars_held") is not None and not t.get("label_error")
    ]
    avg_hold = sum(holds) / len(holds) if holds else None

    return {
        "trades": n,
        "win_pct": round(win_pct, 2),
        "profit_factor": round(pf, 3) if pf is not None else None,
        "ev_pct": round(ev, 4),
        "max_dd_pct": round(max_dd, 4),
        "exposure": round(size_fraction * n, 4),
        "avg_hold_bars": round(avg_hold, 2) if avg_hold is not None else None,
    }


def simulate_scenarios(labeled: List[Dict[str, Any]]) -> Dict[str, Any]:
    table: Dict[str, Any] = {}
    for name in SCENARIOS:
        selected = [c for c in labeled if _scenario_included(name, c)]
        table[name] = _scenario_metrics(selected)
    return table


def threshold_sensitivity(
    labeled: List[Dict[str, Any]],
    thresholds: Sequence[float],
) -> List[Dict[str, Any]]:
    rows = []
    for thr in thresholds:
        subset = [
            c
            for c in labeled
            if c.get("ml_direction") in ("LONG", "SHORT")
            and c.get("flat_thesis")
            and float(c.get("trade_score") or 0) >= thr
            and not c.get("label_error")
        ]
        metrics = _scenario_metrics(subset)
        rows.append({"entry_quality_min": thr, **metrics})
    return rows


def by_regime_table(labeled: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_regime: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in labeled:
        by_regime[str(c.get("regime") or "unknown")].append(c)

    out: Dict[str, Any] = {}
    for regime, group in sorted(by_regime.items()):
        out[regime] = simulate_scenarios(group)
    return out


def evaluate_promotion_gates(
    scenario_table: Dict[str, Any],
    stability: Dict[str, Any],
    *,
    by_regime: Optional[Dict[str, Any]] = None,
    flip_rate_ceiling: float = 0.5,
) -> Dict[str, Any]:
    ml_flat = scenario_table.get("ml_adopt_flat") or {}
    trades = int(ml_flat.get("trades") or 0)
    ev = float(ml_flat.get("ev_pct") or 0.0)
    max_dd = float(ml_flat.get("max_dd_pct") or 0.0)
    flip_rate = float(stability.get("flip_rate") or 0.0)

    non_ranging_positive = False
    if by_regime:
        for regime, scenarios in by_regime.items():
            if regime in ("ranging", "neutral", "unknown"):
                continue
            reg_ev = float((scenarios.get("ml_adopt_flat") or {}).get("ev_pct") or 0.0)
            if reg_ev > 0:
                non_ranging_positive = True
                break

    gates = {
        "G1_sample_size": {
            "pass": trades >= 30,
            "value": trades,
            "threshold": 30,
        },
        "G2_net_ev": {
            "pass": ev > 0,
            "value": ev,
            "threshold": "> 0",
        },
        "G3_max_dd": {
            "pass": max_dd <= 5.0,
            "value": max_dd,
            "threshold": "<= 5.0%",
        },
        "G4_regime": {
            "pass": non_ranging_positive,
            "value": non_ranging_positive,
            "threshold": "positive EV in non-ranging bucket",
        },
        "G5_stability": {
            "pass": flip_rate <= flip_rate_ceiling,
            "value": flip_rate,
            "threshold": f"<= {flip_rate_ceiling}",
        },
    }
    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "all_pass": all_pass,
        "recommendation": (
            "proceed_3a2_testnet"
            if all_pass
            else "hold_baseline_policy"
        ),
        "note": "G6 (OOS shadow) evaluated separately",
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Counterfactual Replay Report",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Window hours: {report.get('window_hours')}",
        f"Candidates labeled: {report.get('labeled_count')}",
        "",
        "## Scenario table",
        "",
        "| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |",
        "|----------|--------|-------|-----|------|----------|----------|----------|",
    ]
    for name, m in report.get("scenario_table", {}).items():
        lines.append(
            f"| {name} | {m.get('trades')} | {m.get('win_pct')} | "
            f"{m.get('profit_factor')} | {m.get('ev_pct')} | {m.get('max_dd_pct')} | "
            f"{m.get('exposure')} | {m.get('avg_hold_bars')} |"
        )

    lines.extend(["", "## Directional stability", ""])
    stab = report.get("directional_stability") or {}
    for k, v in stab.items():
        if k != "transition_matrix":
            lines.append(f"- **{k}**: {v}")
    if stab.get("transition_matrix"):
        lines.append("")
        lines.append("| Transition | Count |")
        lines.append("|------------|------:|")
        for tr, cnt in sorted(stab["transition_matrix"].items()):
            lines.append(f"| {tr} | {cnt} |")

    lines.extend(["", "## Promotion gates", ""])
    promo = report.get("promotion_gates") or {}
    lines.append(f"**Recommendation:** {promo.get('recommendation')}")
    for gname, g in (promo.get("gates") or {}).items():
        status = "PASS" if g.get("pass") else "FAIL"
        lines.append(f"- {gname}: {status} (value={g.get('value')}, threshold={g.get('threshold')})")

    if report.get("threshold_sensitivity"):
        lines.extend(["", "## Threshold sensitivity", ""])
        lines.append("| Min score | Trades | Win % | EV % |")
        lines.append("|-----------|--------|-------|------|")
        for row in report["threshold_sensitivity"]:
            lines.append(
                f"| {row.get('entry_quality_min')} | {row.get('trades')} | "
                f"{row.get('win_pct')} | {row.get('ev_pct')} |"
            )

    return "\n".join(lines)


async def run_replay(
    *,
    telemetry_path: Path,
    hours: float,
    horizon_bars: int,
    bar_minutes: int,
    economic: bool,
    concurrency: int,
) -> Dict[str, Any]:
    rows = filter_since(load_telemetry(telemetry_path), hours)
    candidates = extract_candidates(rows)
    labeled = await label_all(
        candidates,
        horizon_bars=horizon_bars,
        bar_minutes=bar_minutes,
        economic=economic,
        concurrency=concurrency,
    )
    stability = compute_directional_stability(candidates)
    scenario_table = simulate_scenarios(labeled)
    regime_table = by_regime_table(labeled)
    threshold_rows = threshold_sensitivity(labeled, [45, 50, 55, 60])
    promotion = evaluate_promotion_gates(scenario_table, stability, by_regime=regime_table)

    label_errors = sum(1 for c in labeled if c.get("label_error"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "telemetry_path": str(telemetry_path),
        "candidate_count": len(candidates),
        "labeled_count": len(labeled) - label_errors,
        "label_errors": label_errors,
        "horizon_bars": horizon_bars,
        "economic": economic,
        "directional_stability": stability,
        "scenario_table": scenario_table,
        "by_regime": regime_table,
        "threshold_sensitivity": threshold_rows,
        "promotion_gates": promotion,
        "candidates": labeled,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--horizon-bars", type=int, default=2)
    parser.add_argument("--bar-minutes", type=int, default=5)
    parser.add_argument("--economic", action="store_true")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "data" / "investigation" / "counterfactual_replay_2026-07-11.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=ROOT / "data" / "investigation" / "counterfactual_replay_2026-07-11.md",
    )
    parser.add_argument(
        "--stability-out",
        type=Path,
        default=ROOT / "data" / "investigation" / "directional_stability_2026-07-11.json",
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_replay(
            telemetry_path=args.telemetry,
            hours=args.hours,
            horizon_bars=args.horizon_bars,
            bar_minutes=args.bar_minutes,
            economic=args.economic,
            concurrency=args.concurrency,
        )
    )

    stability_only = report.pop("candidates", [])
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    full_report = {**report, "candidates": stability_only}
    args.out_json.write_text(json.dumps(full_report, indent=2, default=str), encoding="utf-8")
    args.out_md.write_text(_render_markdown(report), encoding="utf-8")
    args.stability_out.write_text(
        json.dumps(report.get("directional_stability") or {}, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report["scenario_table"], indent=2))
    print(json.dumps(report["promotion_gates"], indent=2))
    print(f"Wrote {args.out_json}")
    print(f"Wrote {args.out_md}")
    print(f"Wrote {args.stability_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
