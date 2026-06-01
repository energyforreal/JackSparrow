"""
Configuration management for agent service.

Handles environment variable loading, validation, and default values.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator

# Determine project root and env file paths, with Colab fallback.
#
# Env-file split:
#   - .env.example (committed): non-secret defaults, thresholds, feature flags.
#   - .env          (gitignored): secrets / credentials only (DB password, Delta keys, JWT, etc.).
# Pydantic Settings loads the tuple in order and lets later files override earlier ones,
# so .env values win over .env.example values when both define the same key.
def _get_project_root() -> Path:
    """Return repo root (directory containing both ``agent/`` and ``backend/``)."""
    try:
        start = Path(__file__).resolve().parent
        for candidate in (start, *start.parents):
            if (candidate / "agent").is_dir() and (candidate / "backend").is_dir():
                return candidate
    except (NameError, AttributeError):
        pass

    cwd = Path.cwd()
    if (cwd / "agent").is_dir() and (cwd / "backend").is_dir():
        return cwd
    current = cwd
    for _ in range(5):
        if (current / "agent").is_dir() and (current / "backend").is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    return cwd


ROOT_PROJECT_ROOT = _get_project_root()
ROOT_ENV_PATH = ROOT_PROJECT_ROOT / ".env"
ROOT_ENV_EXAMPLE_PATH = ROOT_PROJECT_ROOT / ".env.example"

# Delta India testnet hosts allowed for REST/WebSocket (runtime refuses prod URLs).
DELTA_TESTNET_ALLOWED_HOSTS: Tuple[str, ...] = (
    "cdn-ind.testnet.deltaex.org",
    "socket-ind.testnet.deltaex.org",
    "testnet.delta.exchange",
    "api.testnet.delta.exchange",
)
DELTA_TESTNET_BASE_URL_DEFAULT = "https://cdn-ind.testnet.deltaex.org"
DELTA_TESTNET_WEBSOCKET_URL_DEFAULT = "wss://cdn-ind.testnet.deltaex.org"


def _root_env_files() -> tuple[str, ...] | None:
    """Return existing env files in load order (.env.example, then .env)."""
    paths: list[str] = []
    if ROOT_ENV_EXAMPLE_PATH.exists():
        paths.append(str(ROOT_ENV_EXAMPLE_PATH))
    if ROOT_ENV_PATH.exists():
        paths.append(str(ROOT_ENV_PATH))
    return tuple(paths) if paths else None


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_root_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
        protected_namespaces=("settings_",),
        # In Colab / containers, process env wins over file contents.
        env_ignore_empty=True,
    )
    
    # Database
    database_url: str = Field(
        ...,
        env=("DATABASE_URL", "database_url"),
        description="PostgreSQL database connection URL"
    )
    environment: str = Field(
        default="local",
        env=("ENVIRONMENT", "APP_ENV", "environment"),
        description="Deployment environment identifier (e.g., local, dev, prod)"
    )
    
    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        env="REDIS_URL",
        description="Redis connection URL"
    )
    
    # Delta Exchange API
    delta_exchange_api_key: str = Field(
        ...,
        env=("DELTA_EXCHANGE_API_KEY", "DELTA_API_KEY", "delta_api_key"),
        description="Delta Exchange API key"
    )
    delta_exchange_api_secret: str = Field(
        ...,
        env=("DELTA_EXCHANGE_API_SECRET", "DELTA_API_SECRET", "delta_api_secret"),
        description="Delta Exchange API secret"
    )
    delta_exchange_base_url: str = Field(
        default=DELTA_TESTNET_BASE_URL_DEFAULT,
        env=("DELTA_EXCHANGE_BASE_URL", "DELTA_API_URL", "delta_api_url"),
        description="Delta Exchange API base URL (must be India testnet)",
    )
    
    # Vector Database (Optional)
    qdrant_url: Optional[str] = Field(
        default=None,
        env="QDRANT_URL",
        description="Qdrant vector database URL"
    )
    qdrant_api_key: Optional[str] = Field(
        default=None,
        env="QDRANT_API_KEY",
        description="Qdrant API key"
    )
    
    # Model Configuration
    model_path: Optional[str] = Field(
        default=None,
        env="MODEL_PATH",
        description="Path to production model file"
    )
    model_dir: str = Field(
        default="./agent/model_storage/JackSparrow_IC_BTCUSD",
        env="MODEL_DIR",
        description=(
            "Intelligence Component bundle directory (metadata_ic.json). "
            "Legacy v43 ML bundles are no longer loaded."
        ),
    )
    ic_mode: bool = Field(
        default=True,
        env="IC_MODE",
        description="Use rule-based Intelligence Component instead of ML model artifacts.",
    )
    ic_default_threshold: float = Field(
        default=0.005,
        env="IC_DEFAULT_THRESHOLD",
        description="Default long/short threshold for IC horizon heads when metadata omits values.",
    )
    model_discovery_recursive: bool = Field(
        default=False,
        env="MODEL_DISCOVERY_RECURSIVE",
        description=(
            "JackSparrow v43 uses a flat bundle root (metadata_v43.json or metadata_v44.json). "
            "Recursive scan is legacy; leave false unless you mirror old multi-folder layouts."
        ),
    )
    model_discovery_enabled: bool = Field(
        default=True,
        env="MODEL_DISCOVERY_ENABLED",
        description="Enable automatic model discovery"
    )
    single_model_mode_enabled: bool = Field(
        default=False,
        env="SINGLE_MODEL_MODE_ENABLED",
        description=(
            "DEPRECATED: v43-only agent ignores this flag — use MODEL_DIR with "
            "metadata_v43.json or metadata_v44.json."
        ),
    )
    consolidated_model_metadata_glob: str = Field(
        default="metadata_BTCUSD_consolidated*.json",
        env="CONSOLIDATED_MODEL_METADATA_GLOB",
        description="DEPRECATED: unused with v43-only discovery.",
    )
    single_model_strict_startup: bool = Field(
        default=False,
        env="SINGLE_MODEL_STRICT_STARTUP",
        description="DEPRECATED: unused with v43-only discovery.",
    )
    model_auto_register: bool = Field(
        default=True,
        env="MODEL_AUTO_REGISTER",
        description="Auto-register discovered models"
    )
    model_format: str = Field(
        default="jacksparrow_ic",
        env="MODEL_FORMAT",
        description=(
            "Integration label (health/API). Runtime uses rule-based IC bundle discovery."
        ),
    )
    model_prediction_timeout_seconds: float = Field(
        default=12.0,
        env="MODEL_PREDICTION_TIMEOUT_SECONDS",
        description=(
            "Per-model asyncio timeout for registry predictions. v43 inference plus "
            "lock contention can exceed 5s on busy cycles."
        ),
    )
    v15_signal_logic_enabled: bool = Field(
        default=False,
        env="V15_SIGNAL_LOGIC_ENABLED",
        description="DEPRECATED: v15 pipeline integration removed; keep False.",
    )
    v15_disable_mtf_synthesis: bool = Field(
        default=True,
        env="V15_DISABLE_MTF_SYNTHESIS",
        description="When True, skip mtf_decision_engine synthesis if v15 pipeline models are loaded.",
    )
    v15_filter_feature_source_tf: str = Field(
        default="5m",
        env="V15_FILTER_FEATURE_SOURCE_TF",
        description="Which timeframe's feature snapshot to use for ADX/ATR entry filters (5m or 15m).",
    )
    confidence_percentile: float = Field(
        default=70.0,
        env="CONFIDENCE_PERCENTILE",
        description="Rolling percentile of |edge| for v15 entry gating (e.g. 90 = top 10%).",
    )
    edge_floor: float = Field(
        default=0.11,
        env="EDGE_FLOOR",
        description="Minimum |edge| for v15 directional entry.",
    )
    atr_trailing_mult: float = Field(
        default=1.5,
        env="ATR_TRAILING_MULT",
        description="ATR multiplier for v15 trailing stop.",
    )
    min_hold_bars: int = Field(
        default=5,
        env="MIN_HOLD_BARS",
        description="Minimum bars before v15 soft exits (trail, edge decay).",
    )
    edge_decay_threshold: float = Field(
        default=0.05,
        env="EDGE_DECAY_THRESHOLD",
        description="Exit when |edge| falls below this after min hold (v15).",
    )
    v15_min_edge_cost_ratio: float = Field(
        default=1.2,
        env="V15_MIN_EDGE_COST_RATIO",
        description=(
            "Require abs(edge) >= per_leg_cost * ratio where per_leg_cost = taker + slippage "
            "(matches notebook MIN_EDGE_COST_RATIO vs round-trip fee model)."
        ),
    )
    v15_min_trade_gap_bars: int = Field(
        default=3,
        env="V15_MIN_TRADE_GAP_BARS",
        description="Minimum completed bars between new entries (notebook MIN_GAP_CANDLES).",
    )
    v15_min_trade_gap_enabled: bool = Field(
        default=False,
        env="V15_MIN_TRADE_GAP_ENABLED",
        description="When True, enforce min bar gap between paper entries.",
    )
    v15_max_trades_per_day_5m: int = Field(
        default=8,
        env="V15_MAX_TRADES_PER_DAY_5M",
        description="Daily cap for 5m timeframe (notebook TF_MAX_TRADES_DAY).",
    )
    v15_max_trades_per_day_15m: int = Field(
        default=4,
        env="V15_MAX_TRADES_PER_DAY_15M",
        description="Daily cap for 15m timeframe.",
    )
    v15_daily_trade_cap_enabled: bool = Field(
        default=False,
        env="V15_DAILY_TRADE_CAP_ENABLED",
        description="When True, enforce per-timeframe daily trade caps for v15.",
    )
    position_restore_on_startup: bool = Field(
        default=True,
        env="POSITION_RESTORE_ON_STARTUP",
        description="Load open DB positions into the execution engine after startup (paper).",
    )
    exchange_position_reconcile_enabled: bool = Field(
        default=True,
        env="EXCHANGE_POSITION_RECONCILE_ENABLED",
        description=(
            "When True, sync position_manager with Delta margined positions on startup "
            "and during the position monitor loop."
        ),
    )
    require_ml_signal_for_orders: bool = Field(
        default=True,
        env="REQUIRE_ML_SIGNAL_FOR_ORDERS",
        description=(
            "When True, entry orders on Delta require validated ML model predictions "
            "(v43 gates passed and policy adopted ML evidence)."
        ),
    )
    require_ml_consensus_alignment: bool = Field(
        default=True,
        env="REQUIRE_ML_CONSENSUS_ALIGNMENT",
        description=(
            "When True (non-v43 path), trade side must align with model consensus_signal."
        ),
    )
    require_v43_gates_for_entry: bool = Field(
        default=True,
        env="REQUIRE_V43_GATES_FOR_ENTRY",
        description=(
            "When True, JackSparrow v43 entries require final_long/final_short gates passed."
        ),
    )
    agent_only_delta_orders: bool = Field(
        default=True,
        env="AGENT_ONLY_DELTA_ORDERS",
        description=(
            "When True, only agent-decision execution may place Delta orders; manual "
            "execute_trade is blocked and unattributed exchange fills are flattened."
        ),
    )
    block_manual_execute_trade: bool = Field(
        default=True,
        env="BLOCK_MANUAL_EXECUTE_TRADE",
        description=(
            "When True, reject execute_trade commands that are not from the autonomous "
            "agent decision pipeline (RiskApproved → execution)."
        ),
    )
    agent_order_attribution_window_seconds: float = Field(
        default=3600.0,
        ge=60.0,
        env="AGENT_ORDER_ATTRIBUTION_WINDOW_SECONDS",
        description="Seconds to treat a recent agent js_ order as attributable to an exchange position.",
    )
    exchange_position_reconcile_orphan_mode: str = Field(
        default="close_orphan",
        env="EXCHANGE_POSITION_RECONCILE_ORPHAN_MODE",
        description=(
            "How to handle exchange legs missing locally when not agent-attributed: "
            "'close_orphan' (flatten) or 'adopt' (only used when agent attribution matches)."
        ),
    )
    exchange_position_reconcile_interval_seconds: float = Field(
        default=30.0,
        ge=5.0,
        env="EXCHANGE_POSITION_RECONCILE_INTERVAL_SECONDS",
        description="Minimum seconds between exchange reconciliation passes.",
    )
    volatility_filter_enabled: bool = Field(
        default=True,
        env="VOLATILITY_FILTER_ENABLED",
        description="v15: skip entry when atr_pct is in bottom quartile / below floor.",
    )
    v15_atr_pct_floor: float = Field(
        default=0.0005,
        env="V15_ATR_PCT_FLOOR",
        description="Minimum atr_pct (ratio) to pass v15 volatility filter when enabled.",
    )
    v15_adx_ranging_max: float = Field(
        default=25.0,
        env="V15_ADX_RANGING_MAX",
        description="v15: only enter when ADX <= this (ranging regime).",
    )
    v15_adx_regime_filter_enabled: bool = Field(
        default=True,
        env="V15_ADX_REGIME_FILTER_ENABLED",
        description=(
            "When True, v15 entry gate requires ADX <= v15_adx_ranging_max. "
            "When False, ADX is ignored for v15 entry (allows trend regimes)."
        ),
    )
    htf_cache_ttl_seconds: int = Field(
        default=840,
        env="HTF_CACHE_TTL_SECONDS",
        description="Redis TTL for 15m HTF feature rows used by 5m v15 model (seconds).",
    )
    allow_feature_fallback_predictions: bool = Field(
        default=False,
        env="ALLOW_FEATURE_FALLBACK_PREDICTIONS",
        description=(
            "DEPRECATED: Previously allowed feature-based fallback predictions when no ML "
            "models were available. This setting is now ignored and feature-based fallbacks "
            "are disabled so that all trading decisions require real ML model predictions."
        ),
    )
    require_models_on_startup: bool = Field(
        default=False,
        env="REQUIRE_MODELS_ON_STARTUP",
        description=(
            "When True, the MCP orchestrator raises if zero ML models load at startup. "
            "Recommended True in Docker/production; False for local/tests without model artifacts."
        ),
    )
    prediction_audit_writes_enabled: bool = Field(
        default=True,
        env="PREDICTION_AUDIT_WRITES_ENABLED",
        description="When True, persist each DecisionReady path to prediction_audit (PostgreSQL).",
    )
    learning_state_persistence_enabled: bool = Field(
        default=True,
        env="LEARNING_STATE_PERSISTENCE_ENABLED",
        description="When True, persist learning system state snapshots to local disk.",
    )
    learning_state_path: str = Field(
        default="learning_state.json",
        env="LEARNING_STATE_PATH",
        description="Path to persisted learning state (JSON).",
    )
    feature_drift_logging_enabled: bool = Field(
        default=True,
        env="FEATURE_DRIFT_LOGGING_ENABLED",
        description="When True, log feature drift warnings during live inference (when stats available).",
    )
    feature_drift_sigma_threshold: float = Field(
        default=4.0,
        env="FEATURE_DRIFT_SIGMA_THRESHOLD",
        description="Drift threshold in training stddev units (z-score) beyond which a feature is flagged.",
    )

    # Retraining scheduler (local automation)
    retraining_scheduler_enabled: bool = Field(
        default=False,
        env="RETRAINING_SCHEDULER_ENABLED",
        description="When True, periodically evaluate outcomes and trigger a local retraining command.",
    )
    retraining_scheduler_interval_seconds: int = Field(
        default=3600,
        env="RETRAINING_SCHEDULER_INTERVAL_SECONDS",
        description="How often to evaluate retraining triggers (seconds).",
    )
    retraining_min_closed_trades: int = Field(
        default=50,
        env="RETRAINING_MIN_CLOSED_TRADES",
        description="Minimum closed trades required before retraining trigger can fire.",
    )
    retraining_rolling_window: int = Field(
        default=100,
        env="RETRAINING_ROLLING_WINDOW",
        description="How many recent closed trades to evaluate for retraining trigger.",
    )
    retraining_win_rate_threshold: float = Field(
        default=0.45,
        env="RETRAINING_WIN_RATE_THRESHOLD",
        description="Trigger retraining when win rate falls below this threshold over the rolling window.",
    )
    retraining_profit_factor_threshold: float = Field(
        default=0.90,
        env="RETRAINING_PROFIT_FACTOR_THRESHOLD",
        description="Trigger retraining when profit factor falls below this threshold over the rolling window.",
    )
    retraining_cooldown_minutes: int = Field(
        default=360,
        env="RETRAINING_COOLDOWN_MINUTES",
        description="Minimum minutes between retraining runs.",
    )
    retraining_command: str = Field(
        default="",
        env="RETRAINING_COMMAND",
        description="Shell command to run for retraining/export (empty disables execution).",
    )
    retraining_state_path: str = Field(
        default="retraining_state.json",
        env="RETRAINING_STATE_PATH",
        description="Path to retraining scheduler state (JSON).",
    )

    # Adaptive drift + warm-start retrain (v15 pipeline bundles under MODEL_DIR)
    adaptive_retrain_enabled: bool = Field(
        default=False,
        env="ADAPTIVE_RETRAIN_ENABLED",
        description=(
            "When True, periodically run KS drift check and optional warm-start "
            "retrain with F1 validation gate; persists versioned pipelines and refreshes models."
        ),
    )
    adaptive_retrain_check_interval_seconds: int = Field(
        default=3600,
        env="ADAPTIVE_RETRAIN_CHECK_INTERVAL_SECONDS",
        ge=60,
        description="How often to evaluate adaptive retrain (seconds).",
    )
    adaptive_retrain_cooldown_hours: float = Field(
        default=12.0,
        env="ADAPTIVE_RETRAIN_COOLDOWN_HOURS",
        ge=0.0,
        description="Minimum hours between adaptive retrains per timeframe.",
    )
    adaptive_drift_alpha: float = Field(
        default=0.01,
        env="ADAPTIVE_DRIFT_ALPHA",
        description="KS two-sample p-value threshold (reject if p < alpha).",
    )
    adaptive_drift_stat_threshold: float = Field(
        default=0.10,
        env="ADAPTIVE_DRIFT_STAT_THRESHOLD",
        description="Minimum KS statistic to count a feature as drifted.",
    )
    adaptive_drift_feature_limit: int = Field(
        default=5,
        env="ADAPTIVE_DRIFT_FEATURE_LIMIT",
        ge=1,
        description="Retrain when drifted feature count exceeds this limit.",
    )
    adaptive_drift_min_rows: int = Field(
        default=40000,
        env="ADAPTIVE_DRIFT_MIN_ROWS",
        ge=1000,
        description="Minimum labeled rows required before drift/retrain (matches notebook).",
    )
    adaptive_drift_recent_rows: int = Field(
        default=20000,
        env="ADAPTIVE_DRIFT_RECENT_ROWS",
        ge=500,
        description="Recent window row count for KS drift (tail).",
    )
    adaptive_drift_past_rows: int = Field(
        default=20000,
        env="ADAPTIVE_DRIFT_PAST_ROWS",
        ge=500,
        description="Past comparison window row count (immediately before recent).",
    )
    adaptive_retrain_window_rows_5m: int = Field(
        default=80000,
        env="ADAPTIVE_RETRAIN_WINDOW_ROWS_5M",
        ge=1000,
        description="Max training rows slice from tail for 5m adaptive retrain.",
    )
    adaptive_retrain_window_rows_15m: int = Field(
        default=40000,
        env="ADAPTIVE_RETRAIN_WINDOW_ROWS_15M",
        ge=1000,
        description="Max training rows slice from tail for 15m adaptive retrain.",
    )
    adaptive_rolling_days_train: int = Field(
        default=60,
        env="ADAPTIVE_ROLLING_DAYS_TRAIN",
        ge=1,
        description="If DataFrame has DatetimeIndex, restrict train slice to last N days.",
    )
    adaptive_num_boost_round_incremental: int = Field(
        default=150,
        env="ADAPTIVE_NUM_BOOST_ROUND_INCREMENTAL",
        ge=1,
        description="XGBoost trees to add per warm-start retrain.",
    )
    adaptive_validation_window_rows: int = Field(
        default=10000,
        env="ADAPTIVE_VALIDATION_WINDOW_ROWS",
        ge=100,
        description="Holdout tail rows for F1 acceptance gate.",
    )
    adaptive_min_f1_improvement: float = Field(
        default=0.0,
        env="ADAPTIVE_MIN_F1_IMPROVEMENT",
        description="Require new_f1 >= old_f1 + this delta to accept.",
    )
    adaptive_class_weight_sell: float = Field(
        default=1.3,
        env="ADAPTIVE_CLASS_WEIGHT_SELL",
        description="Sample weight for label 0 (SELL); must match training Cell 5.",
    )
    adaptive_class_weight_hold: float = Field(
        default=0.5,
        env="ADAPTIVE_CLASS_WEIGHT_HOLD",
        description="Sample weight for label 1 (HOLD).",
    )
    adaptive_class_weight_buy: float = Field(
        default=1.3,
        env="ADAPTIVE_CLASS_WEIGHT_BUY",
        description="Sample weight for label 2 (BUY).",
    )
    adaptive_retrain_timeframes: str = Field(
        default="5m,15m",
        env="ADAPTIVE_RETRAIN_TIMEFRAMES",
        description="Comma-separated timeframes to run adaptive retrain for.",
    )
    adaptive_labeled_data_source: str = Field(
        default="none",
        env="ADAPTIVE_LABELED_DATA_SOURCE",
        description="none | parquet — source for labeled feature+label DataFrames.",
    )
    adaptive_retrain_parquet_dir: str = Field(
        default="",
        env="ADAPTIVE_RETRAIN_PARQUET_DIR",
        description=(
            "Directory containing labeled_{tf}.parquet (e.g. labeled_5m.parquet) "
            "with columns matching metadata features plus label."
        ),
    )
    adaptive_retrain_state_path: str = Field(
        default="adaptive_retrain_state.json",
        env="ADAPTIVE_RETRAIN_STATE_PATH",
        description="JSON path for per-TF last retrain timestamps (cooldown).",
    )
    adaptive_retrain_log_name: str = Field(
        default="retrain_log.json",
        env="ADAPTIVE_RETRAIN_LOG_NAME",
        description="Audit log filename written next to each timeframe's metadata folder.",
    )
    adaptive_min_clean_rows: int = Field(
        default=1000,
        env="ADAPTIVE_MIN_CLEAN_ROWS",
        ge=100,
        description="Minimum rows after cleaning required to attempt retrain.",
    )
    adaptive_drift_metric: str = Field(
        default="ks",
        env="ADAPTIVE_DRIFT_METRIC",
        description="ks | psi | both | either — feature drift detection mode.",
    )
    adaptive_drift_psi_threshold: float = Field(
        default=0.20,
        env="ADAPTIVE_DRIFT_PSI_THRESHOLD",
        description="PSI above this counts as drifted for a feature (v43 consensus default 0.20).",
    )
    adaptive_drift_psi_bins: int = Field(
        default=10,
        env="ADAPTIVE_DRIFT_PSI_BINS",
        ge=3,
        description="Histogram bins for PSI.",
    )
    adaptive_performance_retrain_enabled: bool = Field(
        default=False,
        env="ADAPTIVE_PERFORMANCE_RETRAIN_ENABLED",
        description="When True, poor live trade outcomes can trigger adaptive retrain (OR with drift).",
    )
    adaptive_performance_rolling_trades: int = Field(
        default=50,
        env="ADAPTIVE_PERFORMANCE_ROLLING_TRADES",
        ge=10,
        description="Recent closed trades to evaluate for performance trigger.",
    )
    adaptive_performance_min_trades: int = Field(
        default=30,
        env="ADAPTIVE_PERFORMANCE_MIN_TRADES",
        ge=5,
        description="Minimum trades required before performance trigger applies.",
    )
    adaptive_performance_win_rate_floor: float = Field(
        default=0.40,
        env="ADAPTIVE_PERFORMANCE_WIN_RATE_FLOOR",
        description="Trigger retrain when rolling win rate falls below this.",
    )
    adaptive_performance_profit_factor_floor: float = Field(
        default=0.85,
        env="ADAPTIVE_PERFORMANCE_PROFIT_FACTOR_FLOOR",
        description="Trigger retrain when rolling profit factor falls below this.",
    )
    adaptive_performance_max_drawdown_ceiling: float = Field(
        default=0.35,
        env="ADAPTIVE_PERFORMANCE_MAX_DD_CEILING",
        description="Trigger retrain when rolling equity drawdown proxy exceeds this fraction.",
    )
    adaptive_validation_scorecard_enabled: bool = Field(
        default=False,
        env="ADAPTIVE_VALIDATION_SCORECARD_ENABLED",
        description="When True, require val win-rate / PF / DD proxies not worse than previous model.",
    )
    adaptive_retrain_subprocess_enabled: bool = Field(
        default=True,
        env="ADAPTIVE_RETRAIN_SUBPROCESS_ENABLED",
        description=(
            "When True, run adaptive warm-start retrain in a separate Python process "
            "so CPU-bound training does not block the agent asyncio loop."
        ),
    )
    adaptive_retrain_subprocess_timeout_seconds: int = Field(
        default=7200,
        env="ADAPTIVE_RETRAIN_SUBPROCESS_TIMEOUT_SECONDS",
        ge=60,
        description="Hard timeout for adaptive retrain worker subprocess.",
    )
    adaptive_drift_require_ks_psi_consensus: bool = Field(
        default=True,
        env="ADAPTIVE_DRIFT_REQUIRE_KS_PSI_CONSENSUS",
        description=(
            "When True, a feature counts toward drift only if both KS (p<alpha, stat>thr) "
            "and PSI (>threshold) flag the same feature; retrain when consensus count "
            "meets adaptive_drift_feature_limit."
        ),
    )
    adaptive_drift_consensus_min_count: int = Field(
        default=5,
        env="ADAPTIVE_DRIFT_CONSENSUS_MIN_COUNT",
        ge=1,
        description="Minimum number of KS+PSI consensus drift features to trigger retrain.",
    )
    adaptive_retrain_failure_cooldown_base_hours: float = Field(
        default=1.0,
        env="ADAPTIVE_RETRAIN_FAILURE_COOLDOWN_BASE_HOURS",
        ge=0.0,
        description="Base cooldown hours after a rejected/failed adaptive retrain (doubles up to max).",
    )
    adaptive_retrain_failure_cooldown_max_hours: float = Field(
        default=8.0,
        env="ADAPTIVE_RETRAIN_FAILURE_COOLDOWN_MAX_HOURS",
        ge=0.0,
        description="Maximum exponential-backoff cooldown after adaptive retrain failures.",
    )
    adaptive_v43_five_gates_enabled: bool = Field(
        default=True,
        env="ADAPTIVE_V43_FIVE_GATES_ENABLED",
        description=(
            "When True, adaptive model promotion also requires the five v43-style validation gates "
            "(macro AUC, IC proxy, win rate, return proxy, Sharpe proxy) on the holdout slice."
        ),
    )
    feature_server_fail_closed_no_candles: bool = Field(
        default=True,
        env="FEATURE_SERVER_FAIL_CLOSED_NO_CANDLES",
        description="When True, no candles yields UNAVAILABLE features (no zero placeholders).",
    )
    strict_candle_validation_enabled: bool = Field(
        default=True,
        env="STRICT_CANDLE_VALIDATION_ENABLED",
        description="When True, validate spacing/OHLC on v15 feature path.",
    )
    strict_candle_validation_min_rows: int = Field(
        default=50,
        env="STRICT_CANDLE_VALIDATION_MIN_ROWS",
        ge=2,
        description="Minimum candle rows required after validation.",
    )

    # JackSparrow v43 dedicated bundle (metadata_v43.json + model_artifact_v43.pkl)
    jacksparrow_v43_mode_enabled: bool = Field(
        default=True,
        env="JACKSPARROW_V43_MODE_ENABLED",
        description=(
            "DEPRECATED: v43 is the only integration path; discovery always loads the v43 "
            "bundle under MODEL_DIR. Kept for env compat."
        ),
    )

    # JackSparrow MSO v50 market-state oracle (optional alongside v43)
    mso_model_enabled: bool = Field(
        default=False,
        env="MSO_MODEL_ENABLED",
        description="Load MarketStateOracleNode when metadata_mso_v50.json exists in MODEL_DIR.",
    )
    mso_require_trend_regime: bool = Field(
        default=False,
        env="MSO_REQUIRE_TREND_REGIME",
        description="When True, block entries unless intraday_30m trend regime is directional.",
    )
    mso_breakout_min_prob: float = Field(
        default=0.55,
        env="MSO_BREAKOUT_MIN_PROB",
        ge=0.0,
        le=1.0,
        description="Minimum P(BREAKOUT_FORMING|CONFIRMED) for momentum-style entries.",
    )
    mso_liquidity_veto_classes: str = Field(
        default="STOP_HUNT_ENV,LIQ_SWEEP_ACTIVE",
        env="MSO_LIQUIDITY_VETO_CLASSES",
        description="Comma-separated liquidity_condition labels that veto new entries.",
    )
    mso_oi_max_staleness_seconds: int = Field(
        default=600,
        env="MSO_OI_MAX_STALENESS_SECONDS",
        ge=60,
        description="Block MSO inference if OI snapshot older than this (seconds).",
    )
    mso_require_real_oi: bool = Field(
        default=True,
        env="MSO_REQUIRE_REAL_OI",
        description="Raise InsufficientRealDataError on zero/stale OI (no synthetic fallback).",
    )
    mso_require_export_gates: bool = Field(
        default=True,
        env="MSO_REQUIRE_EXPORT_GATES",
        description="Refuse MSO node init when metadata export_gate_passed is false.",
    )
    mso_shadow_mode: bool = Field(
        default=False,
        env="MSO_SHADOW_MODE",
        description="Log MSO policy vetoes/boosts without applying them (paper validation).",
    )
    use_bracket_orders: bool = Field(
        default=True,
        env="USE_BRACKET_ORDERS",
        description="Use Delta bracket SL/TP on entry order when stop and target prices are set.",
    )

    jacksparrow_v43_artifact_basename: str = Field(
        default="model_artifact_v43_patched.pkl",
        env="JACKSPARROW_V43_ARTIFACT_BASENAME",
        description=(
            "Primary v43 artifact filename when present in MODEL_DIR; "
            "falls back to v43/v44 artifact aliases when missing."
        ),
    )
    jacksparrow_v43_metadata_glob: str = Field(
        default="**/metadata_v43.json",
        env="JACKSPARROW_V43_METADATA_GLOB",
        description="Glob under MODEL_DIR to locate v43 metadata (unused when MODEL_DIR is bundle root).",
    )
    jacksparrow_v43_candles_5m: int = Field(
        default=600,
        env="JACKSPARROW_V43_CANDLES_5M",
        ge=50,
        description="Number of 5m candles to fetch for v43 feature_engineer.transform.",
    )
    jacksparrow_v43_candles_15m: int = Field(
        default=400,
        env="JACKSPARROW_V43_CANDLES_15M",
        ge=50,
        description="Number of 15m candles for v43.",
    )
    jacksparrow_v43_candles_1h: int = Field(
        default=300,
        env="JACKSPARROW_V43_CANDLES_1H",
        ge=48,
        description="Number of 1h candles for v43 (OHLCV + funding alignment).",
    )
    jacksparrow_v43_candles_oi: int = Field(
        default=300,
        env="JACKSPARROW_V43_CANDLES_OI",
        ge=48,
        description=(
            "Max OI snapshots to request for v43 feature engineering (5m cadence). "
            "Real-only: shorter frames are returned until the ring buffer fills."
        ),
    )
    jacksparrow_v43_oi_enabled: bool = Field(
        default=True,
        env="JACKSPARROW_V43_OI_ENABLED",
        description=(
            "Enable OI feature fetching from Delta public ticker API. "
            "When False, OI features are zero-filled."
        ),
    )
    jacksparrow_v43_oi_fetch_timeout_s: float = Field(
        default=4.0,
        env="JACKSPARROW_V43_OI_FETCH_TIMEOUT_S",
        ge=1.0,
        le=15.0,
        description="Per-request timeout for the OI public ticker fetch (seconds).",
    )
    jacksparrow_v43_oi_public_base_url: str = Field(
        default="https://api.india.delta.exchange",
        env="JACKSPARROW_V43_OI_PUBLIC_BASE_URL",
        description=(
            "Public REST base URL for OI ticker reads only (no auth). "
            "May differ from DELTA_EXCHANGE_BASE_URL (testnet trading)."
        ),
    )
    jacksparrow_v43_basis_zscore_window: int = Field(
        default=48,
        env="JACKSPARROW_V43_BASIS_ZSCORE_WINDOW",
        ge=12,
        le=200,
        description="Rolling window (5m bars) for basis z-score feature.",
    )
    jacksparrow_v43_crowding_basis_threshold: float = Field(
        default=2.0,
        env="JACKSPARROW_V43_CROWDING_BASIS_THRESHOLD",
        description="Absolute basis_zscore threshold for basis crowding thesis.",
    )
    jacksparrow_v43_crowding_oi_threshold: float = Field(
        default=1.0,
        env="JACKSPARROW_V43_CROWDING_OI_THRESHOLD",
        description="Minimum oi_zscore for basis crowding thesis.",
    )
    jacksparrow_v43_crowding_funding_x_oi_threshold: float = Field(
        default=1.5,
        env="JACKSPARROW_V43_CROWDING_FUNDING_X_OI_THRESHOLD",
        description="Absolute funding_x_oi threshold for funding crowding thesis.",
    )
    jacksparrow_v43_price_band_veto_pct: float = Field(
        default=0.5,
        env="JACKSPARROW_V43_PRICE_BAND_VETO_PCT",
        description="Veto longs within this %% of upper band; shorts near lower band.",
    )
    jacksparrow_v43_contract_state_ttl_s: float = Field(
        default=60.0,
        env="JACKSPARROW_V43_CONTRACT_STATE_TTL_S",
        ge=5.0,
        le=600.0,
        description="TTL for in-process contract state cache (seconds).",
    )
    jacksparrow_v43_forward_target_bars: int = Field(
        default=2,
        env="JACKSPARROW_V43_FORWARD_TARGET_BARS",
        ge=1,
        description=(
            "Training label horizon in 5m bars for new v43 exports (2 = scalp 10m). "
            "Runtime uses metadata.primary_execution_horizon_bars from the loaded bundle."
        ),
    )
    jacksparrow_v43_align_execution_to_horizon: bool = Field(
        default=True,
        env="JACKSPARROW_V43_ALIGN_EXECUTION_TO_HORIZON",
        description=(
            "When True, debounce/max-hold/TP hints follow the loaded model's "
            "training_forward_bars via v43 execution profile."
        ),
    )
    jacksparrow_v43_require_horizon_fusion_match: bool = Field(
        default=True,
        env="JACKSPARROW_V43_REQUIRE_HORIZON_FUSION_MATCH",
        description=(
            "When True, ml_and_thesis fusion requires thesis intended_horizon_bars "
            "to match the ML bundle training_forward_bars."
        ),
    )
    jacksparrow_v43_trade_debounce_bars: int = Field(
        default=1,
        env="JACKSPARROW_V43_TRADE_DEBOUNCE_BARS",
        ge=1,
        description=(
            "Minimum 5m bars between v43 entries when horizon alignment is off "
            "(default 2 ≈ 10 min for 30m label training)."
        ),
    )
    jacksparrow_v43_max_trades_per_hour: int = Field(
        default=6,
        env="JACKSPARROW_V43_MAX_TRADES_PER_HOUR",
        ge=1,
        description="Gate 3: max entries per rolling hour.",
    )
    jacksparrow_v43_max_trades_per_day: int = Field(
        default=20,
        env="JACKSPARROW_V43_MAX_TRADES_PER_DAY",
        ge=1,
        description="Gate 3: max entries per UTC day.",
    )
    jacksparrow_v43_min_edge_cost_ratio: float = Field(
        default=0.2,
        env="JACKSPARROW_V43_MIN_EDGE_COST_RATIO",
        ge=0.0,
        description=(
            "Gate 5: min multiple of round-trip cost vs expected-return edge. "
            "Default 0.2 matches v43 regressor scale (~1e-4 predictions); raise toward "
            "0.5–1.25 after measuring reject rates (docs/v43_trade_execution_runbook.md)."
        ),
    )
    jacksparrow_v43_block_trending_entries: bool = Field(
        default=False,
        env="JACKSPARROW_V43_BLOCK_TRENDING_ENTRIES",
        description="When True, skip entries when regime_label is trending.",
    )
    jacksparrow_v43_threshold_oof_percentile: float = Field(
        default=75.0,
        env="JACKSPARROW_V43_THRESHOLD_OOF_PERCENTILE",
        ge=1.0,
        le=99.0,
        description="OOF percentile hint for diagnostics / collapse tuning (75 default).",
    )
    jacksparrow_v43_signal_threshold_floor: float = Field(
        default=0.005,
        env="JACKSPARROW_V43_SIGNAL_THRESHOLD_FLOOR",
        ge=0.0,
        description=(
            "Soft floor for threshold resolution; must stay below OOF P75 (~0.011) so "
            "it does not block patched calibrations."
        ),
    )
    jacksparrow_v43_metadata_promotion_strict: bool = Field(
        default=False,
        env="JACKSPARROW_V43_METADATA_PROMOTION_STRICT",
        description=(
            "When True, reject v43 bundle load if metadata promotion audit finds "
            "meta_calibrator issues (zero short candidates, low meta_auc, missing calibrator)."
        ),
    )
    jacksparrow_v43_near_threshold_epsilon: float = Field(
        default=0.0,
        env="JACKSPARROW_V43_NEAR_THRESHOLD_EPSILON",
        ge=0.0,
        description=(
            "Optional near-threshold band for v43: treat expected_return within "
            "`threshold - epsilon` as a raw signal candidate. Keep 0.0 for strict gating."
        ),
    )
    jacksparrow_v43_max_position_pct: float = Field(
        default=0.20,
        env="JACKSPARROW_V43_MAX_POSITION_PCT",
        ge=0.01,
        le=1.0,
        description=(
            "Fraction of capital for v43 notional sizing before uncertainty scale. "
            "With leverage_assumption=3, effective notional exposure is up to "
            "max_position_pct * leverage (default 0.20 * 3 = 60% of capital per position)."
        ),
    )
    jacksparrow_v43_leverage_assumption: int = Field(
        default=3,
        env="JACKSPARROW_V43_LEVERAGE_ASSUMPTION",
        ge=1,
        description=(
            "Leverage for position sizing (not applied to label returns or Gate-5 edge math). "
            "Training stores this in runtime_cost_assumptions with "
            "round_trip_cost_includes_leverage=False. Effective notional per position: "
            "max_position_pct * leverage_assumption (default 60%)."
        ),
    )
    jacksparrow_v43_take_profit_pct: float = Field(
        default=0.01,
        env="JACKSPARROW_V43_TAKE_PROFIT_PCT",
        ge=0.0,
        description=(
            "TP fraction for v43 diagnostics when horizon alignment is off "
            "(profile uses ~1% for 30m / 2.5% for 10h when alignment on)."
        ),
    )
    jacksparrow_v43_maker_fee_rate: float = Field(
        default=0.0002,
        env="JACKSPARROW_V43_MAKER_FEE_RATE",
        ge=0.0,
        description=(
            "Per-leg maker fee for v43 round-trip cost estimate. "
            "Delta India BTC perp maker = 2 bps (0.0002)."
        ),
    )
    jacksparrow_v43_taker_fee_rate: float = Field(
        default=0.0010,
        env="JACKSPARROW_V43_TAKER_FEE_RATE",
        ge=0.0,
        description=(
            "Per-leg taker fee for market-order fallback cost estimate. "
            "Delta India BTC perp taker = 10 bps (0.0010)."
        ),
    )
    jacksparrow_v43_slippage_pct: float = Field(
        default=0.0003,
        env="JACKSPARROW_V43_SLIPPAGE_PCT",
        ge=0.0,
        description="Per-leg slippage fraction for v43 round-trip cost estimate.",
    )

    jacksparrow_v43_short_execution_enabled: bool = Field(
        default=True,
        env="JACKSPARROW_V43_SHORT_EXECUTION_ENABLED",
        description=(
            "When True, symmetric short entries fire when expected_return < -threshold "
            "(same gates/cost model as long). Default on for BTCUSD perpetual futures; "
            "set false only to run long-only experiments."
        ),
    )
    jacksparrow_v43_inference_stack: str = Field(
        default="meta_calibrator",
        env="JACKSPARROW_V43_INFERENCE_STACK",
        description=(
            "v43 ensemble inference path: meta_calibrator (production default) or "
            "regressor_mean (A/B ablation — base regressor mean only, skips meta+calibrator)."
        ),
    )
    jacksparrow_v43_regime_classifier_coercion_guard_enabled: bool = Field(
        default=True,
        env="JACKSPARROW_V43_REGIME_CLASSIFIER_COERCION_GUARD_ENABLED",
        description=(
            "When True, regime submodels that emit classifier-like probabilities on the "
            "return-target path fall back to the head ensemble instead of coercing P(class=1) "
            "to a small return proxy."
        ),
    )
    jacksparrow_v43_primary_signal_mode: str = Field(
        default="conditions",
        env="JACKSPARROW_V43_PRIMARY_SIGNAL_MODE",
        description=(
            "v43 signal priority: conditions (state heads), returns (forward-return heads), "
            "or hybrid (blend)."
        ),
    )
    jacksparrow_v43_state_heads_enabled: bool = Field(
        default=False,
        env="JACKSPARROW_V43_STATE_HEADS_ENABLED",
        description="When True, run state-intelligence heads at inference and apply policy gates.",
    )
    jacksparrow_v43_state_head_policy_enabled: bool = Field(
        default=True,
        env="JACKSPARROW_V43_STATE_HEAD_POLICY_ENABLED",
        description="When True, ml_and_thesis fusion enforces state-head probability minima.",
    )
    jacksparrow_v43_regime_min: float = Field(
        default=0.60,
        env="JACKSPARROW_V43_REGIME_MIN",
        description="Minimum p_regime_favorable for ML entry adoption.",
    )
    jacksparrow_v43_quality_min: float = Field(
        default=0.60,
        env="JACKSPARROW_V43_QUALITY_MIN",
        description="Minimum p_setup_quality for ML entry adoption.",
    )
    jacksparrow_v43_vol_min: float = Field(
        default=0.50,
        env="JACKSPARROW_V43_VOL_MIN",
        description="Below this p_vol_expansion, reduce size or hold (policy layer).",
    )
    jacksparrow_v43_uncertainty_max: float = Field(
        default=0.02,
        env="JACKSPARROW_V43_UNCERTAINTY_MAX",
        description="Force hold when uncertainty_score exceeds this threshold.",
    )
    signal_recovery_telemetry_enabled: bool = Field(
        default=True,
        env="SIGNAL_RECOVERY_TELEMETRY_ENABLED",
        description=(
            "Append per-cycle decision telemetry NDJSON for signal-recovery KPI scripts."
        ),
    )
    signal_recovery_telemetry_subpath: str = Field(
        default="signal_recovery/decision_telemetry.ndjson",
        env="SIGNAL_RECOVERY_TELEMETRY_SUBPATH",
        description="Relative to LOGS_ROOT; used by baseline/ablation tooling.",
    )

    trade_outcomes_writes_enabled: bool = Field(
        default=True,
        env="TRADE_OUTCOMES_WRITES_ENABLED",
        description="When True, persist closed positions to trade_outcomes (PostgreSQL).",
    )
    threshold_adapter_enabled: bool = Field(
        default=True,
        env="THRESHOLD_ADAPTER_ENABLED",
        description="When True, periodically adjust Redis-backed learning thresholds from trade_outcomes.",
    )
    threshold_adapter_interval_seconds: int = Field(
        default=3600,
        env="THRESHOLD_ADAPTER_INTERVAL_SECONDS",
        ge=60,
        description="How often to run ThresholdAdapter (seconds).",
    )
    
    # Agent Configuration
    agent_start_mode: str = Field(
        default="MONITORING",
        env="AGENT_START_MODE",
        description="Agent start mode"
    )
    agent_symbol: str = Field(
        default="BTCUSD",
        env="AGENT_SYMBOL",
        description="Default trading symbol"
    )
    agent_interval: str = Field(
        default="15m",
        env="AGENT_INTERVAL",
        description="Default analysis interval"
    )

    # Perpetual futures contract configuration
    product_id: int = Field(27, env="PRODUCT_ID")
    symbol: str = Field("BTCUSD", env="SYMBOL")
    contract_type: str = Field("perpetual_futures", env="CONTRACT_TYPE")
    contract_value_btc: float = Field(0.001, env="CONTRACT_VALUE_BTC")
    tick_size: float = Field(0.50, env="TICK_SIZE")
    use_live_product_specs: bool = Field(
        True,
        env="USE_LIVE_PRODUCT_SPECS",
        description="Fetch contract_value and tick_size from Delta public /v2/products/{symbol}",
    )
    product_specs_cache_ttl_seconds: int = Field(
        3600,
        env="PRODUCT_SPECS_CACHE_TTL_SECONDS",
        description="Redis TTL for cached product specs",
    )
    delta_public_http_timeout_seconds: float = Field(
        15.0,
        env="DELTA_PUBLIC_HTTP_TIMEOUT_SECONDS",
        description="Timeout for unauthenticated Delta public API calls",
    )
    taker_fee_rate: float = Field(0.0005, env="TAKER_FEE_RATE")
    maker_fee_rate: float = Field(0.0002, env="MAKER_FEE_RATE")
    funding_interval_hours: int = Field(8, env="FUNDING_INTERVAL_HOURS")
    funding_interest_rate: float = Field(0.0001, env="FUNDING_INTEREST_RATE")

    # Leverage (set manually in exchange UI)
    default_leverage: int = Field(5, env="DEFAULT_LEVERAGE")
    max_leverage: int = Field(20, env="MAX_LEVERAGE")
    min_leverage: int = Field(1, env="MIN_LEVERAGE")

    # Order execution limits
    slippage_bps: float = Field(5.0, env="SLIPPAGE_BPS")
    min_lot_size: int = Field(1, env="MIN_LOT_SIZE")
    max_lots_per_order: int = Field(100, env="MAX_LOTS_PER_ORDER")
    fixed_lot_size: int = Field(
        default=1,
        env="FIXED_LOT_SIZE",
        description="Fixed lot size used for each entry when fixed sizing is enabled",
    )
    enforce_fixed_lot_size: bool = Field(
        default=True,
        env="ENFORCE_FIXED_LOT_SIZE",
        description="When true, always trade the fixed lot size for new entries",
    )
    use_notional_lot_sizing: bool = Field(
        default=False,
        env="USE_NOTIONAL_LOT_SIZING",
        description="When true, size lots from USD notional (floor) instead of fixed_lot_size",
    )
    isolated_margin_leverage: int = Field(
        default=5,
        env="ISOLATED_MARGIN_LEVERAGE",
        description="Leverage assumption for isolated margin checks",
    )
    usdinr_fallback_rate: float = Field(
        default=83.0,
        env="USDINR_FALLBACK_RATE",
        description="Fallback USDINR conversion rate when live FX is unavailable",
    )
    maintenance_fraction_of_initial: float = Field(
        0.5,
        env="MAINTENANCE_FRACTION_OF_INITIAL",
        ge=0.0,
        le=1.0,
        description="Paper liquidation when equity < initial_margin * this fraction (isolated)",
    )
    fee_accounting_mode: str = Field(
        "split",
        env="FEE_ACCOUNTING_MODE",
        description="split: entry fee at open, exit fee at close; round_trip: fees in net at close only",
    )

    active_timeframes: str = Field(
        default="1m,5m,15m,30m,1h,2h",
        env="ACTIVE_TIMEFRAMES",
        description="Comma-separated list of active trading timeframes (first = primary candle interval for ML triggers)"
    )
    
    # Trading runtime (Delta testnet only — real orders, no local simulation)
    exchange_backend: str = Field(
        default="delta_live",
        env="EXCHANGE_BACKEND",
        description="Exchange adapter (only delta_live is supported)",
    )
    delta_env: str = Field(
        default="india_testnet",
        env="DELTA_ENV",
        description="Delta environment label (only india_testnet is supported)",
    )

    # Risk Management
    max_position_size: float = Field(
        default=0.1,
        env="MAX_POSITION_SIZE",
        description="Maximum position size as fraction of portfolio"
    )
    max_portfolio_heat: float = Field(
        default=0.3,
        env="MAX_PORTFOLIO_HEAT",
        description="Maximum portfolio heat"
    )
    stop_loss_percentage: float = Field(
        default=0.01,
        env="STOP_LOSS_PERCENTAGE",
        description="Stop loss as fraction of price (e.g. 0.01 = 1%; default for medium-term strategy)"
    )
    take_profit_percentage: float = Field(
        default=0.015,
        env="TAKE_PROFIT_PERCENTAGE",
        description="Take profit as fraction of price (e.g. 0.015 = 1.5%; default for medium-term strategy)"
    )
    use_atr_scaled_sl_tp: bool = Field(
        default=True,
        env="USE_ATR_SCALED_SL_TP",
        description="Use ATR-scaled stop loss / take profit when available"
    )
    atr_sl_distance_mult: float = Field(
        default=1.0,
        env="ATR_SL_DISTANCE_MULT",
        description="ATR multiplier for stop loss distance"
    )
    atr_tp_distance_mult: float = Field(
        default=1.5,
        env="ATR_TP_DISTANCE_MULT",
        description="ATR multiplier for take profit distance"
    )
    entry_min_atr_pct_of_price: float = Field(
        default=0.003,
        env="ENTRY_MIN_ATR_PCT_OF_PRICE",
        description="Minimum ATR% of price required to authorize new entry (market regime filter)"
    )
    min_risk_reward_ratio: float = Field(
        default=1.2,
        env="MIN_RISK_REWARD_RATIO",
        description="Minimum risk/reward ratio to allow a trade"
    )
    enforce_ema200_trend_filter: bool = Field(
        default=True,
        env="ENFORCE_EMA200_TREND_FILTER",
        description="When True, require long trades above EMA200 and short trades below EMA200."
    )
    max_signal_age_seconds: int = Field(
        default=45,
        env="MAX_SIGNAL_AGE_SECONDS",
        description="Reject signals older than this (seconds)"
    )
    trailing_stop_percentage: float = Field(
        default=0.015,
        env="TRAILING_STOP_PERCENTAGE",
        description="Trailing stop percentage for longs/shorts"
    )
    max_position_hold_hours: int = Field(
        default=24,
        env="MAX_POSITION_HOLD_HOURS",
        description="Force-close positions after this many hours"
    )
    websocket_sl_tp_enabled: bool = Field(
        default=True,
        env="WEBSOCKET_SL_TP_ENABLED",
        description="Use WebSocket ticks for SL/TP checks when positions open"
    )
    partial_fill_timeout_seconds: float = Field(
        default=10.0,
        env="PARTIAL_FILL_TIMEOUT_SECONDS",
        description="Seconds to wait for remainder fill before closing partial position",
    )
    position_reconcile_stale_seconds: float = Field(
        default=30.0,
        env="POSITION_RECONCILE_STALE_SECONDS",
        description="Max age of last reconcile before blocking new entries",
    )
    mtf_confirmation_enabled: bool = Field(
        default=False,
        env="MTF_CONFIRMATION_ENABLED",
        description="Require higher-timeframe trend confirmation before entry"
    )
    mtf_decision_engine_enabled: bool = Field(
        default=True,
        env="MTF_DECISION_ENGINE_ENABLED",
        description=(
            "Use multi-timeframe model rules (trend TF + entry TF ± optional filter) "
            "instead of averaging all models into one consensus"
        ),
    )
    mtf_signal_architecture: str = Field(
        default="standard",
        env="MTF_SIGNAL_ARCHITECTURE",
        description=(
            "'standard' = higher-TF trend gates lower-TF entry (MTF_TREND/ENTRY_TIMEFRAME). "
            "'short_tf_primary' = primary TF (default 5m) prob_long - prob_short drives trades; "
            "context TF (default 15m) never blocks — used only for position sizing in trading handler."
        ),
    )
    mtf_primary_signal_timeframe: str = Field(
        default="5m",
        env="MTF_PRIMARY_SIGNAL_TIMEFRAME",
        description="Primary alpha TF when mtf_signal_architecture=short_tf_primary",
    )
    mtf_primary_signal_fallback_timeframes: str = Field(
        default="15m,30m",
        env="MTF_PRIMARY_SIGNAL_FALLBACK_TIMEFRAMES",
        description="Comma-separated fallbacks if primary signal TF model is missing",
    )
    mtf_context_timeframe: str = Field(
        default="15m",
        env="MTF_CONTEXT_TIMEFRAME",
        description="Weak context TF for alignment sizing only (short_tf_primary mode)",
    )
    mtf_context_fallback_timeframes: str = Field(
        default="30m,1h",
        env="MTF_CONTEXT_FALLBACK_TIMEFRAMES",
        description="Fallbacks if context TF model is missing",
    )
    mtf_strict_trend_entry_alignment: bool = Field(
        default=True,
        env="MTF_STRICT_TREND_ENTRY_ALIGNMENT",
        description="Require entry TF direction matches trend TF direction for long/short execution",
    )
    mtf_primary_dead_zone: float = Field(
        default=0.05,
        env="MTF_PRIMARY_DEAD_ZONE",
        description="If abs(buy-sell) on primary TF is below this, HOLD (short_tf_primary)",
    )
    mtf_primary_edge_long: float = Field(
        default=0.08,
        env="MTF_PRIMARY_EDGE_LONG",
        description="Minimum (buy-sell) on primary TF for LONG (short_tf_primary)",
    )
    mtf_primary_edge_short: float = Field(
        default=0.08,
        env="MTF_PRIMARY_EDGE_SHORT",
        description="Minimum (sell-buy) on primary TF for SHORT (short_tf_primary)",
    )
    mtf_primary_strong_long_min_prob: float = Field(
        default=0.55,
        env="MTF_PRIMARY_STRONG_LONG_MIN_PROB",
        description="Primary-TF buy prob floor for STRONG_BUY (short_tf_primary)",
    )
    mtf_primary_strong_short_min_prob: float = Field(
        default=0.58,
        env="MTF_PRIMARY_STRONG_SHORT_MIN_PROB",
        description="Primary-TF sell prob floor for STRONG_SELL (short_tf_primary)",
    )
    mtf_context_agree_edge: float = Field(
        default=0.02,
        env="MTF_CONTEXT_AGREE_EDGE",
        description="Signed prob edge on context TF to count as aligned / misaligned for sizing",
    )
    mtf_context_aligned_size_multiplier: float = Field(
        default=1.15,
        env="MTF_CONTEXT_ALIGNED_SIZE_MULTIPLIER",
        description="Scale proposed size when context TF agrees with signal (short_tf_primary)",
    )
    mtf_context_misaligned_size_multiplier: float = Field(
        default=0.75,
        env="MTF_CONTEXT_MISALIGNED_SIZE_MULTIPLIER",
        description="Scale proposed size when context TF disagrees (short_tf_primary)",
    )
    mtf_trend_timeframe: str = Field(
        default="15m",
        env="MTF_TREND_TIMEFRAME",
        description="Primary timeframe for trend direction from model outputs",
    )
    mtf_entry_timeframe: str = Field(
        default="5m",
        env="MTF_ENTRY_TIMEFRAME",
        description="Primary timeframe for entry confirmation",
    )
    mtf_filter_timeframe: str = Field(
        default="none",
        env="MTF_FILTER_TIMEFRAME",
        description="Optional shorter TF filter; set empty, 'none', or '-' to disable",
    )
    mtf_trend_fallback_timeframes: str = Field(
        default="30m,1h,2h,4h",
        env="MTF_TREND_FALLBACK_TIMEFRAMES",
        description="Comma-separated fallbacks if primary trend TF model is missing",
    )
    mtf_entry_fallback_timeframes: str = Field(
        default="15m,30m,1h",
        env="MTF_ENTRY_FALLBACK_TIMEFRAMES",
        description="Comma-separated fallbacks if primary entry TF model is missing",
    )
    mtf_allow_partial_timeframe_fallback: bool = Field(
        default=True,
        env="MTF_ALLOW_PARTIAL_TIMEFRAME_FALLBACK",
        description=(
            "Allow best-available timeframe selection when configured MTF trend/entry "
            "timeframes are unavailable."
        ),
    )
    mtf_entry_min_confidence: float = Field(
        default=0.52,
        env="MTF_ENTRY_MIN_CONFIDENCE",
        description="Minimum entry-TF confidence to confirm a trade with trend",
    )
    mtf_trend_signal_threshold: float = Field(
        default=0.1,
        env="MTF_TREND_SIGNAL_THRESHOLD",
        description="Absolute entry_signal on trend TF to classify bull/bear (not neutral)",
    )
    mtf_entry_signal_threshold: float = Field(
        default=0.15,
        env="MTF_ENTRY_SIGNAL_THRESHOLD",
        description="Absolute entry_signal on entry TF to count as confirming BUY/SELL",
    )
    mtf_use_entry_proba_gating: bool = Field(
        default=True,
        env="MTF_USE_ENTRY_PROBA_GATING",
        description="Use entry_proba buy/sell thresholds for MTF gating when available",
    )
    mtf_trend_min_buy_prob: float = Field(
        default=0.50,
        env="MTF_TREND_MIN_BUY_PROB",
        description="Minimum trend-TF BUY probability for bullish MTF bias",
    )
    mtf_trend_min_sell_prob: float = Field(
        default=0.50,
        env="MTF_TREND_MIN_SELL_PROB",
        description="Minimum trend-TF SELL probability for bearish MTF bias",
    )
    mtf_entry_min_buy_prob: float = Field(
        default=0.50,
        env="MTF_ENTRY_MIN_BUY_PROB",
        description="Minimum entry-TF BUY probability to confirm BUY decision",
    )
    mtf_entry_min_sell_prob: float = Field(
        default=0.50,
        env="MTF_ENTRY_MIN_SELL_PROB",
        description="Minimum entry-TF SELL probability to confirm SELL decision",
    )
    mtf_strong_min_buy_prob: float = Field(
        default=0.60,
        env="MTF_STRONG_MIN_BUY_PROB",
        description="Minimum BUY probability/confidence to emit STRONG_BUY",
    )
    mtf_strong_min_sell_prob: float = Field(
        default=0.60,
        env="MTF_STRONG_MIN_SELL_PROB",
        description="Minimum SELL probability/confidence to emit STRONG_SELL",
    )
    use_ml_exit_model: bool = Field(
        default=False,
        env="USE_ML_EXIT_MODEL",
        description="If False, skip exit classifier inference; rely on TP/SL/trailing/time exits",
    )
    feature_filter_enabled: bool = Field(
        default=True,
        env="FEATURE_FILTER_ENABLED",
        description="Apply lightweight feature gates (e.g. BB upper) before entries",
    )
    block_buy_near_bb_upper_pct: float = Field(
        default=0.92,
        env="BLOCK_BUY_NEAR_BB_UPPER_PCT",
        description="Block BUY when bb_position is above this (near upper band / resistance)",
    )
    sr_strength_filter_enabled: bool = Field(
        default=True,
        env="SR_STRENGTH_FILTER_ENABLED",
        description="Apply SR support/resistance strength gates before entries",
    )
    block_buy_min_sr_resistance_strength: float = Field(
        default=0.7,
        env="BLOCK_BUY_MIN_SR_RESISTANCE_STRENGTH",
        description="Block BUY when SR resistance strength exceeds this threshold",
    )
    block_sell_min_sr_support_strength: float = Field(
        default=0.7,
        env="BLOCK_SELL_MIN_SR_SUPPORT_STRENGTH",
        description="Block SELL when SR support strength exceeds this threshold",
    )
    entry_signal_filter_enabled: bool = Field(
        default=True,
        env="ENTRY_SIGNAL_FILTER_ENABLED",
        description="Apply EntrySignalFilter (max trades/hour, breakout score) after SR/BB gates",
    )
    max_trades_per_hour: int = Field(
        default=0,
        env="MAX_TRADES_PER_HOUR",
        description="Cap approved entries per symbol per rolling hour (0 = unlimited)",
    )
    entry_min_breakout_score: float = Field(
        default=0.0,
        env="ENTRY_MIN_BREAKOUT_SCORE",
        description="Block BUY when bo_breakout_score is below this (0 = disabled)",
    )
    use_atr_scaled_sl_tp: bool = Field(
        default=False,
        env="USE_ATR_SCALED_SL_TP",
        description=(
            "When True, scale SL/TP distances using max(config pct, atr_14 * multiplier). "
            "Requires atr_14 in market_context features."
        ),
    )
    atr_sl_distance_mult: float = Field(
        default=1.0,
        env="ATR_SL_DISTANCE_MULT",
        description="Stop distance lower bound: atr_14 * this factor (when ATR scaling on)",
    )
    atr_tp_distance_mult: float = Field(
        default=1.5,
        env="ATR_TP_DISTANCE_MULT",
        description="Take-profit distance lower bound: atr_14 * this factor (when ATR scaling on)",
    )
    trailing_stop_activation_profit_pct: float = Field(
        default=0.0,
        env="TRAILING_STOP_ACTIVATION_PROFIT_PCT",
        description=(
            "Only ratchet trailing stop after unrealized profit exceeds this fraction (0 = always trail when in profit)"
        ),
    )
    mtf_min_confidence_gap: float = Field(
        default=0.05,
        env="MTF_MIN_CONFIDENCE_GAP",
        description=(
            "Minimum |buy-sell| entry probability gap on entry TF when using proba gating; "
            "0 disables uncertainty filter"
        ),
    )
    entry_long_short_min_gap: float = Field(
        default=0.0,
        env="ENTRY_LONG_SHORT_MIN_GAP",
        description=(
            "In v4 ensemble with binary long/short heads: if |buy_prob-sell_prob| is below this, "
            "force neutral entry signal and reduce confidence. 0 disables (use MTF_MIN_CONFIDENCE_GAP when MTF is on)."
        ),
    )
    mtf_trend_use_prob_diff: bool = Field(
        default=True,
        env="MTF_TREND_USE_PROB_DIFF",
        description=(
            "Classify trend TF direction from (buy-sell) vs (sell-buy) using mtf_trend_prob_diff_edge "
            "instead of absolute buy/sell probability floors"
        ),
    )
    mtf_trend_prob_diff_edge: float = Field(
        default=0.05,
        env="MTF_TREND_PROB_DIFF_EDGE",
        description="Minimum signed prob gap on trend TF to call bull or bear bias",
    )
    mtf_entry_use_prob_diff: bool = Field(
        default=True,
        env="MTF_ENTRY_USE_PROB_DIFF",
        description=(
            "Require signed (entry_buy - entry_sell) or (entry_sell - entry_buy) to exceed "
            "mtf_entry_prob_diff_edge instead of absolute entry buy/sell floors"
        ),
    )
    mtf_entry_prob_diff_edge: float = Field(
        default=0.08,
        env="MTF_ENTRY_PROB_DIFF_EDGE",
        description="Minimum signed long/short gap on entry TF to confirm a trade with trend",
    )
    mtf_strong_entry_prob_diff: float = Field(
        default=0.15,
        env="MTF_STRONG_ENTRY_PROB_DIFF",
        description="Signed entry prob gap required for STRONG_BUY / STRONG_SELL when using prob-diff mode",
    )
    mtf_entry_min_max_prob_floor: float = Field(
        default=0.0,
        env="MTF_ENTRY_MIN_MAX_PROB_FLOOR",
        description=(
            "When > 0 with prob-diff entry gating, also require max(buy,sell) >= this (suppresses "
            "tiny-probability edges). 0 disables."
        ),
    )
    mtf_entry_strength_percentile_enabled: bool = Field(
        default=False,
        env="MTF_ENTRY_STRENGTH_PERCENTILE_ENABLED",
        description=(
            "When True, block BUY/SELL unless |buy-sell| on entry TF is at or above the rolling "
            "percentile of prior bars (selective scalping)."
        ),
    )
    mtf_entry_strength_percentile: int = Field(
        default=80,
        env="MTF_ENTRY_STRENGTH_PERCENTILE",
        description="Percentile of prior |buy-sell| strengths that current strength must meet or exceed",
    )
    mtf_entry_strength_percentile_min_samples: int = Field(
        default=30,
        env="MTF_ENTRY_STRENGTH_PERCENTILE_MIN_SAMPLES",
        description="Minimum history length before percentile gate applies",
    )
    entry_min_volatility_for_trade: float = Field(
        default=0.0,
        env="ENTRY_MIN_VOLATILITY_FOR_TRADE",
        description=(
            "When > 0, reject entries if features.volatility is below this (same units as feature pipeline). "
            "0 disables."
        ),
    )
    entry_min_atr_pct_of_price: float = Field(
        default=0.0,
        env="ENTRY_MIN_ATR_PCT_OF_PRICE",
        description=(
            "When > 0, reject entries if atr_14 / entry_price is below this fraction (dead market filter). "
            "0 disables."
        ),
    )
    trade_signal_debounce_seconds: int = Field(
        default=10,
        env="TRADE_SIGNAL_DEBOUNCE_SECONDS",
        description="Debounce: block duplicate (symbol, side) approvals within this many seconds",
    )
    min_risk_reward_ratio: float = Field(
        default=1.2,
        env="MIN_RISK_REWARD_RATIO",
        description="Minimum reward/risk ratio required for entry (TP distance / SL distance).",
    )
    adx_ranging_threshold: float = Field(
        default=15.0,
        env="ADX_RANGING_THRESHOLD",
        description="Reject mild BUY/SELL signals when adx_14 is below this threshold (trend too weak).",
    )
    model_disagreement_threshold: float = Field(
        default=0.6,
        env="MODEL_DISAGREEMENT_THRESHOLD",
        description="Max inter-model prediction stdev before dampening consensus"
    )
    half_spread_pct: float = Field(
        default=0.0002,
        env="HALF_SPREAD_PCT",
        description="Paper trading: simulated half bid-ask spread (0.02%)"
    )
    paper_ticker_max_age_seconds: float = Field(
        default=10.0,
        env="PAPER_TICKER_MAX_AGE_SECONDS",
        description="Maximum ticker age for paper-trade fills before stale handling"
    )
    paper_fill_price_fallback_enabled: bool = Field(
        default=True,
        env="PAPER_FILL_PRICE_FALLBACK_ENABLED",
        description="Allow fallback to latest context market price when ticker is stale"
    )
    min_monitor_interval_seconds: float = Field(
        default=2.0,
        env="MIN_MONITOR_INTERVAL_SECONDS",
        description="Position monitor interval when positions are open"
    )
    position_monitor_interval_seconds: float = Field(
        default=2.0,
        env="POSITION_MONITOR_INTERVAL_SECONDS",
        description="Position monitor interval when no positions"
    )
    max_daily_loss: float = Field(
        default=0.05,
        env="MAX_DAILY_LOSS",
        description="Maximum daily loss as fraction of portfolio"
    )
    max_drawdown: float = Field(
        default=0.15,
        env="MAX_DRAWDOWN",
        description="Maximum drawdown as fraction of portfolio"
    )
    max_consecutive_losses: int = Field(
        default=5,
        env="MAX_CONSECUTIVE_LOSSES",
        description="Maximum consecutive losses before stopping"
    )
    min_time_between_trades: int = Field(
        default=300,
        env="MIN_TIME_BETWEEN_TRADES",
        description="Minimum time between trades in seconds"
    )
    
    # Logging
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level"
    )
    agent_log_level: Optional[str] = Field(
        default=None,
        env="AGENT_LOG_LEVEL",
        description="Agent-specific logging level (overrides LOG_LEVEL)"
    )
    log_forwarding_enabled: bool = Field(
        default=False,
        env="LOG_FORWARDING_ENABLED",
        description="Enable log forwarding"
    )
    log_forwarding_endpoint: Optional[str] = Field(
        default=None,
        env="LOG_FORWARDING_ENDPOINT",
        description="Log forwarding endpoint URL"
    )
    log_include_stacktrace: bool = Field(
        default=False,
        env="LOG_INCLUDE_STACKTRACE",
        description="Include stack traces in logs"
    )

    # Communication Logging
    enable_communication_logging: bool = Field(
        default=True,
        env="ENABLE_COMMUNICATION_LOGGING",
        description="Enable detailed communication logging between services"
    )
    log_websocket_payloads: bool = Field(
        default=True,
        env="LOG_WEBSOCKET_PAYLOADS",
        description="Log WebSocket message payloads"
    )
    max_log_payload_size: int = Field(
        default=10240,  # 10KB
        env="MAX_LOG_PAYLOAD_SIZE",
        description="Maximum size of payloads to log (bytes)"
    )
    communication_sensitive_fields: List[str] = Field(
        default=["password", "token", "api_key", "secret", "private_key"],
        env="COMMUNICATION_SENSITIVE_FIELDS",
        description="Fields to sanitize in communication logs"
    )
    signal_audit_md_enabled: bool = Field(
        default=True,
        env="SIGNAL_AUDIT_MD_ENABLED",
        description="Append AI signals and trade actions to realtime markdown under LOGS_ROOT",
    )
    signal_audit_md_subpath: str = Field(
        default="signal_audit/live_audit.md",
        env="SIGNAL_AUDIT_MD_SUBPATH",
        description="Path under LOGS_ROOT for the live markdown audit file",
    )
    
    # Feature Server
    feature_server_port: int = Field(
        default=8001,
        env="FEATURE_SERVER_PORT",
        description="Feature server port"
    )
    feature_server_host: str = Field(
        default="0.0.0.0",
        env="FEATURE_SERVER_HOST",
        description="Feature server host address"
    )
    
    # Agent Communication
    agent_command_queue: str = Field(
        default="agent_commands",
        env="AGENT_COMMAND_QUEUE",
        description="Redis queue for agent commands"
    )
    agent_response_queue: str = Field(
        default="agent_responses",
        env="AGENT_RESPONSE_QUEUE",
        description="Redis queue for agent responses"
    )
    
    # WebSocket Configuration
    agent_websocket_host: str = Field(
        default="0.0.0.0",
        env="AGENT_WS_HOST",
        description="Host for agent WebSocket server"
    )
    agent_websocket_port: int = Field(
        default=8003,
        env="AGENT_WS_PORT",
        description="Port for agent WebSocket server (8002 is reserved for the feature HTTP API)",
    )
    backend_websocket_url: str = Field(
        default="ws://localhost:8000/ws/agent",
        alias="BACKEND_WS_URL",
        description="Backend WebSocket URL for agent event client"
    )
    
    # Trading Session Defaults
    initial_balance: float = Field(
        default=20000.0,
        env="INITIAL_BALANCE",
        description="Initial trading balance"
    )
    trading_mode: str = Field(
        default="testnet",
        env="TRADING_MODE",
        description="Trading mode (testnet only — real orders on Delta testnet)",
    )
    delta_environment: str = Field(
        default="testnet",
        env="DELTA_ENVIRONMENT",
        description="Exchange environment label exposed to health/API (testnet)",
    )
    trading_symbol: str = Field(
        default="BTCUSD",
        env="TRADING_SYMBOL",
        description="Trading symbol"
    )
    min_confidence_threshold: float = Field(
        default=0.55,
        env="MIN_CONFIDENCE_THRESHOLD",
        description="Minimum confidence threshold for trades"
    )
    paper_trade_validation_mode: bool = Field(
        default=False,
        env="PAPER_TRADE_VALIDATION_MODE",
        description=(
            "When true, use relaxed confidence gate for paper-trading "
            "pipeline validation only."
        ),
    )
    paper_trade_validation_min_confidence: float = Field(
        default=0.45,
        env="PAPER_TRADE_VALIDATION_MIN_CONFIDENCE",
        description=(
            "Temporary minimum confidence while PAPER_TRADE_VALIDATION_MODE is enabled."
        ),
    )
    ai_signal_minimal_entry_gates: bool = Field(
        default=False,
        env="AI_SIGNAL_MINIMAL_ENTRY_GATES",
        description=(
            "When True, trading_handler approves from DecisionReady using only payload "
            "AI confidence ≥ ai_signal_min_entry_confidence plus price, margin, min lots, and "
            "open-position rules; skips v15 entry gate, stale-signal, feature/MTF/SR filters, "
            "profit/R:R gate, Redis-blended confidence floor path, and "
            "v15 hourly/daily caps. RiskManager.validate_trade still runs for every entry. "
            "Higher trade frequency — use with care."
        ),
    )
    ai_signal_min_entry_confidence: float = Field(
        default=0.70,
        env="AI_SIGNAL_MIN_ENTRY_CONFIDENCE",
        ge=0.0,
        le=1.0,
        description="Minimum payload confidence when AI_SIGNAL_MINIMAL_ENTRY_GATES is True.",
    )
    agent_policy_force_hold: bool = Field(
        default=False,
        env="AGENT_POLICY_FORCE_HOLD",
        description=(
            "When True, AgentPolicyEngine vetoes all autonomous entries (DecisionReady stays HOLD). "
            "ML evidence is still emitted on EvidenceReady for audit/UI."
        ),
    )
    agent_policy_mode: str = Field(
        default="ml_and_thesis",
        env="AGENT_POLICY_MODE",
        description=(
            "Signal fusion: ml_only | thesis_only | ml_or_thesis | ml_and_thesis | thesis_veto_ml"
        ),
    )
    agent_trade_score_min: float = Field(
        default=70.0,
        env="AGENT_TRADE_SCORE_MIN",
        ge=0.0,
        le=100.0,
        description="Minimum confluence score (0-100) before policy may emit entry.",
    )
    require_strategy_ml_agreement: bool = Field(
        default=True,
        env="REQUIRE_STRATEGY_ML_AGREEMENT",
        description="When True and policy mode is ml_and_thesis, execution requires thesis+ML agreement.",
    )
    agent_policy_adopt_gated_ml_when_thesis_neutral: bool = Field(
        default=True,
        env="AGENT_POLICY_ADOPT_GATED_ML_WHEN_THESIS_NEUTRAL",
        description=(
            "In ml_and_thesis mode, adopt gated ML entries (final_long/final_short) when thesis "
            "is HOLD and not in crisis/veto/conflict. Enables perp shorts without a parallel thesis rule."
        ),
    )
    agent_introspection_enabled: bool = Field(
        default=True,
        env="AGENT_INTROSPECTION_ENABLED",
        description="Emit deterministic agent_introspection on DecisionReadyEvent (read-only).",
    )
    agent_memory_outcome_backfill_enabled: bool = Field(
        default=True,
        env="AGENT_MEMORY_OUTCOME_BACKFILL_ENABLED",
        description="Backfill vector memory with trade outcomes on position close.",
    )
    agent_reflection_advisory_enabled: bool = Field(
        default=True,
        env="AGENT_REFLECTION_ADVISORY_ENABLED",
        description="Emit advisory reflection_snapshot on position close (no policy mutation).",
    )
    agent_reflection_policy_feedback_enabled: bool = Field(
        default=True,
        env="AGENT_REFLECTION_POLICY_FEEDBACK_ENABLED",
        description=(
            "When True, reflection quality/buckets feed bounded confidence calibration "
            "for future decisions. Roll out behind this flag."
        ),
    )
    reflection_calibration_step_size: float = Field(
        default=0.02,
        env="REFLECTION_CALIBRATION_STEP_SIZE",
        ge=0.001,
        le=0.1,
        description="Max per-trade adjustment to global reflection calibration factor.",
    )
    reflection_calibration_min_samples: int = Field(
        default=5,
        env="REFLECTION_CALIBRATION_MIN_SAMPLES",
        ge=1,
        le=100,
        description="Minimum reflection samples before calibration affects decisions.",
    )
    agent_vector_store_backend: str = Field(
        default="memory",
        env="AGENT_VECTOR_STORE_BACKEND",
        description="Vector memory backend: memory (in-process) or qdrant.",
    )
    agent_vector_store_qdrant_collection: str = Field(
        default="decision_contexts",
        env="AGENT_VECTOR_STORE_QDRANT_COLLECTION",
        description="Qdrant collection name for decision context vectors.",
    )
    portfolio_intelligence_enabled: bool = Field(
        default=False,
        env="PORTFOLIO_INTELLIGENCE_ENABLED",
        description="Enable portfolio heat/concentration/correlation guard before execution.",
    )
    portfolio_intelligence_shadow_mode: bool = Field(
        default=True,
        env="PORTFOLIO_INTELLIGENCE_SHADOW_MODE",
        description=(
            "When True (default), compute portfolio guard and log but do not mutate policy verdict."
        ),
    )
    portfolio_intelligence_reduce_enabled: bool = Field(
        default=False,
        env="PORTFOLIO_INTELLIGENCE_REDUCE_ENABLED",
        description="When shadow is False, allow guard to reduce position_size_fraction.",
    )
    portfolio_intelligence_block_enabled: bool = Field(
        default=False,
        env="PORTFOLIO_INTELLIGENCE_BLOCK_ENABLED",
        description="When shadow is False, allow guard to block entries (HOLD).",
    )
    portfolio_max_heat_ratio: float = Field(
        default=0.85,
        env="PORTFOLIO_MAX_HEAT_RATIO",
        ge=0.1,
        le=3.0,
        description="Max (open+proposed notional) / equity before block.",
    )
    portfolio_max_same_side_concentration: float = Field(
        default=0.70,
        env="PORTFOLIO_MAX_SAME_SIDE_CONCENTRATION",
        ge=0.5,
        le=1.0,
        description="Max fraction of directional notional on proposed side after entry.",
    )
    portfolio_max_correlation_group_fraction: float = Field(
        default=0.55,
        env="PORTFOLIO_MAX_CORRELATION_GROUP_FRACTION",
        ge=0.1,
        le=1.0,
        description="Max group notional as fraction of equity.",
    )
    portfolio_near_limit_size_factor: float = Field(
        default=0.50,
        env="PORTFOLIO_NEAR_LIMIT_SIZE_FACTOR",
        ge=0.1,
        le=1.0,
        description="Size multiplier when near heat cap (reduce_size action).",
    )
    portfolio_near_limit_band: float = Field(
        default=0.08,
        env="PORTFOLIO_NEAR_LIMIT_BAND",
        ge=0.0,
        le=0.5,
        description="Heat ratio band below cap that triggers reduce_size.",
    )
    portfolio_correlation_groups_json: str = Field(
        default='{"crypto_major":["BTCUSD","ETHUSD","BTCUSDT","ETHUSDT"]}',
        env="PORTFOLIO_CORRELATION_GROUPS_JSON",
        description="JSON map of correlation group name to symbol list.",
    )
    agent_structure_chop_atr_pct_max: float = Field(
        default=0.003,
        env="AGENT_STRUCTURE_CHOP_ATR_PCT_MAX",
    )
    agent_structure_low_vol_regime_max: float = Field(
        default=0.85,
        env="AGENT_STRUCTURE_LOW_VOL_REGIME_MAX",
    )
    agent_structure_trending_adx_min: float = Field(
        default=22.0,
        env="AGENT_STRUCTURE_TRENDING_ADX_MIN",
    )
    agent_thesis_chop_veto_enabled: bool = Field(
        default=True,
        env="AGENT_THESIS_CHOP_VETO_ENABLED",
    )
    agent_thesis_min_atr_pct: float = Field(
        default=0.0,
        env="AGENT_THESIS_MIN_ATR_PCT",
    )
    agent_thesis_max_spread_bps: float = Field(
        default=50.0,
        env="AGENT_THESIS_MAX_SPREAD_BPS",
    )
    agent_thesis_funding_pressure_max: float = Field(
        default=2.0,
        env="AGENT_THESIS_FUNDING_PRESSURE_MAX",
    )
    agent_daily_drawdown_halt_pct: float = Field(
        default=4.0,
        env="AGENT_DAILY_DRAWDOWN_HALT_PCT",
        description="Halt new entries when daily drawdown exceeds this percent.",
    )
    agent_thesis_breakout_enabled: bool = Field(
        default=True,
        env="AGENT_THESIS_BREAKOUT_ENABLED",
    )
    agent_thesis_trend_enabled: bool = Field(
        default=True,
        env="AGENT_THESIS_TREND_ENABLED",
    )
    agent_thesis_crisis_veto: bool = Field(
        default=True,
        env="AGENT_THESIS_CRISIS_VETO",
    )
    agent_thesis_mean_reversion_enabled: bool = Field(
        default=False,
        env="AGENT_THESIS_MEAN_REVERSION_ENABLED",
    )
    agent_thesis_squeeze_veto_threshold: float = Field(
        default=0.5,
        env="AGENT_THESIS_SQUEEZE_VETO_THRESHOLD",
        ge=0.0,
        le=1.0,
    )
    agent_thesis_breakout_adx_min: float = Field(
        default=25.0,
        env="AGENT_THESIS_BREAKOUT_ADX_MIN",
    )
    agent_thesis_breakout_di_min: float = Field(
        default=5.0,
        env="AGENT_THESIS_BREAKOUT_DI_MIN",
    )
    agent_thesis_breakout_vol_regime_min: float = Field(
        default=1.1,
        env="AGENT_THESIS_BREAKOUT_VOL_REGIME_MIN",
    )
    agent_thesis_trend_rsi_lo: float = Field(
        default=40.0,
        env="AGENT_THESIS_TREND_RSI_LO",
    )
    agent_thesis_trend_rsi_hi: float = Field(
        default=65.0,
        env="AGENT_THESIS_TREND_RSI_HI",
    )
    agent_thesis_trend_hurst_min: float = Field(
        default=0.52,
        env="AGENT_THESIS_TREND_HURST_MIN",
    )
    agent_thesis_mr_rsi_max: float = Field(
        default=32.0,
        env="AGENT_THESIS_MR_RSI_MAX",
    )
    agent_thesis_mr_bb_pos_max: float = Field(
        default=0.15,
        env="AGENT_THESIS_MR_BB_POS_MAX",
    )
    agent_decision_idempotency_ttl_seconds: float = Field(
        default=300.0,
        env="AGENT_DECISION_IDEMPOTENCY_TTL_SECONDS",
        description="TTL for duplicate decision_event_id execution guard.",
    )
    manual_execute_requires_audit_reason_live: bool = Field(
        default=True,
        env="MANUAL_EXECUTE_REQUIRES_AUDIT_REASON_LIVE",
        description=(
            "When TRADING_MODE=live, WebSocket/API execute_trade must include "
            "non-empty manual_trade_audit_reason in parameters or the agent rejects the command."
        ),
    )
    xgb_binary_decision_midpoint: float = Field(
        default=0.5,
        env="XGB_BINARY_DECISION_MIDPOINT",
        description=(
            "Neutral probability midpoint for binary XGBoost outputs. "
            "Used when mapping predict_proba to [-1, +1] in xgboost_node."
        ),
    )
    reasoning_consensus_label_threshold: float = Field(
        default=0.5,
        env="REASONING_CONSENSUS_LABEL_THRESHOLD",
        description=(
            "Consensus magnitude threshold used by reasoning step-3 labels "
            "('strong bullish/bearish consensus' vs mixed)."
        ),
    )
    update_interval: int = Field(
        default=900,
        env="UPDATE_INTERVAL",
        description="Update interval in seconds (legacy - used for candle-based operations)"
    )
    price_fluctuation_threshold_pct: float = Field(
        default=0.10,
        env="PRICE_FLUCTUATION_THRESHOLD_PCT",
        description="Percentage threshold for price fluctuations that trigger ML pipeline (e.g., 0.5 = 0.5%)"
    )
    fast_poll_interval: float = Field(
        default=0.5,
        env="FAST_POLL_INTERVAL",
        description="Fast polling interval in seconds for continuous ticker monitoring (controls API call frequency)"
    )
    timeframes: str = Field(
        default="3m,5m,15m",
        env="TIMEFRAMES",
        description="Comma-separated list of timeframes when ACTIVE_TIMEFRAMES is unset (15m=trend, 5m=entry, 3m=optional filter)"
    )

    # WebSocket Configuration
    websocket_enabled: bool = Field(
        default=True,
        env="WEBSOCKET_ENABLED",
        description="Enable WebSocket streaming for real-time data (default: True)"
    )
    websocket_url: str = Field(
        default=DELTA_TESTNET_WEBSOCKET_URL_DEFAULT,
        env="WEBSOCKET_URL",
        description="Delta Exchange WebSocket URL (must match testnet REST cluster)",
    )
    websocket_reconnect_attempts: int = Field(
        default=5,
        env="WEBSOCKET_RECONNECT_ATTEMPTS",
        description="Maximum WebSocket reconnection attempts"
    )
    websocket_reconnect_delay: float = Field(
        default=5.0,
        env="WEBSOCKET_RECONNECT_DELAY",
        description="Delay between WebSocket reconnection attempts in seconds"
    )
    websocket_heartbeat_interval: float = Field(
        default=30.0,
        env="WEBSOCKET_HEARTBEAT_INTERVAL",
        description="WebSocket heartbeat interval in seconds"
    )
    websocket_fallback_poll_interval: float = Field(
        default=60.0,
        env="WEBSOCKET_FALLBACK_POLL_INTERVAL",
        description="REST API polling interval when WebSocket is unavailable (seconds)"
    )
    market_data_stale_rest_poll_seconds: float = Field(
        default=15.0,
        env="MARKET_DATA_STALE_REST_POLL_SECONDS",
        ge=3.0,
        le=300.0,
        description=(
            "If Delta WSS is connected but no good ticker arrived within this window, "
            "poll REST GET /v2/tickers/{symbol} for the headline price (seconds)"
        ),
    )

    # Candle monitoring cadence (REST calls) - can be different from ticker polling cadence.
    candle_poll_interval_seconds: int = Field(
        default=30,
        env="CANDLE_POLL_INTERVAL_SECONDS",
        description="How often to check for completed candles while streaming (seconds)"
    )
    candle_close_trigger_enabled: bool = Field(
        default=True,
        env="CANDLE_CLOSE_TRIGGER_ENABLED",
        description="Enable candle-close event path to trigger ML decision pipeline.",
    )
    price_fluctuation_trigger_enabled: bool = Field(
        default=True,
        env="PRICE_FLUCTUATION_TRIGGER_ENABLED",
        description="Enable price-fluctuation event path to trigger ML decision pipeline.",
    )
    # Signal staleness configuration
    signal_staleness_minutes: int = Field(
        default=10,
        env="SIGNAL_STALENESS_MINUTES",
        description="Minutes since last DecisionReadyEvent after which agent should proactively trigger a new prediction"
    )

    # Market data recovery configuration
    agent_no_candle_restart_minutes: int = Field(
        default=10,
        env="AGENT_NO_CANDLE_RESTART_MINUTES",
        description="Minutes without candle closes before attempting a market data stream restart"
    )

    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_trading_mode(cls, value: Optional[str]) -> str:
        """Normalize trading mode string (testnet-only runtime)."""
        if value is None:
            return "testnet"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"paper", "live"}:
                print(
                    "Warning: TRADING_MODE=paper|live is deprecated; using testnet.",
                    file=sys.stderr,
                )
                return "testnet"
            if normalized != "testnet":
                raise ValueError("TRADING_MODE must be 'testnet'")
            return normalized
        raise ValueError("TRADING_MODE must be a string")

    @field_validator("exchange_backend", mode="before")
    @classmethod
    def normalize_exchange_backend(cls, value: Optional[str]) -> str:
        """Normalize exchange backend selector."""
        backend = (value or "delta_live").strip().lower()
        if backend == "delta_paper_sim":
            raise ValueError(
                "EXCHANGE_BACKEND=delta_paper_sim is removed; use delta_live against Delta testnet"
            )
        if backend != "delta_live":
            raise ValueError("EXCHANGE_BACKEND must be delta_live")
        return backend

    @field_validator("delta_env", mode="before")
    @classmethod
    def normalize_delta_env(cls, value: Optional[str]) -> str:
        """Normalize Delta environment selector."""
        env_name = (value or "india_testnet").strip().lower()
        if env_name == "india_prod":
            raise ValueError(
                "DELTA_ENV=india_prod is not allowed; runtime requires india_testnet"
            )
        if env_name != "india_testnet":
            raise ValueError("DELTA_ENV must be india_testnet")
        return env_name

    @field_validator("agent_start_mode", mode="before")
    @classmethod
    def validate_start_mode(cls, value: Optional[str]) -> str:
        """Ensure agent start mode is supported."""
        allowed = {"MONITORING", "PAUSED", "EMERGENCY_STOP"}
        mode = (value or "MONITORING").strip().upper()
        if mode not in allowed:
            raise ValueError(
                f"AGENT_START_MODE must be one of {', '.join(sorted(allowed))}"
            )
        return mode

    @field_validator("timeframes", mode="before")
    @classmethod
    def normalize_timeframes(cls, value: Optional[str]) -> str:
        """Normalize timeframe string by trimming whitespace and duplicates."""
        if not value:
            return "15m"
        if isinstance(value, str):
            cleaned = [tf.strip() for tf in value.split(",") if tf.strip()]
            return ",".join(dict.fromkeys(cleaned)) or "15m"
        raise ValueError("TIMEFRAMES must be a comma-separated string")

    @field_validator("price_fluctuation_threshold_pct", mode="before")
    @classmethod
    def validate_price_fluctuation_threshold(cls, value: Optional[float]) -> float:
        """Validate price fluctuation threshold is positive."""
        if value is None:
            return 0.5

        # Handle string inputs from environment variables
        if isinstance(value, str):
            try:
                threshold = float(value)
            except ValueError:
                raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be a valid number")
        elif isinstance(value, (int, float)):
            threshold = float(value)
        else:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be a number")

        if threshold <= 0:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be positive")
        if threshold > 100:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT cannot exceed 100%")
        return threshold

    @field_validator("fast_poll_interval", mode="before")
    @classmethod
    def validate_fast_poll_interval(cls, value: Optional[float]) -> float:
        """Validate fast poll interval is reasonable."""
        if value is None:
            return 0.5

        # Handle string inputs from environment variables
        if isinstance(value, str):
            try:
                interval = float(value)
            except ValueError:
                raise ValueError("FAST_POLL_INTERVAL must be a valid number")
        elif isinstance(value, (int, float)):
            interval = float(value)
        else:
            raise ValueError("FAST_POLL_INTERVAL must be a number")

        if interval <= 0:
            raise ValueError("FAST_POLL_INTERVAL must be positive")
        if interval > 60:
            raise ValueError("FAST_POLL_INTERVAL cannot exceed 60 seconds (too slow for real-time)")
        return interval

    @model_validator(mode="after")
    def validate_futures_lot_contract(self) -> "Settings":
        """Ensure perpetual lot settings remain valid."""
        if float(self.contract_value_btc) <= 0:
            raise ValueError("CONTRACT_VALUE_BTC must be greater than 0")
        if int(self.min_lot_size) < 1:
            raise ValueError("MIN_LOT_SIZE must be at least 1")
        if int(self.fixed_lot_size) < int(self.min_lot_size):
            self.fixed_lot_size = int(self.min_lot_size)
        return self

    @model_validator(mode="after")
    def enforce_testnet_runtime(self) -> "Settings":
        """Enforce Delta testnet URLs and reject removed local paper-simulation flags."""
        paper_mode_env = os.getenv("PAPER_TRADING_MODE", "").strip().lower()
        if paper_mode_env in ("true", "1", "yes"):
            raise ValueError(
                "PAPER_TRADING_MODE is removed. Use TRADING_MODE=testnet with Delta testnet API keys."
            )

        self.trading_mode = "testnet"
        self.delta_environment = "testnet"
        self.exchange_backend = "delta_live"
        self.delta_env = "india_testnet"

        parsed = urlparse((self.delta_exchange_base_url or "").strip())
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError("DELTA_EXCHANGE_BASE_URL must include a valid hostname")
        if host not in DELTA_TESTNET_ALLOWED_HOSTS:
            raise ValueError(
                f"DELTA_EXCHANGE_BASE_URL host '{host}' is not an allowed Delta testnet host. "
                f"Allowed: {', '.join(DELTA_TESTNET_ALLOWED_HOSTS)}"
            )

        ws_parsed = urlparse((self.websocket_url or "").strip())
        ws_host = (ws_parsed.hostname or "").lower()
        if ws_host and ws_host not in DELTA_TESTNET_ALLOWED_HOSTS:
            if "testnet" not in ws_host and "deltaex.org" not in ws_host:
                print(
                    f"Warning: WEBSOCKET_URL host '{ws_host}' may not match testnet cluster.",
                    file=sys.stderr,
                )

        return self

    def parsed_timeframes(self) -> List[str]:
        """Return normalized timeframes as list."""
        return [tf for tf in (self.timeframes or "").split(",") if tf]

    def resolved_agent_timeframes(self) -> List[str]:
        """Timeframes for candle loops: prefer ACTIVE_TIMEFRAMES when set, else TIMEFRAMES."""
        active = [
            tf.strip()
            for tf in (self.active_timeframes or "").split(",")
            if tf.strip()
        ]
        if active:
            return active
        return self.parsed_timeframes() or [self.agent_interval]
    
try:
    settings = Settings()
except Exception as e:
    # Configuration errors must be printed to stderr since logger may not be initialized
    # This is acceptable for startup errors that prevent the application from starting
    import sys
    
    # Check if either env file exists to provide more specific guidance.
    env_exists = ROOT_ENV_PATH.exists() or ROOT_ENV_EXAMPLE_PATH.exists()
    
    # Try to extract which field failed from Pydantic error
    error_str = str(e)
    missing_field = None
    if "field required" in error_str.lower():
        # Try to extract field name from error message
        import re
        match = re.search(r"['\"]([^'\"]+)['\"]", error_str)
        if match:
            missing_field = match.group(1)
    
    error_msg = f"""
{'='*70}
ERROR: Failed to load agent configuration
{'='*70}

Error: {error_str}
"""
    
    if env_exists:
        error_msg += f"""
Env files in use (later overrides earlier):
  - defaults : {ROOT_ENV_EXAMPLE_PATH} ({'present' if ROOT_ENV_EXAMPLE_PATH.exists() else 'MISSING'})
  - secrets  : {ROOT_ENV_PATH} ({'present' if ROOT_ENV_PATH.exists() else 'MISSING'})

However, there are issues with the configuration:
"""
        if missing_field:
            error_msg += f"  - Missing or invalid: {missing_field}\n"
        else:
            error_msg += "  - One or more required variables are missing or invalid\n"

        error_msg += """
Required secrets (must be in root .env):
  - DATABASE_URL (PostgreSQL connection URL with password)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key from your account)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret from your account)

Non-secret defaults live in .env.example (MODEL_DIR, AGENT_SYMBOL, AGENT_INTERVAL,
thresholds, feature flags, ports, etc.). Edit values there, not in .env.

To fix:
  1. Ensure root .env contains the required secrets above (no empty values).
  2. Ensure .env.example is present in the project root (non-secret defaults).
  3. Verify variable formats are correct.
  4. Ensure database is initialized: python scripts/setup_db.py
  5. See docs/13-debugging.md and docs/10-deployment.md for detailed help.
"""
    else:
        error_msg += f"""
No env files found in the project root:
  - {ROOT_ENV_EXAMPLE_PATH}
  - {ROOT_ENV_PATH}

Required secrets (place in root .env):
  - DATABASE_URL (PostgreSQL connection URL with password)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret)

Non-secret defaults (place in committed .env.example):
  - MODEL_PATH / MODEL_DIR / AGENT_SYMBOL / AGENT_INTERVAL / thresholds / flags

To fix:
  1. Keep .env.example committed for non-secret defaults.
  2. Create root .env with secrets only (DB password, Delta keys, JWT, API_KEY).
  3. Or export required variables in the process environment (e.g. Colab/CI).
  4. Initialize database: python scripts/setup_db.py
  5. See docs/11-build-guide.md for setup instructions.
"""
    
    error_msg += f"""
Additional checks:
  - Ensure PostgreSQL is running and accessible
  - Ensure Redis is running (if required)
  - Verify DATABASE_URL connection string format is correct
  - Run database setup: python scripts/setup_db.py
{'='*70}
"""
    print(error_msg, file=sys.stderr)
    sys.exit(1)
