"""Standard structlog field names for observability (model, features, trades)."""

# Event names (suffix with subsystem as needed)
EVENT_MODEL_PREDICTION = "model_prediction"
EVENT_FEATURE_RESPONSE = "feature_response"
EVENT_TRADE_LIFECYCLE = "trade_lifecycle"

# Common bound keys
KEY_MODEL_VERSION = "model_version"
KEY_MODEL_ID = "model_id"
KEY_FEATURE_QUALITY = "feature_quality"
KEY_PREDICTION_PROBA = "prediction_proba_max"
KEY_SYMBOL = "symbol"
KEY_TIMEFRAME = "timeframe"
KEY_TRADE_ID = "trade_id"
KEY_POSITION_ID = "position_id"
KEY_PNL_REALIZED = "pnl_realized"
KEY_PIPELINE_VERSION = "pipeline_version"
