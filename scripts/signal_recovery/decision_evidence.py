"""Shared decision evidence enrichment with per-feature provenance."""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from scripts.signal_recovery.log_parser import filter_since, load_telemetry

ConfidenceLevel = Literal["high", "medium", "excluded"]
SourceLevel = Literal["log_market_context", "telemetry_embedded", "default_missing"]

CORE_THESIS_FEATURES: Tuple[str, ...] = (
    "adx_14",
    "di_spread",
    "vol_regime",
    "hurst_60",
    "h_trend",
    "h1_trend",
    "rsi_14",
    "bb_pos",
)

SWEEP_GATE_MIN_HIGH_CONFIDENCE = 100

_CODE_VALUE_RE = re.compile(r"^([a-z0-9_]+)=(-?\d+(?:\.\d+)?)$", re.I)


def iter_json_objects(text: str) -> Iterator[Dict[str, Any]]:
    """Yield JSON objects from agent log text (handles wrapped structlog lines)."""
    dec = json.JSONDecoder()
    flat = re.sub(r"\s+", "", text)
    pos = 0
    length = len(flat)
    while pos < length:
        if flat[pos] != "{":
            pos += 1
            continue
        try:
            obj, end = dec.raw_decode(flat, pos)
            if isinstance(obj, dict):
                yield obj
            pos = end
        except json.JSONDecodeError:
            pos += 1


def parse_ts_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def nearest_before(
    ts_index: List[float],
    rows: List[Dict[str, Any]],
    target_ts: float,
    *,
    max_delta_sec: float = 15.0,
) -> Optional[Dict[str, Any]]:
    if not ts_index:
        return None
    pos = bisect_right(ts_index, target_ts) - 1
    if pos < 0:
        return None
    if target_ts - ts_index[pos] > max_delta_sec:
        return None
    return rows[pos]


def reason_codes_from_context(ctx: Dict[str, Any]) -> List[str]:
    codes: List[str] = []
    pv = ctx.get("policy_verdict")
    if isinstance(pv, dict):
        for c in pv.get("reason_codes") or []:
            codes.append(str(c))
    hyp = ctx.get("hypothesis_snapshot")
    if isinstance(hyp, dict):
        for c in hyp.get("reason_codes") or []:
            codes.append(str(c))
    mc = ctx.get("market_context")
    if isinstance(mc, dict):
        hyp2 = mc.get("hypothesis_snapshot")
        if isinstance(hyp2, dict):
            for c in hyp2.get("reason_codes") or []:
                codes.append(str(c))
        pv2 = mc.get("policy_verdict")
        if isinstance(pv2, dict):
            for c in pv2.get("reason_codes") or []:
                codes.append(str(c))
    dc = ctx.get("decision_context")
    if isinstance(dc, dict):
        for c in reason_codes_from_context(dc):
            codes.append(c)
    return codes


def hypothesis_snapshot(obj: Dict[str, Any]) -> Dict[str, Any]:
    mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
    hyp = mc.get("hypothesis_snapshot") if isinstance(mc.get("hypothesis_snapshot"), dict) else {}
    if hyp:
        return hyp
    dc = obj.get("decision_context") if isinstance(obj.get("decision_context"), dict) else {}
    hyp2 = dc.get("hypothesis_snapshot") if isinstance(dc.get("hypothesis_snapshot"), dict) else {}
    return hyp2 or {}


def classify_hold_bucket(
    *,
    codes: List[str],
    hyp: Dict[str, Any],
    v43: Optional[Dict[str, Any]],
    cognition: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> str:
    """Assign one primary bucket per hold_at_synthesis event."""
    code_set = set(codes)
    reject_tag = str((v43 or {}).get("reject") or "")
    v43_gates_passed = reject_tag in ("gates_passed_short", "gates_passed_long")
    policy_hold = str((v43 or {}).get("policy_signal") or "HOLD").upper() == "HOLD"

    if "hypothesis_margin_below_min" in code_set:
        return "B3"

    if v43_gates_passed and policy_hold and (
        "hypothesis_no_rule_fired" in code_set or "thesis_no_rule_fired" in code_set
    ):
        return "B4"

    hypotheses = hyp.get("hypotheses") if isinstance(hyp.get("hypotheses"), list) else []
    eligible = list((cognition or {}).get("eligible_profiles") or [])
    long_p = float(hyp.get("long_pressure") or 0.0)
    short_p = float(hyp.get("short_pressure") or 0.0)
    total_pressure = long_p + short_p

    if not hypotheses or (cognition is not None and not eligible):
        return "B1"

    if hypotheses and total_pressure <= 1e-9:
        return "B2"

    rb = str((shadow or {}).get("rule_based_signal") or "HOLD").upper()
    live = str((shadow or {}).get("live_signal") or "HOLD").upper()
    if rb == "HOLD" and live == "HOLD":
        return "A"

    if "hypothesis_no_rule_fired" in code_set:
        return "B2"
    return "unknown"


@dataclass
class FeatureObservation:
    feature: str
    value: Optional[float]
    source: SourceLevel
    confidence: ConfidenceLevel
    observed: bool


@dataclass
class EnrichedDecisionRecord:
    event_id: Optional[str]
    ts: str
    symbol: str
    bucket: str
    regime: str
    eligible_profiles: List[str]
    policy_reason_codes: List[str]
    reject: Optional[str]
    trade_score: Optional[float]
    features: Dict[str, FeatureObservation]
    hypothesis_snapshot: Dict[str, Any]
    shadow: Optional[Dict[str, Any]]
    provenance_summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["features"] = {k: asdict(v) for k, v in self.features.items()}
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> EnrichedDecisionRecord:
        feats = {}
        for k, v in (raw.get("features") or {}).items():
            if isinstance(v, dict):
                feats[k] = FeatureObservation(**v)
        return cls(
            event_id=raw.get("event_id"),
            ts=str(raw.get("ts") or ""),
            symbol=str(raw.get("symbol") or ""),
            bucket=str(raw.get("bucket") or "unknown"),
            regime=str(raw.get("regime") or "unknown"),
            eligible_profiles=list(raw.get("eligible_profiles") or []),
            policy_reason_codes=list(raw.get("policy_reason_codes") or []),
            reject=raw.get("reject"),
            trade_score=raw.get("trade_score"),
            features=feats,
            hypothesis_snapshot=dict(raw.get("hypothesis_snapshot") or {}),
            shadow=raw.get("shadow"),
            provenance_summary=dict(raw.get("provenance_summary") or {}),
        )


def _parse_code_features(codes: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for raw in codes:
        m = _CODE_VALUE_RE.match(str(raw).strip())
        if m:
            try:
                out[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                continue
    return out


def _regime_from_codes(codes: List[str]) -> str:
    for c in codes:
        if str(c).startswith("regime="):
            return str(c).split("=", 1)[1].lower()
    return "unknown"


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        return v
    except (TypeError, ValueError):
        return None


def build_feature_observations(
    *,
    log_features: Optional[Dict[str, Any]] = None,
    telemetry_row: Optional[Dict[str, Any]] = None,
    reason_codes: Optional[List[str]] = None,
) -> Dict[str, FeatureObservation]:
    """Apply provenance precedence per core thesis feature."""
    log_map: Dict[str, float] = {}
    if isinstance(log_features, dict):
        for k, v in log_features.items():
            fv = _float_or_none(v)
            if fv is not None:
                log_map[str(k).lower()] = fv

    tel_map: Dict[str, float] = {}
    if telemetry_row:
        extra = telemetry_row.get("extra") if isinstance(telemetry_row.get("extra"), dict) else {}
        raw_feat = extra.get("features") or telemetry_row.get("features")
        if isinstance(raw_feat, dict):
            for k, v in raw_feat.items():
                fv = _float_or_none(v)
                if fv is not None:
                    tel_map[str(k).lower()] = fv
        codes = telemetry_row.get("policy_reason_codes") or reason_codes or []
        if isinstance(codes, list):
            tel_map.update(_parse_code_features([str(c) for c in codes]))

    code_map = _parse_code_features(reason_codes or [])

    out: Dict[str, FeatureObservation] = {}
    for key in CORE_THESIS_FEATURES:
        if key in log_map:
            out[key] = FeatureObservation(
                feature=key,
                value=log_map[key],
                source="log_market_context",
                confidence="high",
                observed=True,
            )
        elif key in tel_map:
            out[key] = FeatureObservation(
                feature=key,
                value=tel_map[key],
                source="telemetry_embedded",
                confidence="medium",
                observed=True,
            )
        elif key in code_map:
            out[key] = FeatureObservation(
                feature=key,
                value=code_map[key],
                source="telemetry_embedded",
                confidence="medium",
                observed=True,
            )
        else:
            out[key] = FeatureObservation(
                feature=key,
                value=None,
                source="default_missing",
                confidence="excluded",
                observed=False,
            )
    return out


def _provenance_summary(features: Dict[str, FeatureObservation]) -> Dict[str, int]:
    counts = {"high": 0, "medium": 0, "excluded": 0}
    for obs in features.values():
        counts[str(obs.confidence)] = counts.get(str(obs.confidence), 0) + 1
    return counts


def is_high_confidence_record(record: EnrichedDecisionRecord) -> bool:
    """All core features observed from high or medium provenance."""
    for key in CORE_THESIS_FEATURES:
        obs = record.features.get(key)
        if obs is None or not obs.observed or obs.confidence == "excluded":
            return False
    return True


def feature_dict_for_engine(record: EnrichedDecisionRecord) -> Dict[str, float]:
    """Numeric feature dict for thesis engine diagnostics (high/medium only)."""
    out: Dict[str, float] = {}
    for key, obs in record.features.items():
        if obs.observed and obs.value is not None:
            out[key] = float(obs.value)
    return out


def filter_high_confidence(records: List[EnrichedDecisionRecord]) -> List[EnrichedDecisionRecord]:
    return [r for r in records if is_high_confidence_record(r)]


def _index_telemetry(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[float], Dict[str, Dict[str, Any]]]:
    by_event: Dict[str, Dict[str, Any]] = {}
    ts_rows: List[Dict[str, Any]] = []
    ts_index: List[float] = []
    for row in rows:
        eid = row.get("event_id")
        if eid:
            by_event[str(eid)] = row
        ts = parse_ts_float(row.get("ts") or row.get("timestamp"))
        if ts is not None:
            ts_rows.append(row)
            ts_index.append(ts)
    return ts_rows, ts_index, by_event


def _match_telemetry(
    hold: Dict[str, Any],
    *,
    ts_rows: List[Dict[str, Any]],
    ts_index: List[float],
    by_event: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    eid = hold.get("event_id")
    if eid and str(eid) in by_event:
        return by_event[str(eid)]
    ts = parse_ts_float(hold.get("timestamp"))
    if ts is None:
        return None
    return nearest_before(ts_index, ts_rows, ts)


def parse_agent_log(content: str) -> List[EnrichedDecisionRecord]:
    """Build enriched records from agent log only."""
    return enrich_log_objects(list(iter_json_objects(content)))


def enrich_log_objects(objects: List[Dict[str, Any]]) -> List[EnrichedDecisionRecord]:
    v43_rows: List[Dict[str, Any]] = []
    v43_ts: List[float] = []
    cog_rows: List[Dict[str, Any]] = []
    cog_ts: List[float] = []
    shadow_rows: List[Dict[str, Any]] = []
    shadow_ts: List[float] = []
    holds: List[Dict[str, Any]] = []

    for obj in objects:
        event = str(obj.get("event") or obj.get("message") or "")
        ts = parse_ts_float(obj.get("timestamp"))

        if event == "mcp_orchestrator_v43_prediction_complete" and ts is not None:
            v43_rows.append(obj)
            v43_ts.append(ts)
        elif event == "cognition_thesis_authority_compare" and ts is not None:
            cog_rows.append(obj)
            cog_ts.append(ts)
        elif event == "rule_based_pipeline_shadow" and ts is not None:
            shadow_rows.append(obj)
            shadow_ts.append(ts)
        elif event == "trading_entry_rejected" and str(obj.get("reason")) == "hold_at_synthesis":
            holds.append(obj)

    records: List[EnrichedDecisionRecord] = []
    for hold in holds:
        ts_f = parse_ts_float(hold.get("timestamp"))
        if ts_f is None:
            continue
        v43 = nearest_before(v43_ts, v43_rows, ts_f)
        cognition = nearest_before(cog_ts, cog_rows, ts_f)
        shadow = nearest_before(shadow_ts, shadow_rows, ts_f)
        codes = reason_codes_from_context(hold)
        hyp = hypothesis_snapshot(hold)
        bucket = classify_hold_bucket(
            codes=codes,
            hyp=hyp,
            v43=v43,
            cognition=cognition,
            shadow=shadow,
        )
        mc = hold.get("market_context") if isinstance(hold.get("market_context"), dict) else {}
        log_features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
        regime = _regime_from_codes(codes) or str(mc.get("regime") or "unknown").lower()
        eligible = list((cognition or {}).get("eligible_profiles") or [])
        reject = str((v43 or {}).get("reject") or "") or None
        trade_score = _float_or_none(hold.get("trade_score") or (v43 or {}).get("trade_score"))

        features = build_feature_observations(
            log_features=log_features,
            telemetry_row=None,
            reason_codes=codes,
        )
        summary = _provenance_summary(features)
        records.append(
            EnrichedDecisionRecord(
                event_id=hold.get("event_id"),
                ts=str(hold.get("timestamp") or ""),
                symbol=str(hold.get("symbol") or mc.get("symbol") or "BTCUSD"),
                bucket=bucket,
                regime=regime,
                eligible_profiles=eligible,
                policy_reason_codes=codes,
                reject=reject,
                trade_score=trade_score,
                features=features,
                hypothesis_snapshot=hyp,
                shadow=dict(shadow) if shadow else None,
                provenance_summary=summary,
            )
        )
    return records


def _telemetry_embedded_features(row: Dict[str, Any]) -> Dict[str, float]:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    raw = extra.get("features") or row.get("features")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for k, v in raw.items():
        fv = _float_or_none(v)
        if fv is not None:
            out[str(k).lower()] = fv
    return out


def _telemetry_gates_passed_reject(row: Dict[str, Any]) -> Optional[str]:
    """Map telemetry gate blob / reject tag to gates_passed_* for B4 classification."""
    explicit = str(row.get("reject") or "")
    if explicit in ("gates_passed_long", "gates_passed_short"):
        return explicit
    gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
    if not gates:
        return None
    if gates.get("gate_reject"):
        return None
    g2_ok = all(bool(gates.get(k)) for k in ("g2_pass", "g3_pass", "g4_pass", "g5_pass"))
    if not g2_ok:
        return None
    if gates.get("g1_raw_long"):
        return "gates_passed_long"
    if gates.get("g1_raw_short"):
        return "gates_passed_short"
    return None


def telemetry_row_is_b4_candidate(row: Dict[str, Any]) -> bool:
    """True when a Phase-6 telemetry row is a B4-equivalent hold without requiring agent logs."""
    if str(row.get("event") or "") != "v43_prediction_complete":
        return False
    codes = [str(c) for c in (row.get("policy_reason_codes") or [])]
    if "hypothesis_no_rule_fired" not in codes and "thesis_no_rule_fired" not in codes:
        return False
    signal = str(row.get("signal") or row.get("thesis_signal") or "HOLD").upper()
    if signal != "HOLD":
        return False
    if _telemetry_gates_passed_reject(row) is None:
        return False
    feats = _telemetry_embedded_features(row)
    return all(k in feats for k in CORE_THESIS_FEATURES)


def record_from_telemetry_row(row: Dict[str, Any]) -> EnrichedDecisionRecord:
    """Build an enriched B4 record from an embedded-feature telemetry row."""
    codes = [str(c) for c in (row.get("policy_reason_codes") or [])]
    reject = _telemetry_gates_passed_reject(row)
    features = build_feature_observations(
        log_features=None,
        telemetry_row=row,
        reason_codes=codes,
    )
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    event_id = row.get("event_id") or extra.get("event_id")
    return EnrichedDecisionRecord(
        event_id=str(event_id) if event_id else None,
        ts=str(row.get("ts") or row.get("timestamp") or ""),
        symbol=str(row.get("symbol") or "BTCUSD"),
        bucket="B4",
        regime=_regime_from_codes(codes),
        eligible_profiles=[],
        policy_reason_codes=codes,
        reject=reject,
        trade_score=_float_or_none(row.get("trade_score")),
        features=features,
        hypothesis_snapshot={},
        shadow=None,
        provenance_summary=_provenance_summary(features),
    )


def _covered_by_log(
    tel_ts: float,
    tel_symbol: str,
    *,
    log_keys: List[Tuple[float, str]],
    max_delta_sec: float = 15.0,
) -> bool:
    for log_ts, log_symbol in log_keys:
        if log_symbol != tel_symbol:
            continue
        if abs(tel_ts - log_ts) <= max_delta_sec:
            return True
    return False


def enrich_from_sources(
    *,
    telemetry_path: Path,
    log_path: Optional[Path] = None,
    log_content: Optional[str] = None,
    hours: float = 168.0,
) -> List[EnrichedDecisionRecord]:
    """Join agent log holds with telemetry; also emit telemetry-primary B4 rows.

    Log-derived rows remain primary when present. Telemetry-primary B4 candidates
    (Phase 6 ``extra.features`` + ``hypothesis_no_rule_fired`` + gates passed) are
    appended when not already covered by a log hold within 15s — so evidence N no
    longer collapses when only a day-scoped log rotation is available.
    """
    if log_content is None and log_path and log_path.is_file():
        log_content = log_path.read_text(encoding="utf-8", errors="replace")

    tel_rows = filter_since(load_telemetry(telemetry_path), hours) if telemetry_path.is_file() else []
    ts_rows, ts_index, by_event = _index_telemetry(tel_rows)

    enriched: List[EnrichedDecisionRecord] = []
    log_keys: List[Tuple[float, str]] = []
    seen_event_ids: set[str] = set()

    if log_content:
        records = parse_agent_log(log_content)
        if hours > 0:
            cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600.0
            records = [r for r in records if (parse_ts_float(r.ts) or 0) >= cutoff]

        hold_features: Dict[str, Dict[str, Any]] = {}
        for obj in iter_json_objects(log_content):
            if str(obj.get("event") or "") != "trading_entry_rejected":
                continue
            mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
            feats = mc.get("features") if isinstance(mc.get("features"), dict) else {}
            key = str(obj.get("event_id") or obj.get("timestamp") or "")
            if key:
                hold_features[key] = feats

        for rec in records:
            hold_stub = {"event_id": rec.event_id, "timestamp": rec.ts}
            tel = _match_telemetry(hold_stub, ts_rows=ts_rows, ts_index=ts_index, by_event=by_event)
            key = str(rec.event_id or rec.ts)
            log_feats = hold_features.get(key) or {
                k: v.value
                for k, v in rec.features.items()
                if v.observed and v.source == "log_market_context"
            }
            features = build_feature_observations(
                log_features=log_feats or None,
                telemetry_row=tel,
                reason_codes=rec.policy_reason_codes,
            )
            out = EnrichedDecisionRecord(
                event_id=rec.event_id,
                ts=rec.ts,
                symbol=rec.symbol,
                bucket=rec.bucket,
                regime=rec.regime,
                eligible_profiles=rec.eligible_profiles,
                policy_reason_codes=rec.policy_reason_codes,
                reject=rec.reject,
                trade_score=rec.trade_score,
                features=features,
                hypothesis_snapshot=rec.hypothesis_snapshot,
                shadow=rec.shadow,
                provenance_summary=_provenance_summary(features),
            )
            enriched.append(out)
            ts_f = parse_ts_float(out.ts)
            if ts_f is not None:
                log_keys.append((ts_f, out.symbol.upper()))
            if out.event_id:
                seen_event_ids.add(str(out.event_id))

    for row in tel_rows:
        if not telemetry_row_is_b4_candidate(row):
            continue
        tel_rec = record_from_telemetry_row(row)
        if tel_rec.event_id and str(tel_rec.event_id) in seen_event_ids:
            continue
        tel_ts = parse_ts_float(tel_rec.ts)
        if tel_ts is None:
            continue
        if _covered_by_log(tel_ts, tel_rec.symbol.upper(), log_keys=log_keys):
            continue
        enriched.append(tel_rec)
        if tel_rec.event_id:
            seen_event_ids.add(str(tel_rec.event_id))

    enriched.sort(key=lambda r: parse_ts_float(r.ts) or 0.0)
    return enriched


def load_enriched_ndjson(path: Path) -> List[EnrichedDecisionRecord]:
    if not path.is_file():
        return []
    records: List[EnrichedDecisionRecord] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(EnrichedDecisionRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
    return records


def _is_telemetry_primary(record: EnrichedDecisionRecord) -> bool:
    has_log = any(
        obs.source == "log_market_context" and obs.observed for obs in record.features.values()
    )
    has_tel = any(
        obs.source == "telemetry_embedded" and obs.observed for obs in record.features.values()
    )
    return has_tel and not has_log


def provenance_report(records: List[EnrichedDecisionRecord]) -> Dict[str, Any]:
    b4 = [r for r in records if r.bucket == "B4"]
    hi = filter_high_confidence(b4)
    tel_only = 0
    default_missing = 0
    for r in b4:
        if _is_telemetry_primary(r):
            tel_only += 1
        if is_high_confidence_record(r):
            continue
        if all(not obs.observed for obs in r.features.values()):
            default_missing += 1
        elif not is_high_confidence_record(r):
            default_missing += 1

    n_b4 = len(b4)
    n_hi = len(hi)
    frac = round(n_hi / n_b4 * 100.0, 1) if n_b4 else 0.0
    gate = "PASS" if n_hi >= SWEEP_GATE_MIN_HIGH_CONFIDENCE else "FAIL"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "total_b4": n_b4,
        "high_confidence": n_hi,
        "telemetry_only": tel_only,
        "default_missing_excluded": default_missing,
        "high_confidence_fraction_pct": frac,
        "sweep_gate_min": SWEEP_GATE_MIN_HIGH_CONFIDENCE,
        "sweep_gate": gate,
    }


def render_coverage_markdown(report: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Decision Evidence Coverage",
            "",
            f"Generated: {report.get('generated_at')}",
            "",
            "| Metric | Value |",
            "|--------|------:|",
            f"| Total records | {report.get('total_records')} |",
            f"| Total B4 | {report.get('total_b4')} |",
            f"| High-confidence | {report.get('high_confidence')} |",
            f"| Telemetry-only (partial) | {report.get('telemetry_only')} |",
            f"| Default-missing (excluded) | {report.get('default_missing_excluded')} |",
            f"| High-confidence fraction | {report.get('high_confidence_fraction_pct')}% |",
            f"| Sweep gate (N>={report.get('sweep_gate_min')}) | **{report.get('sweep_gate')}** |",
        ]
    )
