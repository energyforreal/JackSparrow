"""
Configuration management for agent service.

Handles environment variable loading, validation, and default values.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator

# Determine ROOT_ENV_PATH with Colab compatibility
def _get_root_env_path() -> Path:
    """Get path to .env file, handling both Colab and local execution."""
    # Try using __file__ first (works in local execution)
    try:
        if __file__:
            config_path = Path(__file__).resolve()
            # agent/core/config.py -> project root (2 levels up)
            potential_root = config_path.parents[2]
            env_path = potential_root / ".env"
            if env_path.exists() or (potential_root / "agent").exists():
                return env_path
    except (NameError, AttributeError):
        # __file__ not available (e.g., in some Colab environments)
        pass
    
    # Fallback: search from current working directory
    cwd = Path.cwd()
    
    # Check if .env exists in current directory
    if (cwd / ".env").exists():
        return cwd / ".env"
    
    # Check if we're in project root
    if (cwd / "agent").exists():
        return cwd / ".env"
    
    # Search upward from current directory
    current = cwd
    for _ in range(5):  # Limit search depth
        if (current / "agent").exists():
            return current / ".env"
        if current == current.parent:
            break
        current = current.parent
    
    # Last resort: return a path that may not exist (will be handled by pydantic)
    return cwd / ".env"

ROOT_ENV_PATH = _get_root_env_path()


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        # Make env_file optional - if it doesn't exist, use environment variables only
        env_file=str(ROOT_ENV_PATH) if ROOT_ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
        protected_namespaces=("settings_",),
        # In Colab, environment variables are preferred over .env file
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
        default="https://api.india.delta.exchange",
        env=("DELTA_EXCHANGE_BASE_URL", "DELTA_API_URL", "delta_api_url"),
        description="Delta Exchange API base URL"
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
        default="./agent/model_storage",
        env="MODEL_DIR",
        description="Directory for model discovery"
    )
    model_discovery_recursive: bool = Field(
        default=True,
        env="MODEL_DISCOVERY_RECURSIVE",
        description=(
            "When true, discover metadata_BTCUSD_*.json recursively under MODEL_DIR "
            "(e.g. jacksparrow_v5_BTCUSD_*/ subfolders). When false, only the top-level MODEL_DIR."
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
            "When True, load only one consolidated BTCUSD model artifact and bypass "
            "timeframe-indexed runtime decision synthesis."
        ),
    )
    consolidated_model_metadata_glob: str = Field(
        default="metadata_BTCUSD_consolidated*.json",
        env="CONSOLIDATED_MODEL_METADATA_GLOB",
        description=(
            "Glob used by model discovery to locate the consolidated model metadata "
            "artifact when SINGLE_MODEL_MODE_ENABLED is true."
        ),
    )
    single_model_strict_startup: bool = Field(
        default=False,
        env="SINGLE_MODEL_STRICT_STARTUP",
        description=(
            "When True in single-model mode, fail startup if no consolidated model "
            "metadata artifact is found."
        ),
    )
    model_auto_register: bool = Field(
        default=True,
        env="MODEL_AUTO_REGISTER",
        description="Auto-register discovered models"
    )
    model_format: str = Field(
        default="auto",
        env="MODEL_FORMAT",
        description=(
            "Model bundle format: auto (detect per metadata), v4_ensemble, v15_pipeline"
        ),
    )
    v15_signal_logic_enabled: bool = Field(
        default=True,
        env="V15_SIGNAL_LOGIC_ENABLED",
        description="When True and v15 models are active, apply v15 entry/exit filters.",
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
        default=90.0,
        env="CONFIDENCE_PERCENTILE",
        description="Rolling percentile of |edge| for v15 entry gating (e.g. 90 = top 10%).",
    )
    edge_floor: float = Field(
        default=0.15,
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
        default=2.0,
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
        default=True,
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
        default=True,
        env="V15_DAILY_TRADE_CAP_ENABLED",
        description="When True, enforce per-timeframe daily trade caps for v15.",
    )
    position_restore_on_startup: bool = Field(
        default=True,
        env="POSITION_RESTORE_ON_STARTUP",
        description="Load open DB positions into the execution engine after startup (paper).",
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
        default="5m,15m,30m,1h,2h",
        env="ACTIVE_TIMEFRAMES",
        description="Comma-separated list of active trading timeframes"
    )
    
    # Trading Mode
    paper_trading_mode: bool = Field(
        default=True,
        env="PAPER_TRADING_MODE",
        description="Enable paper trading mode (default: True). Set to False for live trading."
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
        default=10,
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
        default=3,
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
        default="paper",
        env="TRADING_MODE",
        description="Trading mode (paper/live)"
    )
    trading_symbol: str = Field(
        default="BTCUSD",
        env="TRADING_SYMBOL",
        description="Trading symbol"
    )
    min_confidence_threshold: float = Field(
        default=0.70,
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
        description="Comma-separated list of timeframes (no 1m; 15m=trend, 5m=entry, 3m=optional filter)"
    )

    # WebSocket Configuration
    websocket_enabled: bool = Field(
        default=True,
        env="WEBSOCKET_ENABLED",
        description="Enable WebSocket streaming for real-time data (default: True)"
    )
    websocket_url: str = Field(
        default="wss://socket.india.delta.exchange",
        env="WEBSOCKET_URL",
        description="Delta Exchange WebSocket URL"
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
        """Normalize trading mode string."""
        if value is None:
            return "paper"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in {"paper", "live"}:
                raise ValueError("TRADING_MODE must be either 'paper' or 'live'")
            return normalized
        raise ValueError("TRADING_MODE must be a string")

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
    def sync_trading_flags(self) -> "Settings":
        """Keep trading_mode and paper_trading_mode aligned."""
        trading_mode_env = os.getenv("TRADING_MODE")
        paper_mode_env = os.getenv("PAPER_TRADING_MODE")

        normalized_mode = (self.trading_mode or "paper").lower()
        derived_paper_flag = normalized_mode != "live"

        if trading_mode_env is not None:
            # TRADING_MODE takes precedence – update boolean flag accordingly
            if paper_mode_env and self.paper_trading_mode != derived_paper_flag:
                print(
                    "Warning: PAPER_TRADING_MODE overrides are ignored when TRADING_MODE is set. "
                    "Keeping values in sync.",
                    file=sys.stderr,
                )
            self.paper_trading_mode = derived_paper_flag
            self.trading_mode = normalized_mode
        elif paper_mode_env is not None:
            # Only PAPER_TRADING_MODE provided – update string representation
            self.trading_mode = "paper" if self.paper_trading_mode else "live"
        else:
            # Neither provided explicitly – derive bool from mode, defaulting to paper
            self.paper_trading_mode = derived_paper_flag
            self.trading_mode = normalized_mode

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
    
    # Check if .env file exists to provide more specific guidance
    env_exists = ROOT_ENV_PATH.exists()
    
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
The .env file exists at: {ROOT_ENV_PATH}

However, there are issues with the configuration:
"""
        if missing_field:
            error_msg += f"  - Missing or invalid: {missing_field}\n"
        else:
            error_msg += "  - One or more required variables are missing or invalid\n"
        
        error_msg += f"""
Required environment variables (check your .env file):
  - DATABASE_URL (PostgreSQL connection URL, e.g., postgresql://user:pass@localhost:5432/dbname)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key from your account)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret from your account)

Optional environment variables:
  - MODEL_PATH (Path to specific model file, e.g., models/xgboost_BTCUSD_15m.pkl)
  - MODEL_DIR (Directory for model discovery, default: ./agent/model_storage)
  - AGENT_SYMBOL (Trading symbol, default: BTCUSD)
  - AGENT_INTERVAL (Analysis interval, default: 15m)

To fix:
  1. Open the .env file: {ROOT_ENV_PATH}
  2. Ensure all required variables are set (no empty values)
  3. Verify variable formats are correct
  4. Run validation: python scripts/validate-env.py
  5. Ensure database is initialized: python scripts/setup_db.py
  6. See docs/13-debugging.md and docs/10-deployment.md for detailed help
"""
    else:
        error_msg += f"""
The .env file was not found at: {ROOT_ENV_PATH}

Required environment variables:
  - DATABASE_URL (PostgreSQL connection URL)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret)

Optional environment variables:
  - MODEL_PATH (Path to specific model file)
  - MODEL_DIR (Directory for model discovery, default: ./agent/model_storage)
  - AGENT_SYMBOL (Trading symbol, default: BTCUSD)
  - AGENT_INTERVAL (Analysis interval, default: 15m)

To fix:
  1. Copy .env.example to .env in the project root (if .env.example exists)
  2. Or create .env file manually with all required variables
  3. Fill in all required values
  4. Run validation: python scripts/validate-env.py
  5. Initialize database: python scripts/setup_db.py
  6. See docs/11-build-guide.md for setup instructions
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
