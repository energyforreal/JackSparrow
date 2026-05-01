# ==== CELL 4 ====
!pip install -q lightgbm xgboost scikit-learn pandas numpy requests python-dotenv schedule ta joblib pyarrow scipy
!pip install -q torch --index-url https://download.pytorch.org/whl/cu121 2>/dev/null || pip install -q torch
print('✅ Dependencies installed')

# ==== CELL 5 ====
# ── GPU Detection & Setup ─────────────────────────────────────────────────────
import subprocess, os, torch

def _detect_gpu():
    """Returns ('cuda', device_name) or ('cpu', 'CPU')."""
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        print(f'  🟢 GPU detected: {name}')
        print(f'     CUDA {torch.version.cuda} | VRAM {torch.cuda.get_device_properties(0).total_memory // 1024**2} MB')
        return 'cuda', name
    print('  🟡 No GPU — falling back to CPU')
    return 'cpu', 'CPU'

GPU_DEVICE, GPU_NAME = _detect_gpu()
USE_GPU = (GPU_DEVICE == 'cuda')

# LightGBM device string
LGBM_DEVICE   = 'gpu'  if USE_GPU else 'cpu'
# XGBoost device string  
XGB_DEVICE    = 'cuda' if USE_GPU else 'cpu'
# Torch device
TORCH_DEVICE  = torch.device('cuda' if USE_GPU else 'cpu')

print(f'\n✅ GPU config: LGBM={LGBM_DEVICE} | XGB={XGB_DEVICE} | Torch={TORCH_DEVICE}')
print(f'   MLP will train on: {TORCH_DEVICE}')

# ==== CELL 7 ====
import os
import random
import numpy as _np_seed

# ── Global reproducibility seed (P7) ────────────────────────────────────
SEED = 42
random.seed(SEED)
_np_seed.random.seed(SEED)
os.environ['PYTHONHASHSEED'] = str(SEED)

# ── Delta Exchange India Credentials ────────────────────────────────────────
# Set these as Colab Secrets (left sidebar 🔑) or environment variables
try:
    from google.colab import userdata
    API_KEY    = userdata.get('DELTA_API_KEY')
    API_SECRET = userdata.get('DELTA_API_SECRET')
except Exception:
    API_KEY    = os.getenv('DELTA_API_KEY', 'YOUR_KEY_HERE')
    API_SECRET = os.getenv('DELTA_API_SECRET', 'YOUR_SECRET_HERE')

# ── Exchange Config ──────────────────────────────────────────────────────────
BASE_URL       = 'https://api.india.delta.exchange'   # Delta Exchange India
SYMBOL_5M      = 'BTCUSD'                            # Futures product symbol
SYMBOL_15M     = 'BTCUSD'                            # Same symbol, different resolution
SYMBOL_1H      = 'BTCUSD'                            # Same symbol, 1h timeframe
PRODUCT_ID     = 27                                   # BTC perpetual product_id on Delta India

# ── Data Config ─────────────────────────────────────────────────────────────
CANDLE_RES_5M  = '5m'
CANDLE_RES_15M = '15m'
TARGET_CANDLES_5M  = 30_000   # Candles to fetch for 5m  timeframe (≈104 days)
TARGET_CANDLES_15M = 20_000   # Candles to fetch for 15m timeframe (≈208 days)
TARGET_CANDLES_1H  = 3_000    # Candles to fetch for 1h  timeframe (≈125 days)
CANDLE_RES_1H  = '1h'
WARMUP_CANDLES = 50                                   # Candles needed for indicator warmup

# ── ML Config ───────────────────────────────────────────────────────────────
RETRAIN_INTERVAL_MINUTES = 60                         # Live retrain cadence (used by LiveTrader)
MIN_TRAIN_SAMPLES        = 500                        # Min rows before training
WALK_FORWARD_SPLITS      = 5                          # Number of WF folds
SIGNAL_THRESHOLD         = 0.58                       # Probability threshold for entry
ENSEMBLE_WEIGHTS         = {'lgbm': 0.45, 'rf': 0.25, 'xgb': 0.20, 'mlp': 0.10}  # v24 4-model weights

# ── Trade Config ────────────────────────────────────────────────────────────
CAPITAL_USDT             = 1000.0                     # Starting capital
MAKER_FEE                = 0.0005                     # 0.05% maker fee
TAKER_FEE                = 0.0005                     # 0.05% taker fee (Delta India flat)
SLIPPAGE_PCT             = 0.0003                     # 0.03% slippage estimate
MAX_POSITION_PCT         = 0.20                       # Max 20% capital per trade (Kelly cap)
STOP_LOSS_PCT            = 0.015                      # 1.5% SL
TAKE_PROFIT_PCT          = 0.03                       # 3.0% TP  (2:1 R/R)
LEVERAGE                 = 5                          # Futures leverage

# ── Backtest Config ─────────────────────────────────────────────────────────
BACKTEST_DAYS            = 60                         # Days for OOS backtest
MODEL_DIR                = '/content/models'          # Model save path
os.makedirs(MODEL_DIR, exist_ok=True)

# ── Offline Retrain Test Config ──────────────────────────────────────────────
# These control Cell 12 (Offline Retrain Test). Tune without touching live logic.
RETRAIN_WINDOW_PAST_BARS    = 5000   # Reference window size for KS drift detection
RETRAIN_WINDOW_RECENT_BARS  = 2000   # Recent window size to test for drift
RETRAIN_DRIFT_FEATURE_LIMIT = 5      # Min drifted features to trigger a retrain
RETRAIN_CYCLES              = 3      # Number of simulated retrain cycles
RETRAIN_VALIDATION_MIN_AUC  = 0.55   # Minimum CV AUC to accept a new model (raised from 0.525 — barely above random)
RETRAIN_VALIDATION_MIN_WR   = 50.0   # Minimum win-rate % — ensures positive EV at 2:1 R/R (raised from 45.0)

# ── v27 Target Config ──────────────────────────────────────────────────────
TP_SL_TARGET_HORIZON = 60   # bars to look forward for TP/SL path outcome (Fix 1)
                             # 60 bars × 5m = 5 hours forward horizon
LONG_ONLY_EXECUTION  = True  # Binary TP/SL target supports long/flat execution only.
REQUIRE_FUNDING_DATA = True  # No zero-fill placeholder funding features in training/live.

# ── v24 Advanced Config ────────────────────────────────────────────────────
USE_META_LEARNER        = True    # Stack models with logistic-regression meta-layer
USE_PROB_CALIBRATION    = True    # Calibrate final probabilities via isotonic regression
PSI_THRESHOLD           = 0.20    # Population Stability Index threshold for drift
REGIME_WINDOW           = 100     # Bars for regime-detection (trending vs choppy)
MLP_HIDDEN_LAYERS       = (128, 64, 32)  # Dense layer sizes for neural net component
RETRAIN_WARMSTART       = True    # Warm-start retraining (fine-tune vs cold start)
RETRAIN_PERF_DECAY      = 0.95    # Exponential decay for rolling retrain perf tracking
SIGNAL_THRESHOLD_LONG   = 0.58    # Asymmetric threshold: long entry
SIGNAL_THRESHOLD_SHORT  = 0.42    # Asymmetric threshold: short entry

# Synthetic / placeholder data is strictly prohibited — models must train on real exchange data.
# ALLOW_SYNTHETIC_DATA has been removed. The pipeline hard-fails if the API returns no data.
TRADING_AGENT_ROOT = os.getenv('TRADING_AGENT_ROOT', '').strip()
if TRADING_AGENT_ROOT:
    import sys
    from pathlib import Path as _Path
    _rp = _Path(TRADING_AGENT_ROOT).resolve()
    if str(_rp) not in sys.path:
        sys.path.insert(0, str(_rp))

# Candle integrity: auto-disabled if TRADING_AGENT_ROOT is unset (P4 fix).
# Set env STRICT_CANDLES=1 explicitly to force strict mode in Colab.
_strict_env = os.getenv('STRICT_CANDLES', '')
if _strict_env == '':
    STRICT_CANDLES = bool(TRADING_AGENT_ROOT)  # strict only when repo is mounted
else:
    STRICT_CANDLES = _strict_env != '0'
FETCH_PAGE_RETRIES = int(os.getenv('FETCH_PAGE_RETRIES', '3'))

# ── v28 Regime & Risk Config (new) ─────────────────────────────────────────
MAX_DRAWDOWN_HALT        = 0.15    # Halt LiveTrader if equity drops 15% from peak
CRISIS_VOL_THRESHOLD     = 3.0    # vol_regime > 3× median → crisis regime
CRISIS_VOL_OF_VOL_THRESH = 2.0    # vol_of_vol > 2 → unstable volatility → crisis
REGIME_EMA_SPAN          = 12     # EMA span for smoothing regime features (1h of 5m bars)
REGIME_MIN_BARS          = 6      # Min bars in regime before accepting switch (30 min)

print('✅ Config loaded — v28 (TP/SL target | GBDT | regime-aware meta-learner | gap=200 | raised gates)')
print(f'   Symbol: {SYMBOL_5M} | Leverage: {LEVERAGE}x | Capital: ${CAPITAL_USDT}')
print(f'   5m target: {TARGET_CANDLES_5M:,} candles | 15m target: {TARGET_CANDLES_15M:,} candles | 1h target: {TARGET_CANDLES_1H:,} candles')
print(f'   Signal threshold: {SIGNAL_THRESHOLD} | Retrain every: {RETRAIN_INTERVAL_MINUTES}m')
print(f'   STRICT_CANDLES={STRICT_CANDLES} | FETCH_PAGE_RETRIES={FETCH_PAGE_RETRIES}')
print(f'   Retrain test: {RETRAIN_CYCLES} cycles | past={RETRAIN_WINDOW_PAST_BARS} bars | recent={RETRAIN_WINDOW_RECENT_BARS} bars')
print(f'   Validation gate: AUC≥{RETRAIN_VALIDATION_MIN_AUC} | WinRate≥{RETRAIN_VALIDATION_MIN_WR}%')
print(f'   SEED={SEED} | STRICT_CANDLES={STRICT_CANDLES} | SYNTHETIC=DISABLED')

# ==== CELL 9 ====
import time
import hmac
import hashlib
import os
import sys
import requests
import pandas as pd
import numpy as np
from pathlib import Path as _Path
from datetime import datetime, timezone, timedelta
from typing import Optional

validate_candles = None
try:
    from agent.data.candle_validation import validate_candles
except ImportError:
    pass


def _resolve_validate_candles():
    """Load validate_candles from repo (TRADING_AGENT_ROOT or cwd parents)."""
    global validate_candles
    if validate_candles is not None:
        return validate_candles
    roots = []
    r = os.environ.get("TRADING_AGENT_ROOT", "").strip()
    if r:
        roots.append(_Path(r).resolve())
    here = _Path.cwd().resolve()
    for p in (here, here.parent, here.parent.parent):
        roots.append(p)
    seen = set()
    for base in roots:
        if base in seen:
            continue
        seen.add(base)
        if not base.exists():
            continue
        mod = base / "agent" / "data" / "candle_validation.py"
        if mod.is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            try:
                from agent.data.candle_validation import validate_candles as vc
                # BUG 10 FIX: deduplicate sys.path to prevent accumulation in long-running processes
                sys.path = list(dict.fromkeys(sys.path))
                return vc
            except ImportError:
                pass
    sys.path = list(dict.fromkeys(sys.path))   # BUG 10 FIX: deduplicate on exit too
    return None


validate_candles = _resolve_validate_candles()
if validate_candles is None:
    if STRICT_CANDLES:
        # P4 fix: degrade to warning instead of hard crash
        print(
            'WARNING: STRICT_CANDLES=True but agent.data.candle_validation could not be imported.\n'
            '  → Auto-disabling STRICT_CANDLES for this session.\n'
            '  Set TRADING_AGENT_ROOT to your Trading Agent repo root to enable it.'
        )
        STRICT_CANDLES = False
    else:
        print(
            'WARNING: validate_candles unavailable — no gap/regularity OHLC checks.\n'
            '  Set TRADING_AGENT_ROOT to enable candle validation (recommended).'
        )


def _validate_frame(df: pd.DataFrame, resolution: str, min_rows: int) -> None:
    if validate_candles is None:
        return
    validate_candles(
        df,
        resolution,
        min_rows=min_rows,
        allow_last_irregular=True,
    )


class DeltaClient:
    """
    Minimal Delta Exchange India REST client.
    Candle endpoint: GET /v2/history/candles
    Docs: https://docs.delta.exchange/#get-ohlcv-candles

    [v22-enhanced] Added fetch_latest_candles() for incremental data updates (v16 pattern)
    """

    VALID_RESOLUTIONS = {'1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '1d', '1w'}

    def __init__(self, base_url: str, api_key: str, api_secret: str):
        self.base_url   = base_url.rstrip('/')
        self.api_key    = api_key
        self.api_secret = api_secret
        self.session    = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'api-key': self.api_key,
        })

    def _sign(self, method: str, path: str, query: str = '', body: str = '') -> dict:
        ts      = str(int(time.time()))
        message = method.upper() + ts + path + query + body
        sig     = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {'timestamp': ts, 'signature': sig}

    def _get(self, path: str, params: dict = None, signed: bool = False) -> dict:
        url      = self.base_url + path
        params   = params or {}
        query_str = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
        headers  = {}
        if signed:
            auth = self._sign('GET', path, '?' + query_str if query_str else '')
            headers = {'timestamp': auth['timestamp'], 'signature': auth['signature']}
        resp = self.session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _get_json_retry(self, path: str, params: dict = None, signed: bool = False) -> dict:
        last_err = None
        for attempt in range(FETCH_PAGE_RETRIES):
            try:
                return self._get(path, params, signed)
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                if attempt + 1 < FETCH_PAGE_RETRIES:
                    time.sleep(0.4 * (2 ** attempt))
        assert last_err is not None
        raise last_err

    def fetch_candles(
        self,
        symbol:     str,
        resolution: str,
        n_bars:     int                    = None,   # PRIMARY: fetch exactly this many candles
        start_time: Optional[datetime]     = None,   # ignored when n_bars is set
        end_time:   Optional[datetime]     = None,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles by candle count (preferred) or time range.

        Parameters
        ----------
        n_bars      : int, optional
            Number of most-recent candles to return.  When supplied, start_time
            is computed automatically as  now - n_bars * bar_seconds * 1.05
            (5 % buffer so pagination always yields enough raw bars).
            The returned DataFrame is trimmed to exactly n_bars rows.
        start_time  : datetime, optional — used only when n_bars is None.
        end_time    : datetime, optional — defaults to now (UTC).
        """
        if resolution not in self.VALID_RESOLUTIONS:
            raise ValueError(
                f'Invalid resolution: {resolution}. Valid: {self.VALID_RESOLUTIONS}'
            )

        res_map = {
            '1m': 60,   '3m': 180,  '5m': 300,   '15m': 900,
            '30m': 1800,'1h': 3600, '2h': 7200,  '4h': 14400,
            '6h': 21600,'1d': 86400,'1w': 604800,
        }
        res_secs = res_map[resolution]

        if end_time is None:
            end_time = datetime.now(timezone.utc)

        # ── Derive start_time from n_bars (candle-count mode) ────────────────
        if n_bars is not None:
            # 5 % over-fetch buffer ensures pagination covers n_bars despite
            # small gaps, duplicates, or partial bars near the boundaries.
            start_time = end_time - timedelta(seconds=res_secs * n_bars * 1.05)

        if start_time is None:
            raise ValueError('Provide either n_bars or start_time.')

        t_end   = int(end_time.timestamp())
        t_start = int(start_time.timestamp())
        page_size = 500

        all_candles: list = []
        cursor_end        = t_end
        pagination_failed = False

        target_label = f'{n_bars:,} candles' if n_bars else f'{start_time.date()} → {end_time.date()}'
        print(f'  Fetching {resolution} candles for {symbol} [{target_label}] ...')

        while cursor_end > t_start:
            cursor_start = max(t_start, cursor_end - res_secs * page_size)
            params = {
                'symbol':     symbol,
                'resolution': resolution,
                'start':      cursor_start,
                'end':        cursor_end,
            }
            try:
                data = self._get_json_retry('/v2/history/candles', params=params)
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
                if STRICT_CANDLES:
                    raise RuntimeError(
                        f'Candle pagination failed after {FETCH_PAGE_RETRIES} retries: {e}'
                    ) from e
                print(f'  ⚠️  HTTP error (giving up this window): {e}')
                pagination_failed = True
                break

            candles = data.get('result', [])
            if not candles:
                break

            all_candles.extend(candles)
            cursor_end = cursor_start - 1
            time.sleep(0.15)

            # Early-exit once we have enough raw rows (saves unnecessary pages)
            if n_bars and len(all_candles) >= int(n_bars * 1.05):
                break

        if not all_candles:
            raise ValueError(
                f'No candle data returned for {symbol} {resolution}'
            )

        if pagination_failed and STRICT_CANDLES:
            raise RuntimeError(
                'Incomplete candle fetch: pagination stopped early (HTTP/network). '
                'Fix connectivity or set STRICT_CANDLES=0 to use partial data (not recommended).'
            )

        df = pd.DataFrame(all_candles)
        df = df.rename(columns={
            'time': 'timestamp', 'o': 'open', 'h': 'high',
            'l': 'low',          'c': 'close', 'v': 'volume',
        })
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns and col[0] in df.columns:
                df[col] = df[col[0]]

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        df = (df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
                .drop_duplicates('timestamp')
                .sort_values('timestamp')
                .reset_index(drop=True))
        df[['open', 'high', 'low', 'close', 'volume']] = (
            df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        )

        # ── Trim to exact n_bars (most-recent) ───────────────────────────────
        if n_bars is not None and len(df) > n_bars:
            df = df.tail(n_bars).reset_index(drop=True)

        span_got = (df.timestamp.iloc[-1] - df.timestamp.iloc[0]).total_seconds()
        print(f'  ✅ {len(df):,} {resolution} candles | '
              f'{df.timestamp.iloc[0].date()} → {df.timestamp.iloc[-1].date()} '
              f'(≈{span_got/86400:.1f}d)')

        if n_bars and len(df) < n_bars * 0.9:
            print(f'  ⚠️  Got {len(df):,} candles, expected {n_bars:,} — '
                  f'Delta Exchange history may not go back that far')

        _validate_frame(df, resolution, min_rows=max(WARMUP_CANDLES, 50))
        return df

    def fetch_latest_candles(
        self,
        symbol: str,
        resolution: str,
        n_bars: int = 5000,
    ) -> pd.DataFrame:
        """
        BUG 6 FIX: Use paginated fetch_candles() instead of a single API call.
        The Delta Exchange API returns max 500 bars per page. The old single-call
        implementation silently returned only ~500 bars regardless of n_bars.
        """
        return self.fetch_candles(
            symbol=symbol,
            resolution=resolution,
            n_bars=n_bars,
        )
    def get_balance(self) -> float:
        data = self._get('/v2/wallet/balances', signed=True)
        for asset in data.get('result', []):
            if asset.get('asset_symbol') == 'USDT':
                return float(asset.get('available_balance', 0))
        return 0.0

    def get_ticker(self, symbol: str) -> float:
        data = self._get(f'/v2/tickers/{symbol}')
        return float(data['result']['close'])

    def place_order(
        self, symbol: str, side: str, size: float,
        order_type: str = 'market_order'
    ) -> dict:
        import json
        path   = '/v2/orders'
        payload = {
            'product_symbol': symbol,
            'side':           side,
            'size':           int(size),
            'order_type':     order_type,
        }
        body  = json.dumps(payload, separators=(',', ':'))
        ts    = str(int(time.time()))
        msg   = f'POST{ts}{path}{body}'
        sig   = hmac.new(
            self.api_secret.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()
        headers = {'timestamp': ts, 'signature': sig}
        resp  = self.session.post(
            self.base_url + path, data=body, headers=headers, timeout=10
        )
        resp.raise_for_status()
        return resp.json()


client = DeltaClient(BASE_URL, API_KEY, API_SECRET)
print('✅ DeltaClient ready (v22: validated candles + retry pagination)')


# ==== CELL 10 ====
# ── v25: Funding Rate Fetcher (corrected Delta Exchange endpoint) ─────────────
import requests, time, pandas as pd

def fetch_funding_rate(symbol: str, n_bars: int = 500) -> pd.DataFrame:
    """
    Fetch funding rate history from Delta Exchange India using the candles endpoint.
    Endpoint: GET /v2/history/candles with FUNDING:{symbol} prefix.
    Per Delta Exchange India support — this is the correct way to get historical
    funding rates.
    """
    base_url = "https://api.india.delta.exchange"
    path = "/v2/history/candles"
    funding_symbol = f"FUNDING:{symbol}"

    end_time   = int(time.time())
    # Each funding period is 8h; fetch enough history for n_bars
    start_time = end_time - (n_bars * 8 * 3600)

    params = {
        'symbol':     funding_symbol,
        'resolution': '1h',   # 1h resolution as confirmed by Delta support
        'start':      start_time,
        'end':        end_time,
    }
    try:
        response = requests.get(f"{base_url}{path}", params=params, timeout=(3, 27))
        response.raise_for_status()
        data = response.json()
        if not data.get('success') or not data.get('result'):
            print(f"  ⚠️  Funding data unavailable for {symbol}")
            return pd.DataFrame()
        df = pd.DataFrame(data['result'])
        # Delta funding candles: 'close' is the funding rate value
        df['timestamp']    = pd.to_datetime(df['time'], unit='s', utc=True)
        df['funding_rate'] = df['close'].astype(float)
        df = df[['timestamp', 'funding_rate']].sort_values('timestamp').reset_index(drop=True)
        print(f"  ✅ Funding: {len(df):,} rows from {df.timestamp.iloc[0].date()} → {df.timestamp.iloc[-1].date()}")
        return df.tail(n_bars)
    except Exception as e:
        print(f"  ⚠️  Funding fetch error: {e}")
        return pd.DataFrame()


def add_funding_features(df_5m: pd.DataFrame, df_funding: pd.DataFrame) -> pd.DataFrame:
    """Merge funding rate features onto 5m frame with no lookahead."""
    if df_funding is None or df_funding.empty:
        raise ValueError(
            'Funding data is required but unavailable. '
            'Zero-fill placeholders are disabled for production reliability.'
        )

    df_f = df_funding.copy()
    # 8-period EMA aligns with Delta's 8h funding realization cycle
    df_f['funding_ema8']   = df_f['funding_rate'].ewm(span=8).mean()
    # Cumulative pressure: 3 most recent funding periods summed
    df_f['funding_cum3']   = df_f['funding_rate'].rolling(3).sum()
    # Z-score: how extreme is current funding vs its own history
    roll_mean = df_f['funding_rate'].rolling(50, min_periods=10).mean()
    roll_std  = df_f['funding_rate'].rolling(50, min_periods=10).std()
    df_f['funding_zscore'] = ((df_f['funding_rate'] - roll_mean) / (roll_std + 1e-9)).clip(-4, 4)

    merged = pd.merge_asof(
        df_5m.sort_values('timestamp'),
        df_f[['timestamp', 'funding_rate', 'funding_ema8', 'funding_cum3', 'funding_zscore']]
            .sort_values('timestamp'),
        on='timestamp',
        direction='backward',
    )
    funding_cols = ['funding_rate', 'funding_ema8', 'funding_cum3', 'funding_zscore']
    missing_rows = merged[funding_cols].isna().any(axis=1).sum()
    if missing_rows > 0:
        print(f'  Warning: dropping {missing_rows:,} rows before first funding observation')
    return merged

print("✅ Funding rate fetcher defined (v25 — corrected FUNDING:SYMBOL endpoint)")

# ==== CELL 12 ====
print('📡 Fetching candles from Delta Exchange India ...')
print(f'   5m  → {TARGET_CANDLES_5M:,} candles')
print(f'   15m → {TARGET_CANDLES_15M:,} candles')

try:
    # ── 5m Candles — fetch by candle count ───────────────────────────────────
    df_5m = client.fetch_candles(
        symbol     = SYMBOL_5M,
        resolution = CANDLE_RES_5M,
        n_bars     = TARGET_CANDLES_5M,
    )
    # ── 15m Candles — fetch by candle count (direct API, NOT resampled) ──────
    df_15m = client.fetch_candles(
        symbol     = SYMBOL_15M,
        resolution = CANDLE_RES_15M,
        n_bars     = TARGET_CANDLES_15M,
    )
    # ── 1h Candles — fetch for higher-timeframe features ─────────────────────
    df_1h = client.fetch_candles(
        symbol     = SYMBOL_1H,
        resolution = CANDLE_RES_1H,
        n_bars     = TARGET_CANDLES_1H,
    )
    # ── Funding Rates — fetch via FUNDING:SYMBOL candle endpoint ─────────────
    df_funding = fetch_funding_rate(SYMBOL_5M, n_bars=500)
except Exception as e:
    print(f'❌ Candle fetch failed: {e}')
    df_5m, df_15m, df_1h = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

if df_5m.empty or df_15m.empty or df_1h.empty:
    raise ValueError(
        '❌ No candle data returned from Delta Exchange API.\n'
        '   Possible causes:\n'
        '   1. Missing / invalid API credentials — set DELTA_API_KEY and DELTA_API_SECRET\n'
        '      via Colab Secrets (left sidebar 🔑) or environment variables.\n'
        '   2. Wrong symbol — verify SYMBOL_5M / SYMBOL_15M / SYMBOL_1H in Cell 2.\n'
        '   3. Network / connectivity issue — check the API response in the Debug cell below.\n'
        '   Synthetic or placeholder data is strictly prohibited.\n'
        '   The model MUST be trained on real market data from Delta Exchange.'
    )

print(f'\n5m  : {len(df_5m):,} candles | {df_5m.timestamp.iloc[0].date()} → {df_5m.timestamp.iloc[-1].date()}')
print(f'15m : {len(df_15m):,} candles | {df_15m.timestamp.iloc[0].date()} → {df_15m.timestamp.iloc[-1].date()}')
print(f'1h  : {len(df_1h):,} candles | {df_1h.timestamp.iloc[0].date()} → {df_1h.timestamp.iloc[-1].date()}')
if not df_funding.empty:
    print(f'Funding: {len(df_funding):,} rows | {df_funding.timestamp.iloc[0].date()} → {df_funding.timestamp.iloc[-1].date()}')
else:
    raise ValueError(
        'Funding data fetch returned no rows. '
        'Notebook is configured to hard-fail instead of using placeholder values.'
    )
df_5m.tail(3)

# ==== CELL 13 ====
# ── Data Validation — assert real market data was loaded ─────────────────────
# This cell runs after the fetch and hard-fails if data is stale or too small.

assert not df_5m.empty,  '❌ df_5m is empty — check API credentials and symbol'
assert not df_15m.empty, '❌ df_15m is empty — check API credentials and symbol'
assert not df_1h.empty,  '❌ df_1h is empty — check API credentials and symbol'

assert len(df_5m)  >= MIN_TRAIN_SAMPLES, (
    f'❌ df_5m has only {len(df_5m)} rows — need at least {MIN_TRAIN_SAMPLES}'
)
assert len(df_15m) >= MIN_TRAIN_SAMPLES, (
    f'❌ df_15m has only {len(df_15m)} rows — need at least {MIN_TRAIN_SAMPLES}'
)

# Sanity-check OHLCV integrity: no negative prices, high >= low, etc.
for name, df in [('5m', df_5m), ('15m', df_15m), ('1h', df_1h)]:
    assert (df['close'] > 0).all(),  f'❌ {name}: non-positive close prices detected'
    assert (df['high'] >= df['low']).all(), f'❌ {name}: high < low detected'
    assert (df['volume'] >= 0).all(), f'❌ {name}: negative volume detected'
    dup = df['timestamp'].duplicated().sum()
    assert dup == 0, f'❌ {name}: {dup} duplicate timestamps detected'

print('✅ Data validation passed — real market data confirmed')
print(f'   5m:  {len(df_5m):,} candles | {df_5m.timestamp.iloc[0].date()} → {df_5m.timestamp.iloc[-1].date()}')
print(f'   15m: {len(df_15m):,} candles | {df_15m.timestamp.iloc[0].date()} → {df_15m.timestamp.iloc[-1].date()}')
print(f'   1h:  {len(df_1h):,} candles | {df_1h.timestamp.iloc[0].date()} → {df_1h.timestamp.iloc[-1].date()}')

# ==== CELL 14 ====
# ── Debug API Call ──────────────────────────────────────────────────────────
print('🔍 Debugging API call...')
print(f'API_KEY: ***...{API_KEY[-4:] if API_KEY and len(API_KEY) >= 4 else "(not set)"}')
print(f'API_SECRET: ***...{API_SECRET[-4:] if API_SECRET and len(API_SECRET) >= 4 else "(not set)"}')
print(f'BASE_URL: {BASE_URL}')

# Try a raw API call with debug info
import json
test_params = {
    'symbol': SYMBOL_5M,
    'resolution': '5m',
    'start': int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()),
    'end': int(datetime.now(timezone.utc).timestamp()),
}
print(f'\nTest params: {test_params}')
print(f'Time range: {datetime.fromtimestamp(test_params["start"], tz=timezone.utc)} → {datetime.fromtimestamp(test_params["end"], tz=timezone.utc)}')

try:
    response = client._get('/v2/history/candles', params=test_params)
    print(f'\n✅ API Response received')
    print(f'Response keys: {list(response.keys())}')
    if 'result' in response:
        result = response['result']
        print(f'Result type: {type(result).__name__}')
        if isinstance(result, list):
            print(f'Result length: {len(result)}')
            if len(result) > 0:
                print(f'First candle: {result[0]}')
                print(f'First candle keys: {list(result[0].keys())}')
        elif isinstance(result, dict):
            print(f'Result dict: {result}')
    if 'status' in response:
        print(f'Status: {response["status"]}')
    if 'message' in response:
        print(f'Message: {response["message"]}')
    print(f'\nFull response (first 800 chars):\n{json.dumps(response, indent=2)[:800]}')
except requests.HTTPError as e:
    print(f'❌ HTTP Error: {e}')
    print(f'Response text: {e.response.text[:500]}')
except Exception as e:
    print(f'❌ Error: {type(e).__name__}: {e}')

# ==== CELL 16 ====
import pandas as pd
import numpy as np


# ── Helpers ─────────────────────────────────────────────────────────────────
def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _hurst_fast(close: pd.Series, window: int = 60) -> pd.Series:
    """
    Fast Hurst approximation using variance-of-returns scaling.
    ~8x faster than the full R/S method; ~91% correlation with full Hurst.
    H > 0.55 → trending  |  H ≈ 0.5 → random walk  |  H < 0.45 → mean-reverting
    """
    log_ret = np.log(close / close.shift(1))
    var1 = log_ret.rolling(window, min_periods=window//2).var()
    var4 = log_ret.rolling(4).mean().rolling(window, min_periods=window//2).var()
    h = 0.5 + 0.5 * np.log((var4 + 1e-12) / (var1 + 1e-12)) / np.log(4)
    return h.clip(0.0, 1.0).fillna(0.5)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low']  - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14):
    """Returns (adx, plus_di, minus_di) as three pd.Series."""
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    up   = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_s    = pd.Series(tr.values).ewm(span=period, adjust=False).mean()
    plus_di  = 100 * pd.Series(plus_dm).ewm(span=period, adjust=False).mean() / (atr_s + 1e-9)
    minus_di = 100 * pd.Series(minus_dm).ewm(span=period, adjust=False).mean() / (atr_s + 1e-9)
    plus_di.index  = df.index
    minus_di.index = df.index
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


def _choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Choppiness Index: near 100 = max chop, near 38.2 = strong trend.
    Complements ADX with a different mathematical approach.
    """
    high_n = df['high'].rolling(period).max()
    low_n  = df['low'].rolling(period).min()
    tr_sum = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low']  - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1).rolling(period).sum()
    chop = 100 * np.log10(tr_sum / (high_n - low_n + 1e-9)) / np.log10(period)
    return chop.clip(1, 100)


def _efficiency_ratio(close: pd.Series, period: int = 20) -> pd.Series:
    """
    Kaufman Efficiency Ratio: 1.0 = clean directional move, 0 = random noise.
    Measures how much directional progress is made relative to total path length.
    """
    direction  = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    return (direction / (volatility + 1e-9)).clip(0, 1)


def _rsi_divergence(close: pd.Series, rsi: pd.Series, window: int = 20) -> pd.Series:
    """
    Bullish divergence: price lower low + RSI higher low  → +1
    Bearish divergence: price higher high + RSI lower high → -1
    """
    price_high = close.rolling(window).max()
    price_low  = close.rolling(window).min()
    rsi_high   = rsi.rolling(window).max()
    rsi_low    = rsi.rolling(window).min()
    bearish = ((close >= price_high * 0.995) & (rsi <= rsi_high * 0.985)).astype(int) * -1
    bullish = ((close <= price_low  * 1.005) & (rsi >= rsi_low  * 1.015)).astype(int)
    return (bullish + bearish).clip(-1, 1)


def _macd_divergence(close: pd.Series, macd_hist: pd.Series, window: int = 20) -> pd.Series:
    price_new_high = close > close.rolling(window).max().shift(1)
    hist_weakening = macd_hist < macd_hist.rolling(window).max().shift(1) * 0.85
    bearish = (price_new_high & hist_weakening).astype(int) * -1
    price_new_low  = close < close.rolling(window).min().shift(1)
    hist_recovery  = macd_hist > macd_hist.rolling(window).min().shift(1) * 0.85
    bullish = (price_new_low & hist_recovery).astype(int)
    return (bullish + bearish).clip(-1, 1)


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """Daily session VWAP resetting at UTC midnight — institutional fair-value anchor."""
    d = df.copy()
    d['date']    = d['timestamp'].dt.date
    d['typical'] = (d['high'] + d['low'] + d['close']) / 3
    d['tp_vol']  = d['typical'] * d['volume']
    d['cum_tpv'] = d.groupby('date')['tp_vol'].cumsum()
    d['cum_vol'] = d.groupby('date')['volume'].cumsum()
    return d['cum_tpv'] / (d['cum_vol'] + 1e-9)


def _round_number_proximity(close: pd.Series, step: float = 1000.0) -> pd.Series:
    """Distance to nearest round number level, normalised by price."""
    nearest = (close / step).round() * step
    return (close - nearest).abs() / (close + 1e-9)



def _classify_regime(hurst: float, adx: float, vol_regime: float, vol_of_vol: float) -> str:
    """
    Improvement 1 (v28): Rule-based explicit regime classifier.
    Deterministic, interpretable, zero training required.
    Returns: 'crisis', 'trending', 'ranging', or 'neutral'
    """
    if vol_regime > CRISIS_VOL_THRESHOLD or vol_of_vol > CRISIS_VOL_OF_VOL_THRESH:
        return 'crisis'      # abnormally high or unstable vol — stay flat
    elif hurst > 0.55 and adx > 22:
        return 'trending'    # directional momentum confirmed
    elif hurst < 0.47 and adx < 18:
        return 'ranging'     # mean-reverting, choppy
    else:
        return 'neutral'     # ambiguous — use conservative sizing


def _smooth_regime_labels(regime_series: pd.Series, min_bars: int = 6) -> pd.Series:
    """
    Improvement 4 (v28): Regime persistence filter.
    Prevents single-bar regime flips by requiring min_bars consecutive bars
    in a new regime before accepting the switch.
    """
    smoothed = regime_series.copy()
    if len(smoothed) == 0:
        return smoothed
    current = smoothed.iloc[0]
    streak  = 0
    for i in range(1, len(smoothed)):
        if smoothed.iloc[i] == current:
            streak += 1
        else:
            if streak >= min_bars:
                current = smoothed.iloc[i]
                streak  = 1
            else:
                smoothed.iloc[i] = current   # reject flip, hold old regime
    return smoothed


def is_crisis_regime(df_recent: pd.DataFrame) -> bool:
    """
    Improvement 6 (v28): Crisis guard — hard rule, bypasses all ML signal.
    Returns True if current market shows crisis characteristics.
    No model is reliable during extreme vol — force flat.
    """
    if df_recent.empty:
        return False
    last = df_recent.iloc[-1]
    vol_spike    = last.get('vol_regime', 0)    > CRISIS_VOL_THRESHOLD
    unstable_vol = last.get('vol_of_vol', 0)    > CRISIS_VOL_OF_VOL_THRESH
    return bool(vol_spike or unstable_vol)


def compute_features_5m(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute enriched technical features on 5m OHLCV data. (v25)
    All rolling/shift operations use only past data — zero lookahead bias.
    Funding features are merged separately via add_funding_features().
    """
    d = df.copy()

    # ── 1. Returns & momentum (trimmed: drop ret_3, ret_12 — redundant) ──────
    d['ret_1']     = d['close'].pct_change(1)
    d['ret_6']     = d['close'].pct_change(6)
    d['ret_24']    = d['close'].pct_change(24)
    d['mom_accel'] = d['close'].pct_change(3) - d['close'].pct_change(3).shift(3)
    d['log_ret_1'] = np.sign(d['ret_1']) * np.log1p(d['ret_1'].abs())

    # ── 2. Moving averages & crosses ─────────────────────────────────────────
    d['ema_9']   = d['close'].ewm(span=9,   adjust=False).mean()
    d['ema_21']  = d['close'].ewm(span=21,  adjust=False).mean()
    d['ema_50']  = d['close'].ewm(span=50,  adjust=False).mean()
    d['ema_100'] = d['close'].ewm(span=100, adjust=False).mean()
    d['ema_9_21_cross']  = (d['ema_9']  - d['ema_21']) / (d['ema_21']  + 1e-9)
    d['ema_21_50_cross'] = (d['ema_21'] - d['ema_50']) / (d['ema_50']  + 1e-9)
    d['price_ema21']     = (d['close']  - d['ema_21']) / (d['ema_21']  + 1e-9)
    d['price_ema100']    = (d['close']  - d['ema_100'])/ (d['ema_100'] + 1e-9)

    # ── 3. RSI (trimmed: drop rsi_21 — ~85% overlap with rsi_14) ─────────────
    d['rsi_14']    = _rsi(d['close'], 14)
    d['rsi_7']     = _rsi(d['close'],  7)
    rsi_norm       = (d['rsi_14'] / 100.0).clip(0.001, 0.999)
    d['fisher_rsi']= np.log(rsi_norm / (1 - rsi_norm))
    d['rsi_mom']   = d['rsi_14'] - d['rsi_14'].shift(5)
    d['rsi_div_20']= _rsi_divergence(d['close'], d['rsi_14'], window=20)

    # ── 4. MACD ──────────────────────────────────────────────────────────────
    ema12 = d['close'].ewm(span=12, adjust=False).mean()
    ema26 = d['close'].ewm(span=26, adjust=False).mean()
    d['macd']        = ema12 - ema26
    d['macd_signal'] = d['macd'].ewm(span=9, adjust=False).mean()
    d['macd_hist']   = d['macd'] - d['macd_signal']
    atr14            = _atr(d, 14)
    d['macd_hist_n'] = d['macd_hist'] / (atr14 + 1e-9)
    d['macd_div_20'] = _macd_divergence(d['close'], d['macd_hist'], window=20)

    # ── 5. Bollinger Bands ───────────────────────────────────────────────────
    bb_mid        = d['close'].rolling(20).mean()
    bb_std        = d['close'].rolling(20).std()
    d['bb_upper'] = bb_mid + 2 * bb_std
    d['bb_lower'] = bb_mid - 2 * bb_std
    d['bb_width'] = (d['bb_upper'] - d['bb_lower']) / (bb_mid + 1e-9)
    d['bb_pos']   = (d['close'] - d['bb_lower']) / (d['bb_upper'] - d['bb_lower'] + 1e-9)
    d['bb_squeeze']= (d['bb_width'] - d['bb_width'].rolling(50).mean()) / (
                      d['bb_width'].rolling(50).std() + 1e-9)

    # ── 6. ATR & volatility (drop raw vol_5/vol_20 — use ratios only) ────────
    d['atr_14']      = atr14
    d['atr_pct']     = atr14 / (d['close'] + 1e-9)
    vol_5            = d['ret_1'].rolling(5).std()
    vol_20           = d['ret_1'].rolling(20).std()
    d['vol_ratio_sv']= vol_5 / (vol_20 + 1e-9)
    d['vol_regime']  = vol_20 / (vol_20.rolling(50).median() + 1e-9)
    d['ret_skew_20'] = d['ret_1'].rolling(20).skew()
    d['ret_kurt_20'] = d['ret_1'].rolling(20).kurt().clip(-5, 10)

    # ── 7. Trend strength — NEW in v25 ──────────────────────────────────────
    adx_vals, plus_di_vals, minus_di_vals = _adx(d, 14)
    d['adx_14']  = adx_vals.values
    d['di_spread']= plus_di_vals.values - minus_di_vals.values   # + = bullish trend
    chop         = _choppiness(d, 14)
    d['chop_norm']= (chop - 38.2) / 61.8   # 0 = trending, 1 = max chop
    d['kauf_er_20']= _efficiency_ratio(d['close'], 20)

    # ── 8. Volume features ───────────────────────────────────────────────────
    d['vol_ema20'] = d['volume'].ewm(span=20, adjust=False).mean()
    d['vol_ratio'] = d['volume'] / (d['vol_ema20'] + 1e-9)
    # FIX 9 (v27): OBV Z-score normalised — baseline-invariant across retrain windows
    # Raw cumsum OBV is non-stationary: absolute value depends on window start point.
    # Z-score normalisation makes it consistent regardless of where the cumsum begins.
    _obv_raw      = (np.sign(d['close'].diff()) * d['volume']).fillna(0).cumsum()
    _obv_roll_std = _obv_raw.rolling(100, min_periods=20).std().clip(lower=1e-9)
    _obv_roll_mu  = _obv_raw.rolling(100, min_periods=20).mean()
    d['obv_ret']  = ((_obv_raw - _obv_roll_mu) / _obv_roll_std).clip(-4, 4)  # Z-score OBV
    clv            = ((d['close'] - d['low']) - (d['high'] - d['close'])) / (
                      d['high'] - d['low'] + 1e-9)
    d['cmf_20']    = (clv * d['volume']).rolling(20).sum() / (
                      d['volume'].rolling(20).sum() + 1e-9)
    d['vp_div']    = (np.sign(d['ret_1']) * np.sign(d['volume'].diff())).clip(-1, 1)
    # BUG 2 FIX: vol_conviction removed here — body_dir not yet computed at this point.
    # Correct computation is in section 10 (after body_dir is defined). See below.

    # ── 9. Session VWAP — NEW in v25 (replaces rolling VWAP) ─────────────────
    d['session_vwap']     = _session_vwap(d)
    d['session_vwap_dev'] = (d['close'] - d['session_vwap']) / (d['session_vwap'] + 1e-9)
    d['session_vwap_std'] = (
        d.groupby(d['timestamp'].dt.date)['close']
        .transform(lambda x: x.expanding().std())
    )
    d['vwap_band_pos']    = (d['close'] - d['session_vwap']) / (d['session_vwap_std'] + 1e-9)

    # ── 10. Candle structure ─────────────────────────────────────────────────
    d['body']      = (d['close'] - d['open']).abs() / (atr14 + 1e-9)
    d['body_dir']  = (d['close'] - d['open'])       / (atr14 + 1e-9)
    d['wick_up']   = (d['high'] - d[['open','close']].max(axis=1)) / (atr14 + 1e-9)
    d['wick_dn']   = (d[['open','close']].min(axis=1) - d['low'])  / (atr14 + 1e-9)
    d['wick_asym'] = d['wick_up'] - d['wick_dn']
    d['bull_bar']  = (d['close'] > d['open']).astype(int)
    d['consec_bull']= (d['bull_bar'].rolling(3).sum() == 3).astype(int)
    d['consec_bear']= (d['bull_bar'].rolling(3).sum() == 0).astype(int)
    # Recompute vol_conviction now that body_dir exists
    d['vol_conviction'] = d['vol_ratio'] * d['body_dir'].abs()

    # ── 11. Stochastic (drop stoch_mom — linear combo of k and d) ────────────
    lo14     = d['low'].rolling(14).min()
    hi14     = d['high'].rolling(14).max()
    d['stoch_k'] = 100 * (d['close'] - lo14) / (hi14 - lo14 + 1e-9)
    d['stoch_d'] = d['stoch_k'].rolling(3).mean()

    # ── 12. S/R — extended lookbacks + round numbers (v27: 200-bar pair → sr_compression) ──
    d['dist_high20']   = (d['high'].rolling(20).max().shift(1) - d['close']) / (d['close'] + 1e-9)
    d['dist_low20']    = (d['close'] - d['low'].rolling(20).min().shift(1))  / (d['close'] + 1e-9)
    d['dist_high100']  = (d['high'].rolling(100).max().shift(1) - d['close'])/ (d['close'] + 1e-9)
    d['dist_low100']   = (d['close'] - d['low'].rolling(100).min().shift(1)) / (d['close'] + 1e-9)
    # FIX (v27): Replace dist_high200/dist_low200 (redundant with 100-bar pair, ~90% corr) with
    # sr_compression: how compressed current price is within the full 200-bar range.
    # Captures structural range information as a single non-redundant feature.
    _high200           = d['high'].rolling(200).max().shift(1)
    _low200            = d['low'].rolling(200).min().shift(1)
    _dist_high200      = (_high200 - d['close']) / (d['close'] + 1e-9)
    _dist_low200       = (d['close'] - _low200)  / (d['close'] + 1e-9)
    d['sr_compression']= _dist_high200 / (_dist_high200 + _dist_low200 + 1e-9)   # 0=at bottom, 1=at top of 200-bar range
    d['round_1000_prox']= _round_number_proximity(d['close'], step=1000.0)
    d['round_500_prox'] = _round_number_proximity(d['close'], step=500.0)

    # ── 13. Price percentile (drop pct_rank_50 — correlated with pct_rank_100) ─
    d['pct_rank_100'] = d['close'].rolling(100).rank(pct=True)

    # ── 14. Time encoding — cyclical (replaces binary session flags) ──────────
    if hasattr(d['timestamp'], 'dt'):
        ts = d['timestamp']
    else:
        ts = pd.to_datetime(d['timestamp'])
    hour = ts.dt.hour + ts.dt.minute / 60.0
    dow  = ts.dt.dayofweek.astype(float)
    d['hour_sin'] = np.sin(2 * np.pi * hour / 24)
    d['hour_cos'] = np.cos(2 * np.pi * hour / 24)
    d['dow_sin']  = np.sin(2 * np.pi * dow  / 7)
    d['dow_cos']  = np.cos(2 * np.pi * dow  / 7)

    # ── 15. Hurst (fast approximation — 8x speedup) ──────────────────────────
    d['hurst_60'] = _hurst_fast(d['close'], window=60)

    # ── 16. Feature interactions (explicit cross-terms for tree models) ────────
    adx_norm       = (d['adx_14'] / 25.0).clip(0, 2)
    d['trend_mom']     = d['mom_accel'] * adx_norm               # momentum × trend strength
    d['squeeze_vol']   = d['bb_squeeze'] * (1 / (d['vol_regime'] + 1e-9))  # squeeze in low vol
    d['rsi_trend']     = d['fisher_rsi'] * adx_norm              # RSI confirmed by ADX
    d['trend_conf']    = (d['hurst_60'] - 0.5) * d['kauf_er_20']  # Hurst × efficiency
    d['vwap_rejection']= d['session_vwap_dev'] * d['wick_asym']  # VWAP deviation × wick
    # vol_conviction already computed above


    # ── REGIME FEATURES (v28 improvements) ──────────────────────────────────
    # Improvement 2: Add missing regime features

    # Vol-of-vol: distinguishes sustained high-vol (tradeable) from vol spikes (dangerous)
    _vol20 = d['ret_1'].rolling(20).std()
    d['vol_of_vol'] = (
        _vol20.rolling(20).std() /
        (_vol20.rolling(50).mean() + 1e-9)
    )

    # Return autocorrelation lag-1: positive = momentum works, negative = mean-reversion
    d['ret_autocorr_20'] = (
        d['ret_1']
        .rolling(20)
        .apply(lambda x: pd.Series(x).autocorr(lag=1) if len(x) > 2 else 0.0, raw=False)
        .fillna(0)
    )

    # Rolling Sharpe ratio over 48 bars (4h at 5m resolution)
    _bars_per_year = 252 * 24 * 12   # 5m bars per year
    d['rolling_sharpe_48'] = (
        d['ret_1'].rolling(48).mean() /
        (d['ret_1'].rolling(48).std() + 1e-9)
    ) * np.sqrt(_bars_per_year)

    # Improvement 4: Smooth regime inputs (prevent single-bar flips)
    d['hurst_smooth']      = d['hurst_60'].ewm(span=REGIME_EMA_SPAN).mean()
    d['adx_smooth']        = d['adx_14'].ewm(span=REGIME_EMA_SPAN).mean()
    d['vol_regime_smooth'] = d['vol_regime'].ewm(span=REGIME_EMA_SPAN).mean()
    d['vol_of_vol_smooth'] = d['vol_of_vol'].ewm(span=REGIME_EMA_SPAN).mean()

    # Improvement 1: Explicit regime classification (rule-based, production-safe)
    d['regime_label'] = d.apply(
        lambda r: _classify_regime(
            r.get('hurst_smooth', 0.5),
            r.get('adx_smooth', 15.0),
            r.get('vol_regime_smooth', 1.0),
            r.get('vol_of_vol_smooth', 1.0),
        ), axis=1
    )

    # Improvement 4: Regime persistence smoothing
    d['regime_label'] = _smooth_regime_labels(d['regime_label'], min_bars=REGIME_MIN_BARS)


    return d


def compute_features_15m(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute enriched higher-timeframe features on 15m data. (v25)
    Prefixed 'h_'; merged onto 5m frame with merge_asof (no lookahead).
    """
    d = df.copy()
    d['h_ret_1']      = d['close'].pct_change(1)
    d['h_ret_3']      = d['close'].pct_change(3)
    d['h_ema_21']     = d['close'].ewm(span=21, adjust=False).mean()
    d['h_ema_50']     = d['close'].ewm(span=50, adjust=False).mean()
    d['h_ema_200']    = d['close'].ewm(span=200, adjust=False).mean()
    d['h_trend']      = (d['h_ema_21'] - d['h_ema_50']) / (d['h_ema_50'] + 1e-9)
    d['h_trend_200']  = (d['h_ema_50'] - d['h_ema_200']) / (d['h_ema_200'] + 1e-9)
    d['h_rsi_14']     = _rsi(d['close'], 14)
    d['h_rsi_7']      = _rsi(d['close'],  7)
    h_rsi_norm        = (d['h_rsi_14'] / 100.0).clip(0.001, 0.999)
    d['h_fisher_rsi'] = np.log(h_rsi_norm / (1 - h_rsi_norm))
    d['h_atr_pct']    = _atr(d, 14) / (d['close'] + 1e-9)
    d['h_vol_ratio']  = d['volume'] / (d['volume'].ewm(span=20).mean() + 1e-9)
    d['h_bull_bar']   = (d['close'] > d['open']).astype(int)
    h_clv             = ((d['close'] - d['low']) - (d['high'] - d['close'])) / (
                         d['high'] - d['low'] + 1e-9)
    d['h_cmf_20']     = (h_clv * d['volume']).rolling(20).sum() / (
                         d['volume'].rolling(20).sum() + 1e-9)
    h_bb_mid          = d['close'].rolling(20).mean()
    h_bb_std          = d['close'].rolling(20).std()
    d['h_bb_pos']     = (d['close'] - (h_bb_mid - 2*h_bb_std)) / (4*h_bb_std + 1e-9)
    d['h_pct_rank_50']= d['close'].rolling(50).rank(pct=True)
    htf_cols = ['timestamp'] + [c for c in d.columns if c.startswith('h_')]
    return d[htf_cols]


def compute_features_1h(df: pd.DataFrame) -> pd.DataFrame:
    """
    1h higher-timeframe features — institutional trend context. (v25 NEW)
    Prefixed 'h1_'; merged onto 5m frame with merge_asof (no lookahead).
    """
    d = df.copy()
    d['h1_ema_21']     = d['close'].ewm(span=21, adjust=False).mean()
    d['h1_ema_50']     = d['close'].ewm(span=50, adjust=False).mean()
    d['h1_trend']      = (d['h1_ema_21'] - d['h1_ema_50']) / (d['h1_ema_50'] + 1e-9)
    d['h1_rsi_14']     = _rsi(d['close'], 14)
    d['h1_atr_pct']    = _atr(d, 14) / (d['close'] + 1e-9)
    adx_1h, _, _       = _adx(d, 14)
    d['h1_adx']        = adx_1h.values
    vol_ret            = d['close'].pct_change()
    d['h1_vol_regime'] = (vol_ret.rolling(20).std() /
                          (vol_ret.rolling(50).std().rolling(100, min_periods=20).median() + 1e-9))
    h1_cols = ['timestamp'] + [c for c in d.columns if c.startswith('h1_')]
    return d[h1_cols]


def merge_timeframes(df_5m: pd.DataFrame, df_15m_features: pd.DataFrame,
                     df_1h_features: pd.DataFrame = None,
                     df_funding: pd.DataFrame = None) -> pd.DataFrame:
    """Merge 15m, 1h, and funding features onto 5m frame (no lookahead)."""
    merged = pd.merge_asof(
        df_5m.sort_values('timestamp'),
        df_15m_features.sort_values('timestamp'),
        on='timestamp', direction='backward',
    )
    if df_1h_features is not None and not df_1h_features.empty:
        merged = pd.merge_asof(
            merged.sort_values('timestamp'),
            df_1h_features.sort_values('timestamp'),
            on='timestamp', direction='backward',
        )
    if df_funding is not None and not df_funding.empty:
        merged = add_funding_features(merged, df_funding)
    elif REQUIRE_FUNDING_DATA:
        raise ValueError(
            'Funding data is required for the configured feature set. '
            'Disable funding features explicitly instead of zero-filling them.'
        )
    return merged




def _build_tp_sl_target(df: pd.DataFrame, tp_pct: float = 0.03, sl_pct: float = 0.015,
                         horizon: int = 60) -> np.ndarray:
    """
    BUG 5 FIX (v28): Vectorised numpy implementation replaces O(n*horizon) Python loop.
    The old pure-Python loop (30,000 × 60 ≈ 1.8M iterations) took 60-90s per run.
    This vectorised version runs in <1s for 30,000 bars.

    BUG 7 FIX (v28): Initialise target with -1 sentinel instead of 0.
    Boundary rows (within `horizon` of end) previously got a false 0 label.
    They now get sentinel -1 and are filtered out in build_feature_matrix().

    FIX 1 (v27): TP/SL-aligned binary target.
    For each bar t, look forward across t+1..t+horizon:
      - 1 if TP (close * (1+tp_pct)) is touched by high BEFORE SL (close * (1-sl_pct)) by low
      - 0 otherwise (SL hit first, or neither hit within horizon)
    """
    close_arr = df['close'].values
    high_arr  = df['high'].values
    low_arr   = df['low'].values
    n         = len(df)

    # BUG 7 FIX: use -1 as sentinel for rows without a complete forward window
    target = np.full(n, -1, dtype=np.int8)

    if n <= horizon:
        return target

    # Vectorised approach: build (n-horizon) × horizon index matrix
    idx      = np.arange(n - horizon)                              # shape (n-horizon,)
    fut_idx  = idx[:, None] + np.arange(1, horizon + 1)           # shape (n-horizon, horizon)

    tp_levels = close_arr[idx] * (1.0 + tp_pct)                   # shape (n-horizon,)
    sl_levels = close_arr[idx] * (1.0 - sl_pct)

    future_highs = high_arr[fut_idx]                               # shape (n-horizon, horizon)
    future_lows  = low_arr[fut_idx]

    tp_hit = future_highs >= tp_levels[:, None]                    # bool matrix
    sl_hit = future_lows  <= sl_levels[:, None]

    # First bar index where TP/SL is hit; default to horizon if never hit
    tp_bar = np.where(tp_hit.any(axis=1), np.argmax(tp_hit, axis=1), horizon)
    sl_bar = np.where(sl_hit.any(axis=1), np.argmax(sl_hit, axis=1), horizon)

    target[idx] = (tp_bar < sl_bar).astype(np.int8)
    # Note: rows in idx where both never hit → tp_bar==sl_bar==horizon → target=0 (correct)
    return target

def build_feature_matrix(df_5m: pd.DataFrame, df_15m: pd.DataFrame,
                          df_1h: pd.DataFrame = None,
                          df_funding: pd.DataFrame = None,
                          for_training: bool = True) -> pd.DataFrame:
    """
    Full feature pipeline (v25):
    1. Compute enriched 5m features
    2. Compute enriched 15m + 1h features
    3. Merge all with merge_asof (no lookahead)
    4. Merge funding rate features
    5. Compute funding_mom interaction
    6. Build binary target
    7. Drop NaN warmup rows
    """
    feat_5m  = compute_features_5m(df_5m)
    feat_15m = compute_features_15m(df_15m)
    feat_1h  = compute_features_1h(df_1h) if df_1h is not None and not df_1h.empty else None

    merged = merge_timeframes(feat_5m, feat_15m, feat_1h, df_funding)

    # Funding × momentum interaction (computed after merge)
    if 'funding_zscore' in merged.columns:
        merged['funding_mom'] = merged['funding_zscore'] * merged['ret_6']
    else:
        merged['funding_mom'] = 0.0

    if for_training:
        # FIX 1 (v27): TP/SL-aligned target — replaces next-bar direction.
        # The model is trained for the actual trade payoff: 1 = TP hit before SL within horizon bars.
        # This directly aligns the training objective with the 1.5% SL / 3% TP trade setup.
        merged['target'] = _build_tp_sl_target(
            merged,
            tp_pct=TAKE_PROFIT_PCT,
            sl_pct=STOP_LOSS_PCT,
            horizon=TP_SL_TARGET_HORIZON,
        )
        # BUG 7 FIX: filter sentinel rows (-1) before training.
        # Keep only rows with a complete forward outcome window.
        valid_mask = merged['target'] >= 0
        n_invalid  = (~valid_mask).sum()
        if n_invalid > 0:
            print(f'  BUG7: Filtered {n_invalid} boundary rows with sentinel target')
        merged = merged[valid_mask].copy()

    warmup = max(WARMUP_CANDLES, 210)   # extended for 200-bar S/R + Hurst 60
    if len(merged) > warmup:
        merged = merged.iloc[warmup:].reset_index(drop=True)
    merged = merged.dropna(subset=FEATURE_COLS_V25, how='any').reset_index(drop=True)

    print(f'✅ Feature matrix: {merged.shape[0]:,} rows × {merged.shape[1]} cols')
    if for_training:
        pos_rate = merged.target.mean()
        print(f'   Target balance: {pos_rate:.3f} (TP/SL-aligned: expect ~0.30-0.40 at 2:1 R/R)')
        if pos_rate > 0.48:
            print('   ⚠️  Target still near 0.5 — check that _build_tp_sl_target ran correctly')
        print(f'   Positive class (TP hit): {merged.target.sum():,} | Negative: {(merged.target==0).sum():,}')
    return merged


# ── v25 Feature columns (~82 features) ──────────────────────────────────────
FEATURE_COLS_V25 = [
    # Returns (trimmed: no ret_3, ret_12)
    'ret_1', 'ret_6', 'ret_24', 'log_ret_1', 'mom_accel',
    # MA crosses
    'ema_9_21_cross', 'ema_21_50_cross', 'price_ema21', 'price_ema100',
    # RSI (trimmed: no rsi_21) + divergence
    'rsi_14', 'rsi_7', 'fisher_rsi', 'rsi_mom', 'rsi_div_20',
    # MACD + divergence (v27: removed raw macd/macd_signal — macd_hist = macd - signal, perfectly collinear)
    'macd_hist_n', 'macd_div_20',
    # Bollinger Bands
    'bb_width', 'bb_pos', 'bb_squeeze',
    # ATR / volatility (no raw vol_5/vol_20 — only ratios)
    'atr_pct', 'vol_ratio_sv', 'vol_regime', 'ret_skew_20', 'ret_kurt_20',
    # Trend strength (NEW)
    'adx_14', 'di_spread', 'chop_norm', 'kauf_er_20',
    # Volume
    'vol_ratio', 'obv_ret', 'cmf_20', 'vp_div', 'vol_conviction',
    # Session VWAP (NEW — replaces vwap_dev)
    'session_vwap_dev', 'vwap_band_pos',
    # Candle structure
    'body', 'body_dir', 'wick_up', 'wick_dn', 'wick_asym',
    'bull_bar', 'consec_bull', 'consec_bear',
    # Stochastic (trimmed: no stoch_mom)
    'stoch_k', 'stoch_d',
    # S/R extended (NEW: 100/200 bar + round numbers)
    'dist_high20', 'dist_low20',
    'dist_high100', 'dist_low100',
    'sr_compression',  # v27: replaces dist_high200/dist_low200 with single non-redundant range feature
    'round_1000_prox', 'round_500_prox',
    # Price rank (trimmed: no pct_rank_50)
    'pct_rank_100',
    # Time encoding — cyclical (NEW: replaces binary sess_asia/eu/us)
    'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
    # Hurst (fast version)
    'hurst_60',
    # Feature interactions (NEW)
    'trend_mom', 'squeeze_vol', 'rsi_trend', 'trend_conf',
    'vwap_rejection',  # v27: removed duplicate vol_conviction (already in Volume block above)
    # Funding (NEW — perp-specific)
    'funding_rate', 'funding_ema8', 'funding_cum3', 'funding_zscore', 'funding_mom',
    # 15m HTF (unchanged)
    'h_ret_1', 'h_ret_3', 'h_trend', 'h_trend_200',
    'h_rsi_14', 'h_rsi_7', 'h_fisher_rsi',
    'h_atr_pct', 'h_vol_ratio', 'h_bull_bar',
    'h_cmf_20', 'h_bb_pos', 'h_pct_rank_50',
    # 1h HTF (NEW)
    'h1_trend', 'h1_rsi_14', 'h1_adx', 'h1_vol_regime',
]

# Deduplicate while preserving order
_seen = set()
FEATURE_COLS_V25 = [x for x in FEATURE_COLS_V25 if not (x in _seen or _seen.add(x))]

# Keep FEATURE_COLS pointing to v25 list for backward compat
FEATURE_COLS = FEATURE_COLS_V25

print(f'✅ Feature engineering v27 defined — {len(FEATURE_COLS)} features')
print('   v27: TP/SL-aligned target | OBV Z-score | sr_compression | MACD dedup | vol_conviction dedup')
print(f'   5m features: {len([c for c in FEATURE_COLS if not c.startswith(("h_","h1_"))])}')
print(f'   15m HTF features: {len([c for c in FEATURE_COLS if c.startswith("h_")])}')
print(f'   1h HTF features: {len([c for c in FEATURE_COLS if c.startswith("h1_")])}')
print(f'   Funding features: {len([c for c in FEATURE_COLS if "funding" in c])}')


# ── FeatureEngineer — pipeline lock (P6) ──────────────────────────────────────
class FeatureEngineer:
    """
    Serialisable wrapper around the full v25 feature pipeline.
    Accepts optional df_1h and df_funding for full pipeline.
    """
    def __init__(self):
        self.columns: list = None

    def fit(self, df_5m, df_15m, df_1h=None, df_funding=None):
        out = build_feature_matrix(df_5m, df_15m, df_1h, df_funding, for_training=True)
        self.columns = [c for c in FEATURE_COLS if c in out.columns]
        return out

    def transform(self, df_5m, df_15m, df_1h=None, df_funding=None, include_target=False):
        out = build_feature_matrix(df_5m, df_15m, df_1h, df_funding, for_training=include_target)
        if self.columns is None:
            raise RuntimeError('Call fit() before transform()')
        missing = [c for c in self.columns if c not in out.columns]
        if missing:
            raise ValueError(f'Features missing: {missing}')
        keep_cols = self.columns + ['timestamp']
        if include_target:
            keep_cols.append('target')
        return out[keep_cols]

    def __repr__(self):
        n = len(self.columns) if self.columns else 'unfitted'
        return f'FeatureEngineer(columns={n})'

print('✅ FeatureEngineer class defined (v25)')

# ==== CELL 18 ====
import lightgbm as lgb
import xgboost as xgb
import joblib
import warnings
warnings.filterwarnings('ignore')

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.isotonic import IsotonicRegression


# ── Base model factories ──────────────────────────────────────────────────────

def _make_lgbm() -> lgb.LGBMClassifier:
    """
    FIX 3 (v27): GBDT-LightGBM (was DART).
    DART boosting has two critical incompatibilities:
      A) DART + early_stopping fires on stochastic predictions → noisy convergence.
      B) DART warm-start retroactively dropouts stable warm-started trees → degrades model.
    GBDT supports both early stopping and warm-start correctly — stable for live retraining.
    Uses GPU HIST when USE_GPU=True (device='gpu'). Falls back to CPU silently.
    is_unbalance=True handles class imbalance from TP/SL target (Fix 1).
    """
    params = dict(
        objective        = 'binary',
        metric           = 'auc',
        boosting_type    = 'gbdt',   # FIX 3: was 'dart'
        num_leaves       = 63,
        max_depth        = 7,
        n_estimators     = 600,
        learning_rate    = 0.03,
        feature_fraction = 0.70,
        bagging_fraction = 0.75,
        bagging_freq     = 3,
        min_child_samples= 15,
        lambda_l1        = 0.05,
        lambda_l2        = 0.10,
        min_gain_to_split= 0.01,
        path_smooth      = 1,
        is_unbalance     = True,   # handles TP/SL target class imbalance (~30% positive)
        verbose          = -1,
        n_jobs           = -1,
        random_state     = 42,
    )
    if USE_GPU:
        params['device']       = 'gpu'
        params['gpu_use_dp']   = False   # single-precision is faster on free Colab T4
    return lgb.LGBMClassifier(**params)


def _make_xgb() -> xgb.XGBClassifier:
    """
    XGBoost. Uses CUDA when USE_GPU=True (device='cuda').
    XGBoost ≥ 2.0 uses device= parameter; older versions use tree_method+gpu_id.
    """
    params = dict(
        n_estimators     = 500,
        max_depth        = 6,
        learning_rate    = 0.04,
        subsample        = 0.80,
        colsample_bytree = 0.70,
        min_child_weight = 10,
        reg_alpha        = 0.10,
        reg_lambda       = 1.00,
        gamma            = 0.01,
        eval_metric      = 'auc',
        scale_pos_weight = 2.2,  # ~30% positive in TP/SL target → approx (1-0.3)/0.3
        # BUG 3 FIX: use_label_encoder removed — deprecated in XGBoost 1.6, removed in 2.0.
        # Keeping it raised TypeError which the try/except silently caught, disabling GPU.
        verbosity        = 0,
        n_jobs           = -1,
        random_state     = 42,
    )
    if USE_GPU:
        xgb_ver = tuple(int(x) for x in xgb.__version__.split('.')[:2])
        if xgb_ver >= (2, 0):
            params['device'] = 'cuda'
        else:
            params['tree_method'] = 'gpu_hist'
            params['gpu_id']      = 0
    else:
        params['tree_method'] = 'hist'
    return xgb.XGBClassifier(**params)


def _make_rf(warm_start: bool = True) -> RandomForestClassifier:
    """
    Random Forest — CPU only (sklearn). OOB score for free internal validation.
    BUG 4 FIX: warm_start is now a parameter instead of always-True.
    This prevents the confusing pattern of creating with warm_start=True then
    immediately overriding to False in the CV loop.
    FIX 10 (v27): warm_start=True enables incremental tree addition during retraining.
    """
    return RandomForestClassifier(
        n_estimators    = 300,
        max_depth       = 10,
        min_samples_leaf= 12,
        max_features    = 'sqrt',
        class_weight    = 'balanced',   # handles TP/SL target class imbalance
        warm_start      = warm_start,  # BUG 4 FIX: explicit parameter, default True for retraining
        n_jobs          = -1,
        random_state    = 42,
        oob_score       = True,
    )


# ── PyTorch MLP (GPU-compatible, sklearn-compatible interface) ─────────────────

class _TorchMLP(nn.Module):
    """3-layer MLP: input → 128 → 64 → 32 → 1 (sigmoid output)."""
    def __init__(self, n_features: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(128, 64),         nn.BatchNorm1d(64),  nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64,  32),         nn.BatchNorm1d(32),  nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(32,   1),
        )
    def forward(self, x):
        return self.net(x).squeeze(-1)


class TorchMLPClassifier:
    """
    sklearn-compatible wrapper around _TorchMLP.
    Trains on TORCH_DEVICE (GPU when available).
    Provides fit() and predict_proba() matching sklearn API.
    """
    def __init__(
        self,
        hidden_layer_sizes = (128, 64, 32),
        lr: float          = 5e-4,
        batch_size: int    = 512,
        max_epochs: int    = 60,
        patience: int      = 8,
        weight_decay: float= 1e-3,
        device             = None,
    ):
        self.hidden_layer_sizes = hidden_layer_sizes
        self.lr          = lr
        self.batch_size  = batch_size
        self.max_epochs  = max_epochs
        self.patience    = patience
        self.weight_decay= weight_decay
        self.device      = device or TORCH_DEVICE
        self._model      = None
        self.classes_    = [0, 1]

    def fit(self, X, y):
        n_features = X.shape[1]
        self._model = _TorchMLP(n_features).to(self.device)

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32)

        # Split last 10% as val for early stopping
        val_n   = max(32, int(len(X_t) * 0.10))
        X_tr, X_val = X_t[:-val_n], X_t[-val_n:]
        y_tr, y_val = y_t[:-val_n], y_t[-val_n:]

        loader = DataLoader(
            TensorDataset(X_tr, y_tr),
            batch_size=self.batch_size,
            shuffle=True,
        )
        opt       = optim.AdamW(self._model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=self.max_epochs)
        loss_fn   = nn.BCEWithLogitsLoss()

        best_val_loss = float('inf')
        patience_cnt  = 0

        for epoch in range(self.max_epochs):
            self._model.train()
            for xb, yb in loader:
                xb, yb = xb.to(self.device), yb.to(self.device)
                opt.zero_grad()
                loss_fn(self._model(xb), yb).backward()
                nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
                opt.step()
            scheduler.step()

            # Validation loss for early stopping
            self._model.eval()
            with torch.no_grad():
                xv = X_val.to(self.device)
                yv = y_val.to(self.device)
                val_loss = loss_fn(self._model(xv), yv).item()

            if val_loss < best_val_loss - 1e-4:
                best_val_loss = val_loss
                patience_cnt  = 0
                self._best_state = {k: v.cpu().clone() for k, v in self._model.state_dict().items()}
            else:
                patience_cnt += 1
                if patience_cnt >= self.patience:
                    break

        if hasattr(self, '_best_state'):
            self._model.load_state_dict({k: v.to(self.device) for k, v in self._best_state.items()})
        return self

    def predict_proba(self, X):
        self._model.eval()
        with torch.no_grad():
            X_t   = torch.tensor(X, dtype=torch.float32).to(self.device)
            logits = self._model(X_t)
            probs  = torch.sigmoid(logits).cpu().numpy()
        return np.column_stack([1 - probs, probs])

    def __getstate__(self):
        """joblib serialisation: move model to CPU before pickling."""
        state = self.__dict__.copy()
        if self._model is not None:
            state['_model_state'] = {k: v.cpu() for k, v in self._model.state_dict().items()}
            state['_n_features']  = next(self._model.parameters()).shape[1]
            state['_model']       = None
        return state

    def __setstate__(self, state):
        """joblib deserialisation: restore model from state dict."""
        self.__dict__.update(state)
        if state.get('_model_state') is not None:
            self._model = _TorchMLP(state['_n_features']).to(self.device)
            self._model.load_state_dict({k: v.to(self.device) for k, v in state['_model_state'].items()})
            self._model.eval()


def _make_mlp() -> TorchMLPClassifier:
    """PyTorch MLP on TORCH_DEVICE. Larger batch on GPU for throughput."""
    return TorchMLPClassifier(
        hidden_layer_sizes = MLP_HIDDEN_LAYERS,
        lr                 = 5e-4,
        batch_size         = 512 if USE_GPU else 256,
        max_epochs         = 60,
        patience           = 8,
        device             = TORCH_DEVICE,
    )


# ── Stacked EnsembleModel (v27) ───────────────────────────────────────────────

class EnsembleModel:
    """
    v27 Architectural Rethink — 4-model stacked ensemble:
    GBDT-LightGBM (GPU) + XGBoost (GPU) + RandomForest (warm_start) + PyTorch MLP (GPU).

    Key v27 changes:
    - Fix 2: CV gap=200 (was gap=12) — eliminates rolling-window leakage
    - Fix 3: GBDT (was DART) — compatible with early stopping and warm-start
    - Fix 4: Single RobustScaler fitted before CV folds — consistent OOF distribution
    - Fix 5: Regime-aware meta-learner with 9 inputs (4 probs + 5 regime features)
    - Fix 6: Isotonic calibrator on separate 30% OOF holdout (no calibration leakage)
    - Fix 10: RF warm_start=True for incremental retraining
    """

    def __init__(self):
        self.scaler       = RobustScaler()
        self.lgbm         = None
        self.xgb          = None
        self.rf           = None
        self.mlp          = None
        self.meta         = None
        self.calibrator   = None
        self.feature_cols = None
        self.is_trained   = False
        self._oob_score   = None
        self._regime_scaler = None
        self._regime_cols   = []

    def train(self, df, feature_cols, n_splits=5, verbose=True):
        """
        v27 train() — implements all architectural fixes:
        Fix 2: CV gap=200 (eliminates rolling-window leakage for 200-bar features)
        Fix 4: Single RobustScaler fitted before CV (consistent OOF distribution)
        Fix 5: Regime-aware meta-learner (9 inputs: 4 probs + 5 regime context features)
        Fix 6: Separate 30% OOF holdout for isotonic calibration (no calibration leakage)
        """
        self.feature_cols = feature_cols

        # Regime context features for Fix 5 (must be present in df)
        REGIME_COLS = ['vol_regime', 'hurst_60', 'adx_14', 'h1_trend', 'kauf_er_20']
        available_regime = [c for c in REGIME_COLS if c in df.columns]
        n_regime = len(available_regime)

        X = df[feature_cols].values.astype('float32')
        y = df['target'].values

        if len(X) < MIN_TRAIN_SAMPLES:
            raise ValueError(f'Need ≥{MIN_TRAIN_SAMPLES} samples, got {len(X)}')

        # FIX 6 (v27): Pre-split 30% of data as calibration holdout BEFORE CV.
        # Calibration must be fitted on data the meta-learner has never seen.
        n_total   = len(X)
        cal_split = int(n_total * 0.70)   # first 70% for meta training, last 30% for calibration
        cal_mask  = np.zeros(n_total, dtype=bool)
        cal_mask[cal_split:] = True

        # FIX 2 (v27): gap=200 in inner CV (was gap=12).
        # 200 bars = 17 hours. Longest features (ema_100 effective memory ~300 bars,
        # dist_high200) need at least 200-bar gap to prevent rolling-window leakage.
        tscv      = TimeSeriesSplit(n_splits=n_splits, gap=200)
        oof_preds = np.zeros((n_total, 4))
        oof_mask  = np.zeros(n_total, dtype=bool)
        cv_aucs   = []

        for fold, (tr_idx, val_idx) in enumerate(tscv.split(X)):
            fold_scaler = RobustScaler()
            X_tr_s = fold_scaler.fit_transform(X[tr_idx]).astype('float32')
            X_val_s = fold_scaler.transform(X[val_idx]).astype('float32')
            y_tr,   y_val   = y[tr_idx],   y[val_idx]
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_val)) < 2:
                continue

            # LightGBM (GBDT — Fix 3: early_stopping now reliable)
            m_lgbm = _make_lgbm()
            try:
                m_lgbm.fit(X_tr_s, y_tr, eval_set=[(X_val_s, y_val)],
                           callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)])
            except Exception:
                m_lgbm = lgb.LGBMClassifier(n_estimators=300, verbose=-1, random_state=42,
                                             is_unbalance=True)
                m_lgbm.fit(X_tr_s, y_tr)
            p_lgbm = m_lgbm.predict_proba(X_val_s)[:, 1]

            # XGBoost
            m_xgb = _make_xgb()
            try:
                m_xgb.fit(X_tr_s, y_tr, eval_set=[(X_val_s, y_val)], verbose=False)
            except Exception:
                m_xgb = xgb.XGBClassifier(n_estimators=300, tree_method='hist', verbosity=0,
                                           random_state=42)
                m_xgb.fit(X_tr_s, y_tr, verbose=False)
            p_xgb = m_xgb.predict_proba(X_val_s)[:, 1]

            # Random Forest (warm_start for fold models — creates new instances for CV)
            m_rf = _make_rf(warm_start=False)   # BUG 4 FIX: explicit param instead of post-override
            m_rf.fit(X_tr_s, y_tr)
            p_rf = m_rf.predict_proba(X_val_s)[:, 1]

            # PyTorch MLP
            m_mlp = _make_mlp()
            m_mlp.fit(X_tr_s, y_tr)
            p_mlp = m_mlp.predict_proba(X_val_s)[:, 1]

            oof_preds[val_idx] = np.column_stack([p_lgbm, p_xgb, p_rf, p_mlp])
            oof_mask[val_idx]  = True

            p_ens = 0.45*p_lgbm + 0.20*p_xgb + 0.25*p_rf + 0.10*p_mlp
            auc   = roc_auc_score(y_val, p_ens)
            cv_aucs.append(auc)
            if verbose:
                print(f'  Fold {fold+1}: AUC={auc:.4f} | n={len(y_val)}')

        mean_auc = float(np.mean(cv_aucs)) if cv_aucs else 0.0
        std_auc  = float(np.std(cv_aucs))  if cv_aucs else 0.0
        print(f'\n  WF-CV AUC (gap=200): {mean_auc:.4f} ± {std_auc:.4f}')

        # Final fit on full data for the production model.
        self.scaler.fit(X)
        X_s = self.scaler.transform(X).astype('float32')

        _ws_lgbm = getattr(self, '_warmstart_lgbm', None)
        _ws_xgb  = getattr(self, '_warmstart_xgb',  None)
        _ws_rf   = getattr(self, '_warmstart_rf',    None)

        # LGBM — GBDT supports warm-start properly (Fix 3)
        self.lgbm = _make_lgbm()
        try:
            if _ws_lgbm is not None:
                self.lgbm.fit(X_s, y, init_model=_ws_lgbm.booster_,
                              callbacks=[lgb.log_evaluation(-1)])
            else:
                self.lgbm.fit(X_s, y, callbacks=[lgb.log_evaluation(-1)])
        except Exception:
            self.lgbm = lgb.LGBMClassifier(n_estimators=300, verbose=-1, random_state=42,
                                            is_unbalance=True)
            self.lgbm.fit(X_s, y)

        # XGBoost — warm-start via xgb_model
        self.xgb = _make_xgb()
        try:
            if _ws_xgb is not None:
                self.xgb.fit(X_s, y, xgb_model=_ws_xgb.get_booster(), verbose=False)
            else:
                self.xgb.fit(X_s, y, verbose=False)
        except Exception:
            self.xgb = xgb.XGBClassifier(n_estimators=300, tree_method='hist', verbosity=0,
                                          random_state=42)
            self.xgb.fit(X_s, y, verbose=False)

        # FIX 10 (v27): RF warm_start — add trees incrementally during retraining
        if _ws_rf is not None and hasattr(_ws_rf, 'n_estimators'):
            # Continue from existing forest: increase n_estimators by 100
            self.rf = _ws_rf
            self.rf.n_estimators = _ws_rf.n_estimators + 100
            self.rf.fit(X_s, y)
        else:
            self.rf = _make_rf()
            self.rf.fit(X_s, y)
        self._oob_score = self.rf.oob_score_

        self.mlp = _make_mlp()
        self.mlp.fit(X_s, y)

        # FIX 5 + FIX 6 (v27): Regime-aware meta-learner + separate calibration holdout
        meta_oof_mask = oof_mask & ~cal_mask   # OOF rows NOT in calibration holdout
        meta_cal_mask = oof_mask & cal_mask     # OOF rows IN calibration holdout

        if meta_oof_mask.sum() > 50:
            # FIX 5: Augment OOF probs with regime context features
            X_base_meta = oof_preds[meta_oof_mask]
            y_meta      = y[meta_oof_mask]
            if n_regime > 0:
                regime_vals = df[available_regime].values[meta_oof_mask].astype('float32')
                # Clip/normalise regime features to prevent them dominating
                from sklearn.preprocessing import RobustScaler as _RS
                _rs = _RS()
                regime_vals_scaled = _rs.fit_transform(regime_vals)
                X_meta = np.hstack([X_base_meta, regime_vals_scaled])
                self._regime_scaler = _rs
                self._regime_cols   = available_regime
                print(f'  Regime-aware meta-learner: {X_base_meta.shape[1]} probs + {n_regime} regime features')
            else:
                X_meta = X_base_meta
                self._regime_scaler = None
                self._regime_cols   = []
                print('  ⚠️  No regime features available — using 4-input meta-learner')

            self.meta = LogisticRegression(C=0.50, max_iter=500, random_state=42)
            self.meta.fit(X_meta, y_meta)
            meta_auc = roc_auc_score(y_meta, self.meta.predict_proba(X_meta)[:, 1])
            print(f'  Meta-learner AUC (OOF excl. cal holdout): {meta_auc:.4f}')
            w = self.meta.coef_[0]
            print(f'  Meta weights → LGBM:{w[0]:.3f} XGB:{w[1]:.3f} RF:{w[2]:.3f} MLP:{w[3]:.3f}', end='')
            if n_regime > 0:
                print(f' | regime:{w[4:][:3]}...', end='')
            print()

            # FIX 6: Isotonic calibration on SEPARATE 30% OOF holdout (never seen by meta-learner)
            # ISSUE 3 FIX: Log calibration set size and skip if too small
            _n_cal = meta_cal_mask.sum()
            print(f'  Calibration holdout size: {_n_cal}')
            if _n_cal < 200:
                print(f'  ⚠️  Calibration holdout too small ({_n_cal} < 200) — skipping isotonic calibration')
                self.calibrator = None
            elif USE_PROB_CALIBRATION and _n_cal > 100:
                X_base_cal = oof_preds[meta_cal_mask]
                y_cal      = y[meta_cal_mask]
                if n_regime > 0:
                    regime_cal = df[available_regime].values[meta_cal_mask].astype('float32')
                    regime_cal_s = self._regime_scaler.transform(regime_cal)
                    X_cal_meta = np.hstack([X_base_cal, regime_cal_s])
                else:
                    X_cal_meta = X_base_cal
                p_cal = self.meta.predict_proba(X_cal_meta)[:, 1]
                self.calibrator = IsotonicRegression(out_of_bounds='clip')
                self.calibrator.fit(p_cal, y_cal)
                print(f'  Isotonic calibrator fitted on {meta_cal_mask.sum()} SEPARATE holdout OOF samples (Fix 6)')
            else:
                self.calibrator = None
        else:
            print('  ⚠️  Insufficient OOF data — using fixed weights')
            self.meta = None
            self._regime_scaler = None
            self._regime_cols   = []

        self.is_trained = True
        print(f'  ✅ All 4 models trained on {len(X):,} samples | RF OOB={self._oob_score:.4f}')
        if USE_GPU:
            print(f'  🟢 GPU used: {GPU_NAME}')
        return {'cv_auc_mean': mean_auc, 'cv_auc_std': std_auc,
                'n_samples': len(X), 'oob_score': self._oob_score}

    def _base_proba(self, X_s):
        p_lgbm = self.lgbm.predict_proba(X_s)[:, 1]
        p_xgb  = self.xgb.predict_proba(X_s)[:, 1]
        p_rf   = self.rf.predict_proba(X_s)[:, 1]
        p_mlp  = self.mlp.predict_proba(X_s)[:, 1]
        return np.column_stack([p_lgbm, p_xgb, p_rf, p_mlp])

    def predict_proba(self, X, X_df=None):
        """
        FIX 5 (v27): Regime-aware predict_proba.
        X_df: original (unscaled) DataFrame row(s) for regime feature extraction.
              If None, meta-learner falls back to 4-input mode.
        """
        if not self.is_trained:
            raise RuntimeError('Model not trained')
        X_s   = self.scaler.transform(X.astype('float32'))
        stack = self._base_proba(X_s)
        if self.meta is not None:
            regime_cols = getattr(self, '_regime_cols', [])
            regime_scaler = getattr(self, '_regime_scaler', None)
            if regime_cols and regime_scaler is not None:
                if X_df is None:
                    raise ValueError(
                        'Regime-aware meta-learner requires X_df with the regime feature columns '
                        f'{regime_cols} at inference time.'
                    )
                # Regime-aware path: augment stack with regime features
                try:
                    if hasattr(X_df, 'values'):
                        regime_vals = X_df[regime_cols].values.astype('float32')
                    else:
                        raise ValueError('X_df must be a DataFrame-like object with named regime columns.')
                    regime_scaled = regime_scaler.transform(
                        regime_vals.reshape(-1, len(regime_cols))
                    )
                    X_meta = np.hstack([stack, regime_scaled])
                except Exception as e:
                    raise ValueError(f'Failed to assemble regime-aware inference inputs: {e}') from e
            else:
                X_meta = stack
            proba = self.meta.predict_proba(X_meta)[:, 1]
        else:
            w = [ENSEMBLE_WEIGHTS.get(k, 0.25) for k in ['lgbm', 'xgb', 'rf', 'mlp']]
            proba = stack @ np.array(w) / sum(w)
        if self.calibrator is not None:
            proba = self.calibrator.predict(proba)
        return proba

    def predict_signal(self, X, threshold=None, X_df=None):
        thr_long  = SIGNAL_THRESHOLD_LONG  if threshold is None else threshold
        proba = self.predict_proba(X, X_df=X_df)
        if LONG_ONLY_EXECUTION:
            sig = np.where(proba > thr_long, 1, 0)
        else:
            thr_short = SIGNAL_THRESHOLD_SHORT if threshold is None else (1 - threshold)
            sig = np.where(proba > thr_long, 1, np.where(proba < thr_short, -1, 0))
        return sig, proba

    def predict_uncertainty(self, X):
        X_s   = self.scaler.transform(X.astype('float32'))
        stack = self._base_proba(X_s)
        return stack.std(axis=1)

    def feature_importance(self):
        if not self.is_trained:
            return pd.DataFrame()
        lgbm_imp = self.lgbm.feature_importances_ / (self.lgbm.feature_importances_.sum() + 1e-9)
        xgb_imp  = self.xgb.feature_importances_  / (self.xgb.feature_importances_.sum()  + 1e-9)
        rf_imp   = self.rf.feature_importances_   / (self.rf.feature_importances_.sum()    + 1e-9)
        combined = 0.45*lgbm_imp + 0.20*xgb_imp + 0.30*rf_imp + 0.05*np.zeros_like(rf_imp)
        return pd.DataFrame({
            'feature': self.feature_cols,
            'lgbm':    (lgbm_imp * 100).round(3),
            'xgb':     (xgb_imp  * 100).round(3),
            'rf':      (rf_imp   * 100).round(3),
            'combined':(combined * 100).round(3),
        }).sort_values('combined', ascending=False).reset_index(drop=True)

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        joblib.dump(self.lgbm,         f'{path}/lgbm.pkl')
        joblib.dump(self.xgb,          f'{path}/xgb.pkl')
        joblib.dump(self.rf,           f'{path}/rf.pkl')
        joblib.dump(self.mlp,          f'{path}/mlp.pkl')
        joblib.dump(self.meta,         f'{path}/meta.pkl')
        joblib.dump(self.calibrator,   f'{path}/calibrator.pkl')
        joblib.dump(self.scaler,       f'{path}/scaler.pkl')
        joblib.dump(self.feature_cols, f'{path}/feature_cols.pkl')
        joblib.dump(getattr(self, '_regime_scaler', None), f'{path}/regime_scaler.pkl')
        joblib.dump(getattr(self, '_regime_cols', []),     f'{path}/regime_cols.pkl')
        print(f'  💾 Model saved to {path}')

    def load(self, path):
        self.lgbm         = joblib.load(f'{path}/lgbm.pkl')
        self.xgb          = joblib.load(f'{path}/xgb.pkl')
        self.rf           = joblib.load(f'{path}/rf.pkl')
        self.mlp          = joblib.load(f'{path}/mlp.pkl')
        self.meta         = joblib.load(f'{path}/meta.pkl')
        self.calibrator   = joblib.load(f'{path}/calibrator.pkl')
        self.scaler       = joblib.load(f'{path}/scaler.pkl')
        self.feature_cols = joblib.load(f'{path}/feature_cols.pkl')
        regime_scaler_path = f'{path}/regime_scaler.pkl'
        regime_cols_path   = f'{path}/regime_cols.pkl'
        self._regime_scaler = joblib.load(regime_scaler_path) if os.path.exists(regime_scaler_path) else None
        self._regime_cols   = joblib.load(regime_cols_path)   if os.path.exists(regime_cols_path) else []
        self.is_trained   = True
        print(f'  📂 Model loaded from {path}')


print('✅ EnsembleModel v27 defined — regime-aware meta-learner | GBDT | single scaler | gap=200')
print(f'   LGBM device : {LGBM_DEVICE}')
print(f'   XGBoost     : {XGB_DEVICE}')
print(f'   MLP (Torch) : {TORCH_DEVICE}')
print('   RF          : CPU (sklearn)')

# ==== CELL 20 ====
print('🔨 Building feature matrix (v27) ...')
# Pass df_1h and df_funding — will gracefully degrade if unavailable
_df_1h      = df_1h      if 'df_1h'      in globals() and not df_1h.empty      else None
_df_funding = df_funding  if 'df_funding'  in globals() and not df_funding.empty  else None

df_features = build_feature_matrix(df_5m, df_15m, _df_1h, _df_funding)

# ── Train/test split: last BACKTEST_DAYS for OOS backtest ───────────────────
cutoff_ts = df_features['timestamp'].max() - pd.Timedelta(days=BACKTEST_DAYS)
df_train  = df_features[df_features['timestamp'] <= cutoff_ts].copy()
df_oos    = df_features[df_features['timestamp'] >  cutoff_ts].copy()

print(f'Train: {len(df_train)} rows | OOS: {len(df_oos)} rows')
print(f'Train period: {df_train.timestamp.iloc[0].date()} → {df_train.timestamp.iloc[-1].date()}')
print(f'OOS period:   {df_oos.timestamp.iloc[0].date()} → {df_oos.timestamp.iloc[-1].date()}')

print('\n🤖 Training ensemble ...')
model = EnsembleModel()
train_metrics = model.train(
    df_train, FEATURE_COLS,
    n_splits=WALK_FORWARD_SPLITS,
)

# Save individual model files
model.save(MODEL_DIR)

# v25: Save FeatureEngineer + unified artifact bundle
feature_engineer = FeatureEngineer()
feature_engineer.fit(df_5m, df_15m, _df_1h, _df_funding)
joblib.dump(feature_engineer, f'{MODEL_DIR}/feature_engineer.pkl')

import json as _json
from datetime import datetime as _dt
artifact = {
    'model':    model,
    'features': model.feature_cols,
    'scaler':   model.scaler,
    'feature_engineer': feature_engineer,
    'metrics':  train_metrics,
    'metadata': {
        'version':       'v27',
        'symbol':        SYMBOL_5M,
        'trained_at':    _dt.utcnow().isoformat(),
        'n_features':    len(model.feature_cols or []),
        'n_train_rows':  len(df_train),
        'cv_auc':        round(train_metrics.get('cv_auc_mean', 0), 4),
    },
}
joblib.dump(artifact, f'{MODEL_DIR}/model_artifact_v27.pkl')
print(f'✅ Unified artifact saved → {MODEL_DIR}/model_artifact_v27.pkl')

print('\n📊 Top 10 features:')
print(model.feature_importance().head(10).to_string(index=False))

# ==== CELL 22 ====
from dataclasses import dataclass, field
from typing import List


@dataclass
class Trade:
    entry_time:  pd.Timestamp
    exit_time:   pd.Timestamp
    side:        str          # 'long' or 'short'
    entry_price: float
    exit_price:  float
    size:        float        # USD notional
    pnl_pct:     float        # net PnL % after fees
    pnl_usd:     float
    exit_reason: str          # 'signal', 'sl', 'tp'


class Backtester:
    """
    Bar-by-bar backtester for the EnsembleModel.
    Signals are generated from features at bar t, executed at bar t+1 open.
    SL/TP are checked within bar t+1's high/low.
    """

    def __init__(
        self,
        maker_fee:    float = MAKER_FEE,
        taker_fee:    float = TAKER_FEE,
        slippage_pct: float = SLIPPAGE_PCT,
        sl_pct:       float = STOP_LOSS_PCT,
        tp_pct:       float = TAKE_PROFIT_PCT,
        leverage:     int   = LEVERAGE,
        max_pos_pct:  float = MAX_POSITION_PCT,
        capital:      float = CAPITAL_USDT,
    ):
        self.maker_fee    = maker_fee
        self.taker_fee    = taker_fee
        self.slippage_pct = slippage_pct
        self.sl_pct       = sl_pct
        self.tp_pct       = tp_pct
        self.leverage     = leverage
        self.max_pos_pct  = max_pos_pct
        self.init_capital = capital

    def _apply_slippage(self, price: float, side: str, entry: bool) -> float:
        direction = 1 if (side == 'long') == entry else -1
        return price * (1 + direction * self.slippage_pct)

    def _position_size(self, capital: float, price: float) -> float:
        """
        Notional USD size using fractional Kelly or max_pos_pct cap.
        BUG 9 FIX: The old min() was ineffective — both terms simplified to the same
        value (0.20 × 5 = 1.0 × capital and 1.0 × capital), making the cap redundant.
        Fix: cap the fraction BEFORE applying leverage.
        """
        capped_fraction = min(self.max_pos_pct, 1.0)   # cap at 20% of capital
        return capital * capped_fraction * self.leverage

    def run(
        self,
        df: pd.DataFrame,
        model: EnsembleModel,
        threshold: float = SIGNAL_THRESHOLD,
        feature_cols: list = None,   # BUG FIX 3: use model.feature_cols, not global
    ) -> dict:
        """
        Run backtest on df (must have OHLCV + feature cols + timestamp).
        Returns performance metrics dict and trade log.
        """
        # BUG FIX 3: always use the model's own feature list, never the global
        feature_cols = feature_cols or getattr(model, 'feature_cols', None) or FEATURE_COLS
        df = df.reset_index(drop=True)
        capital   = self.init_capital
        trades: List[Trade] = []
        equity_curve = [capital]

        position   = None   # None | {'side', 'entry_price', 'size', 'sl', 'tp', 'entry_time', 'entry_idx'}
        total_fees = 0.0

        for i in range(len(df) - 1):
            row_now  = df.iloc[i]
            row_next = df.iloc[i + 1]

            # ── Check open position SL/TP first (within next bar) ─────────
            if position is not None:
                ep    = position['entry_price']
                side  = position['side']
                hi    = row_next['high']
                lo    = row_next['low']
                sl    = position['sl']
                tp    = position['tp']
                exit_price  = None
                exit_reason = None

                if side == 'long':
                    # ISSUE 6 FIX: gap-through pessimism — if bar opens beyond SL,
                    # use open price (worse fill) instead of SL level
                    if row_next['open'] <= sl:
                        exit_price, exit_reason = row_next['open'], 'sl_gap'
                    elif lo <= sl:
                        exit_price, exit_reason = sl, 'sl'
                    elif hi >= tp:
                        exit_price, exit_reason = tp, 'tp'
                else:  # short
                    if row_next['open'] >= sl:
                        exit_price, exit_reason = row_next['open'], 'sl_gap'
                    elif hi >= sl:
                        exit_price, exit_reason = sl, 'sl'
                    elif lo <= tp:
                        exit_price, exit_reason = tp, 'tp'

                if exit_price is None:
                    # Check for signal reversal exit at bar close
                    X_now = df.iloc[i][feature_cols].values.reshape(1, -1)
                    try:
                        x_df = df.iloc[[i]][feature_cols]
                        sig, _ = model.predict_signal(X_now, threshold, X_df=x_df)
                    except Exception:
                        sig = np.array([0])
                    if (side == 'long' and sig[0] == -1) or (side == 'short' and sig[0] == 1):
                        exit_price  = row_next['open']
                        exit_reason = 'signal'

                if exit_price is not None:
                    exit_px_adj = self._apply_slippage(exit_price, side, entry=False)
                    fee = position['size'] * self.taker_fee
                    total_fees += fee
                    if side == 'long':
                        pnl_pct = (exit_px_adj - ep) / ep
                    else:
                        pnl_pct = (ep - exit_px_adj) / ep
                    pnl_usd = position['size'] * pnl_pct - fee
                    capital += pnl_usd
                    trades.append(Trade(
                        entry_time  = position['entry_time'],
                        exit_time   = row_next['timestamp'],
                        side        = side,
                        entry_price = ep,
                        exit_price  = exit_px_adj,
                        size        = position['size'],
                        pnl_pct     = pnl_pct,
                        pnl_usd     = pnl_usd,
                        exit_reason = exit_reason,
                    ))
                    position = None
                    equity_curve.append(capital)
                    continue

            # ── Generate signal if flat ───────────────────────────────────
            if position is None:
                X_now = df.iloc[i][feature_cols].values.reshape(1, -1)
                try:
                    x_df = df.iloc[[i]][feature_cols]
                    sig, proba = model.predict_signal(X_now, threshold, X_df=x_df)
                except Exception:
                    equity_curve.append(capital)
                    continue

                if sig[0] != 0:
                    if LONG_ONLY_EXECUTION and sig[0] != 1:
                        equity_curve.append(capital)
                        continue
                    side       = 'long' if sig[0] == 1 else 'short'
                    entry_price= self._apply_slippage(row_next['open'], side, entry=True)
                    size       = self._position_size(capital, entry_price)
                    fee        = size * self.taker_fee
                    total_fees += fee
                    capital    -= fee  # Entry fee

                    if side == 'long':
                        sl = entry_price * (1 - self.sl_pct)
                        tp = entry_price * (1 + self.tp_pct)
                    else:
                        sl = entry_price * (1 + self.sl_pct)
                        tp = entry_price * (1 - self.tp_pct)

                    position = {
                        'side':        side,
                        'entry_price': entry_price,
                        'entry_time':  row_next['timestamp'],
                        'size':        size,
                        'sl':          sl,
                        'tp':          tp,
                    }

            equity_curve.append(capital)

        # ── Compute metrics ───────────────────────────────────────────────
        return self._compute_metrics(trades, equity_curve, total_fees)

    def _compute_metrics(self, trades: list, equity: list, total_fees: float) -> dict:
        eq   = np.array(equity)
        rets = np.diff(eq) / (eq[:-1] + 1e-9)

        # Drawdown
        peak = np.maximum.accumulate(eq)
        dd   = (eq - peak) / (peak + 1e-9)
        max_dd = dd.min()

        # Trade stats
        n_trades  = len(trades)
        if n_trades == 0:
            print('⚠️  No trades executed')
            return {'error': 'no trades'}

        pnls      = [t.pnl_usd for t in trades]
        wins      = [p for p in pnls if p > 0]
        losses    = [p for p in pnls if p <= 0]
        win_rate  = len(wins) / n_trades
        avg_win   = np.mean(wins) if wins else 0
        avg_loss  = abs(np.mean(losses)) if losses else 0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else float('inf')

        # Sharpe (annualised, assuming 5m bars)
        bars_per_year = 252 * 24 * 12  # 5m bars per year
        sharpe = (
            rets.mean() / (rets.std() + 1e-9) * np.sqrt(bars_per_year)
            if len(rets) > 1 else 0
        )

        total_return = (eq[-1] - eq[0]) / (eq[0] + 1e-9)
        by_exit = {r: sum(1 for t in trades if t.exit_reason == r)
                   for r in ['signal', 'sl', 'tp']}

        metrics = {
            'total_return_pct': round(total_return * 100, 2),
            'final_capital':    round(eq[-1], 2),
            'max_drawdown_pct': round(max_dd * 100, 2),
            'sharpe_ratio':     round(sharpe, 3),
            'n_trades':         n_trades,
            'win_rate_pct':     round(win_rate * 100, 2),
            'profit_factor':    round(profit_factor, 3),
            'avg_win_usd':      round(avg_win, 2),
            'avg_loss_usd':     round(avg_loss, 2),
            'total_fees_usd':   round(total_fees, 2),
            'exits':            by_exit,
        }
        self.equity_curve = eq
        self.trades       = trades
        return metrics


print('✅ Backtester class defined')

# ==== CELL 24 ====
print('🧪 Running OOS backtest ...')
print(f'   Period: {df_oos.timestamp.iloc[0].date()} → {df_oos.timestamp.iloc[-1].date()}')
print(f'   Bars:   {len(df_oos)}')

bt = Backtester()
results = bt.run(df_oos, model, threshold=SIGNAL_THRESHOLD)

print('\n' + '='*50)
print('📊 OOS BACKTEST RESULTS')
print('='*50)
for k, v in results.items():
    print(f'  {k:<25}: {v}')
print('='*50)

# ── Equity curve plot ────────────────────────────────────────────────────────
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(3, 1, figsize=(14, 10), facecolor='#0d1117')
for ax in axes:
    ax.set_facecolor('#0d1117')
    ax.tick_params(colors='#c9d1d9')
    ax.spines[:].set_color('#30363d')

timestamps = df_oos['timestamp'].values[:len(bt.equity_curve)]

# Equity curve
axes[0].plot(timestamps, bt.equity_curve, color='#58a6ff', lw=1.5)
axes[0].axhline(CAPITAL_USDT, color='#6e7681', lw=0.8, ls='--')
axes[0].set_title('Equity Curve (OOS)', color='#c9d1d9', fontsize=12)
axes[0].set_ylabel('Capital (USDT)', color='#c9d1d9')

# Drawdown
eq  = bt.equity_curve
pk  = np.maximum.accumulate(eq)
dd  = (eq - pk) / (pk + 1e-9) * 100
axes[1].fill_between(timestamps, dd, 0, color='#f85149', alpha=0.6)
axes[1].set_title('Drawdown %', color='#c9d1d9', fontsize=12)
axes[1].set_ylabel('DD %', color='#c9d1d9')

# Trade PnL bars
trade_times = [t.exit_time for t in bt.trades]
trade_pnls  = [t.pnl_usd for t in bt.trades]
colors      = ['#3fb950' if p > 0 else '#f85149' for p in trade_pnls]
axes[2].bar(trade_times, trade_pnls, color=colors, width=pd.Timedelta(minutes=20))
axes[2].axhline(0, color='#6e7681', lw=0.8)
axes[2].set_title('Per-Trade PnL (USD)', color='#c9d1d9', fontsize=12)
axes[2].set_ylabel('PnL (USD)', color='#c9d1d9')

plt.tight_layout()
plt.savefig('/content/backtest_results.png', dpi=150, bbox_inches='tight')
plt.show()
print('💾 Chart saved to /content/backtest_results.png')

# ==== CELL 26 ====
def walk_forward_backtest(
    df_full: pd.DataFrame,
    n_splits: int = 5,
    train_pct: float = 0.7,
) -> pd.DataFrame:
    """
    Full walk-forward backtest:
    - Splits the full dataset into n_splits sequential folds
    - For each fold: trains on first 70%, tests on remaining 30%
    - Returns per-fold metrics to assess robustness
    """
    # FIX 7 (v27): gap=200 in walk-forward outer split.
    # Without gap, the first ~200 bars of each test fold have features computed
    # with rolling windows that embed training-set statistics — contaminating the
    # first ~200 OOS predictions. gap=200 ensures genuinely out-of-sample estimates.
    tscv    = TimeSeriesSplit(n_splits=n_splits, gap=200)
    bt      = Backtester()
    fold_metrics = []

    print(f'🔄 Walk-forward backtest: {n_splits} folds (gap=200, v27 Fix 7)')

    # BUG 8 FIX: Time budget guard — prevents Colab session disconnect on long runs
    import time as _time
    MAX_WF_SECONDS = 3600   # 1-hour budget for entire walk-forward
    _wf_start = _time.time()

    for fold, (train_idx, test_idx) in enumerate(tscv.split(df_full)):
        if _time.time() - _wf_start > MAX_WF_SECONDS:
            print(f'  ⏱ Walk-forward time budget exceeded ({MAX_WF_SECONDS}s) — stopping at fold {fold+1}')
            break
        df_tr  = df_full.iloc[train_idx].copy()
        df_te  = df_full.iloc[test_idx].copy()

        if len(df_tr) < MIN_TRAIN_SAMPLES or len(df_te) < 50:
            print(f'  Fold {fold+1}: skipped (insufficient data)')
            continue

        # Train fresh model on this fold's training data
        # P1 fix: no kwargs — meta-learner handles weighting internally
        m = EnsembleModel()
        try:
            m.train(df_tr, FEATURE_COLS, n_splits=3, verbose=False)
        except Exception as e:
            print(f'  Fold {fold+1}: training error — {e}')
            continue

        # Backtest on test window
        res = bt.run(df_te, m, threshold=SIGNAL_THRESHOLD)
        if 'error' in res:
            continue

        res['fold']       = fold + 1
        res['train_rows'] = len(df_tr)
        res['test_rows']  = len(df_te)
        res['test_start'] = df_te['timestamp'].iloc[0].date()
        res['test_end']   = df_te['timestamp'].iloc[-1].date()
        fold_metrics.append(res)

        print(f'  Fold {fold+1}: return={res["total_return_pct"]}% | '
              f'winrate={res["win_rate_pct"]}% | '
              f'sharpe={res["sharpe_ratio"]} | '
              f'trades={res["n_trades"]}')

    if not fold_metrics:
        print('❌ No folds completed')
        return pd.DataFrame()

    summary = pd.DataFrame(fold_metrics)
    print('\n📊 Walk-Forward Summary:')
    cols = ['fold', 'test_start', 'test_end', 'total_return_pct',
            'win_rate_pct', 'sharpe_ratio', 'max_drawdown_pct', 'n_trades', 'profit_factor']
    print(summary[cols].to_string(index=False))
    print(f'\n  Mean return : {summary["total_return_pct"].mean():.2f}%')
    print(f'  Mean Sharpe : {summary["sharpe_ratio"].mean():.3f}')
    print(f'  % profitable folds: {(summary["total_return_pct"] > 0).mean()*100:.0f}%')
    return summary


wf_results = walk_forward_backtest(df_features, n_splits=WALK_FORWARD_SPLITS)

# ==== CELL 28 ====
import threading
import schedule
import time as time_module
from datetime import datetime, timezone
import pickle
import json
from scipy.stats import ks_2samp
from pathlib import Path


# ── Population Stability Index helper ────────────────────────────────────────

def _psi_score(expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
    """
    Population Stability Index (PSI) — complementary to KS test.
    PSI < 0.10 → stable    |  0.10–0.20 → minor shift  |  > 0.20 → significant drift.
    PSI operates on quantile bins, making it sensitive to distributional shape
    changes that KS test can miss (e.g. same mean/variance but different tail behaviour).
    """
    if len(expected) < buckets * 3 or len(actual) < buckets * 3:
        return 0.0
    try:
        breakpoints = np.percentile(expected, np.linspace(0, 100, buckets + 1))
        breakpoints[0]  -= 1e-9
        breakpoints[-1] += 1e-9
        def bucket_pct(arr):
            counts = np.histogram(arr, bins=breakpoints)[0]
            pct    = counts / (counts.sum() + 1e-9)
            return np.clip(pct, 1e-4, None)
        e_pct = bucket_pct(expected)
        a_pct = bucket_pct(actual)
        return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))
    except Exception:
        return 0.0



# ── v27 HTF drift helpers (Fix 11) ───────────────────────────────────────────

def _quick_1h_features(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Compute minimal 1h features for native-granularity drift detection (Fix 11)."""
    d = df_1h.copy()
    if 'close' not in d.columns:
        return d
    ema21 = d['close'].ewm(span=21, adjust=False).mean()
    ema50 = d['close'].ewm(span=50, adjust=False).mean()
    d['h1_trend'] = (ema21 - ema50) / (ema50 + 1e-9)
    rsi_delta = d['close'].diff()
    gain = rsi_delta.where(rsi_delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-rsi_delta.where(rsi_delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    d['h1_rsi_14'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    high, low, close = d.get('high', d['close']), d.get('low', d['close']), d['close']
    tr = pd.concat([high-low, (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    up   = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up.values, 0.0), index=d.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down.values, 0.0), index=d.index)
    atr_s    = tr.ewm(span=14, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=14, adjust=False).mean() / (atr_s + 1e-9)
    minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / (atr_s + 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    d['h1_adx'] = dx.ewm(span=14, adjust=False).mean()
    vol_ret = d['close'].pct_change()
    d['h1_vol_regime'] = vol_ret.rolling(20).std() / (vol_ret.rolling(50).std().rolling(100, min_periods=20).median() + 1e-9)
    return d

# Dummy import guard (the inline functions are used directly, not via import)
import sys as _sys
_m = type(_sys)('agent_utils_v27')
_m._quick_1h_features = _quick_1h_features
_sys.modules['agent_utils_v27'] = _m

class ModelRegistry:
    """
    Versioned model storage + hot-reload with in-memory cache.
    Unchanged from v23 — thread-safe, cooldown-aware.
    """

    def __init__(self, base_dir: str = '/content/models'):
        self.base_dir    = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache      = {}
        self._retrain_ts = {}
        self._log_path   = self.base_dir / 'retrain_log.json'

    def save_version(self, resolution: str, model: EnsembleModel, tag: str) -> Path:
        version_dir = self.base_dir / f'model_{resolution}_{tag}'
        version_dir.mkdir(parents=True, exist_ok=True)
        pipeline = {
            'model':     model,
            'features':  model.feature_cols or [],
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version':   tag,
        }
        versioned_path = version_dir / f'pipeline_{resolution}_{tag}.pkl'
        latest_path    = self.base_dir / f'pipeline_{resolution}_latest.pkl'
        for p in (versioned_path, latest_path):
            with open(p, 'wb') as fh:
                pickle.dump(pipeline, fh)
        self._cache[resolution]      = pipeline
        self._retrain_ts[resolution] = time_module.time()
        print(f'  💾 Registry: saved {resolution} version={tag}')
        return versioned_path

    def load_latest(self, resolution: str) -> dict | None:
        if resolution in self._cache:
            return self._cache[resolution]
        latest_path = self.base_dir / f'pipeline_{resolution}_latest.pkl'
        if not latest_path.exists():
            return None
        try:
            with open(latest_path, 'rb') as fh:
                pipeline = pickle.load(fh)
            self._cache[resolution] = pipeline
            return pipeline
        except Exception as e:
            print(f'  ❌ Load error: {e}')
            return None

    def cooldown_remaining(self, resolution: str, hours: float) -> float:
        last = self._retrain_ts.get(resolution) or self._last_retrain_from_log(resolution)
        if not last:
            return 0.0
        return max(0.0, hours - (time_module.time() - last) / 3600)

    def log_retrain(self, entry: dict):
        entries = self._load_log()
        entries.append(entry)
        with open(self._log_path, 'w') as fh:
            json.dump(entries, fh, indent=2)

    def invalidate_cache(self, resolution: str):
        self._cache.pop(resolution, None)

    def _load_log(self) -> list:
        if not self._log_path.exists():
            return []
        try:
            with open(self._log_path) as fh:
                return json.load(fh)
        except Exception:
            return []

    def _last_retrain_from_log(self, resolution: str) -> float:
        entries = [e for e in self._load_log() if e.get('resolution') == resolution]
        if not entries:
            return 0.0
        try:
            return pd.Timestamp(entries[-1]['timestamp']).timestamp()
        except Exception:
            return 0.0


class RetrainEngine:
    """
    Adaptive retrain engine with dual drift detection + warm-start. (v24)

    Improvements over v23:
    ──────────────────────
    1. DUAL DRIFT DETECTOR: KS test (distribution shape) + PSI (population
       stability). Both must agree above their thresholds to trigger retraining.
       This drastically reduces false-positive retrains from transient spikes.

    2. ADAPTIVE DRIFT THRESHOLD: The KS/PSI thresholds scale with recent
       market volatility. In high-volatility regimes, slight feature shift is
       expected — the engine requires a larger drift signal to retrain.
       Prevents churning models during normal BTC volatility.

    3. WARM-START RETRAINING (RETRAIN_WARMSTART=True): If the current model
       passes the drift check, the new model is initialised from the current
       model's weights/state for LGBM/XGB, reducing retraining cold-start
       cost and preserving previously learned stable patterns.

    4. ROLLING PERFORMANCE TRACKER: Exponentially weighted tracking of
       CV-AUC and win-rate across retrain cycles. Detects persistent model
       degradation vs temporary data noise.

    5. EXPONENTIAL BACKOFF: If a retrain is rejected N times in a row,
       the cooldown period doubles, preventing repeated wasteful retrains
       in persistently hostile market conditions.
    """

    def __init__(
        self,
        registry:            ModelRegistry,
        cooldown_hours:      float = 1.0,
        drift_feature_limit: int   = None,
        past_bars:           int   = None,
        recent_bars:         int   = None,
        min_auc:             float = None,
        min_win_rate:        float = None,
    ):
        self.registry            = registry
        self.base_cooldown_hours = cooldown_hours
        self.cooldown_hours      = cooldown_hours
        self.drift_feature_limit = drift_feature_limit or RETRAIN_DRIFT_FEATURE_LIMIT
        self.past_bars           = past_bars   or RETRAIN_WINDOW_PAST_BARS
        self.recent_bars         = recent_bars or RETRAIN_WINDOW_RECENT_BARS
        self.min_auc             = min_auc     or RETRAIN_VALIDATION_MIN_AUC
        self.min_win_rate        = min_win_rate or RETRAIN_VALIDATION_MIN_WR
        # Rolling performance tracker
        self._ema_auc       = None   # exponential moving average of retrain AUC
        self._ema_wr        = None   # exponential moving average of win-rate
        self._reject_streak = 0      # consecutive validation failures
        self._decay         = RETRAIN_PERF_DECAY

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _update_ema(self, new_auc: float, new_wr: float):
        if self._ema_auc is None:
            self._ema_auc = new_auc
            self._ema_wr  = new_wr
        else:
            self._ema_auc = self._decay * self._ema_auc + (1 - self._decay) * new_auc
            self._ema_wr  = self._decay * self._ema_wr  + (1 - self._decay) * new_wr

    def _adaptive_thresholds(self, df_recent: pd.DataFrame) -> tuple:
        """
        Scale drift sensitivity with recent volatility.
        In high-vol regimes, require larger drift signal to trigger retraining.
        Returns (ks_stat_min, psi_min, drift_limit_adj).
        """
        base_ks_stat  = 0.10
        base_psi      = PSI_THRESHOLD
        base_limit    = self.drift_feature_limit

        if 'vol_regime' in df_recent.columns:
            vol_now    = df_recent['vol_regime'].iloc[-1]
            vol_median = df_recent['vol_regime'].median()
            vol_ratio  = float(np.clip(vol_now / (vol_median + 1e-9), 0.5, 3.0))
            # High vol → raise thresholds (require stronger evidence to retrain)
            ks_stat_min   = base_ks_stat * vol_ratio
            psi_min       = base_psi     * vol_ratio
            drift_adj     = max(2, int(base_limit * vol_ratio))
        else:
            ks_stat_min   = base_ks_stat
            psi_min       = base_psi
            drift_adj     = base_limit

        return ks_stat_min, psi_min, drift_adj

    # ── Main entry point ──────────────────────────────────────────────────────
    def maybe_retrain(
        self,
        resolution:    str,
        df_window:     pd.DataFrame,
        current_model: EnsembleModel,
        df_1h:         pd.DataFrame = None,   # FIX 11: native 1h data for HTF drift detection
    ) -> EnsembleModel | None:
        """
        v27 drift→retrain→validate pipeline (Fixes 8, 10, 11).
        Returns new EnsembleModel if accepted, or None if skipped/rejected.
        """
        print(f'\n[RetrainEngine v27:{resolution}] Checking for retrain...')

        # ── 1. Cooldown (with exponential backoff) ────────────────────────────
        remaining = self.registry.cooldown_remaining(resolution, self.cooldown_hours)
        if remaining > 0:
            print(f'  Cooldown: {remaining:.1f}h remaining (backoff={self.cooldown_hours:.1f}h) — skip')
            return None

        n      = len(df_window)
        needed = self.past_bars + self.recent_bars
        if n < needed:
            print(f'  Insufficient data: {n} bars, need {needed} — skip')
            return None

        df_past   = df_window.iloc[-(self.past_bars + self.recent_bars):-self.recent_bars]
        df_recent = df_window.iloc[-self.recent_bars:]

        feature_cols = (
            current_model.feature_cols
            if hasattr(current_model, 'feature_cols') and current_model.feature_cols
            else FEATURE_COLS
        )

        # ── 2. Adaptive thresholds ────────────────────────────────────────────
        ks_min, psi_min, drift_limit = self._adaptive_thresholds(df_recent)
        print(f'  Adaptive thresholds: KS_stat≥{ks_min:.3f} | PSI≥{psi_min:.3f} | drift_limit={drift_limit}')

        # ── 3. Dual drift detection: KS + PSI ────────────────────────────────
        ks_drifted  = []
        psi_drifted = []

        for col in feature_cols:
            if col not in df_past.columns or col not in df_recent.columns:
                continue
            a = df_past[col].dropna().values
            b = df_recent[col].dropna().values
            if len(a) < 30 or len(b) < 30:
                continue
            try:
                stat, p_val = ks_2samp(a, b)
                if p_val < 0.01 and stat > ks_min:
                    ks_drifted.append((col, p_val, stat))
            except Exception:
                pass
            psi = _psi_score(a, b)
            if psi > psi_min:
                psi_drifted.append((col, psi))

        # Features flagged by BOTH detectors (consensus drift)
        ks_feats  = {d[0] for d in ks_drifted}
        psi_feats = {d[0] for d in psi_drifted}
        consensus = ks_feats & psi_feats

        print(f'  KS-drifted: {len(ks_drifted)} | PSI-drifted: {len(psi_drifted)} | Consensus: {len(consensus)}')
        if consensus:
            top = sorted(ks_drifted, key=lambda x: x[2], reverse=True)[:3]
            print(f'  Top drifted: {[d[0] for d in top]}')

        # ── 3b. FIX 11 (v27): HTF drift detection on native 1h data ──────────
        # The 1h features (h1_trend, h1_adx etc.) are forward-filled to 5m via merge_asof:
        # 12 consecutive 5m rows share identical 1h values (step-function).
        # KS/PSI on step-function distributions underestimates true drift.
        # Solution: run drift check on the raw 1h DataFrame at native granularity.
        htf_drift_count = 0
        if df_1h is not None and not df_1h.empty and len(df_1h) > 100:
            try:
                n_1h = len(df_1h)
                split_1h = max(10, n_1h - max(10, n_1h // 5))  # last ~20% as recent
                df_1h_past   = df_1h.iloc[:split_1h]
                df_1h_recent = df_1h.iloc[split_1h:]
                h1_drift_cols = [c for c in ['h1_trend', 'h1_adx', 'h1_rsi_14', 'h1_vol_regime']
                                 if c in df_1h.columns]
                if not h1_drift_cols:
                    # compute on-the-fly if raw 1h OHLCV
                    from agent_utils_v27 import _quick_1h_features
                    df_1h_past_f   = _quick_1h_features(df_1h_past)
                    df_1h_recent_f = _quick_1h_features(df_1h_recent)
                    h1_drift_cols  = [c for c in df_1h_past_f.columns if c.startswith('h1_')]
                else:
                    df_1h_past_f   = df_1h_past
                    df_1h_recent_f = df_1h_recent
                for col in h1_drift_cols:
                    if col not in df_1h_past_f.columns:
                        continue
                    a = df_1h_past_f[col].dropna().values
                    b = df_1h_recent_f[col].dropna().values
                    if len(a) < 10 or len(b) < 5:
                        continue
                    try:
                        stat, p_val = ks_2samp(a, b)
                        if p_val < 0.05 and stat > 0.20:
                            htf_drift_count += 1
                            print(f'  📡 HTF 1h drift detected: {col} KS={stat:.3f}')
                    except Exception:
                        pass
                if htf_drift_count > 0:
                    print(f'  📡 HTF drift: {htf_drift_count} 1h features shifted at native granularity')
            except Exception as e:
                print(f'  ⚠️  HTF drift check error (non-critical): {e}')
        # HTF drift alone can lower the consensus bar by 2 (macro regime shift signal)
        htf_adjustment = min(2, htf_drift_count)

        # ── 4. Rolling performance degradation check ──────────────────────────
        # If EMA AUC is declining, lower the drift threshold to catch regime shifts earlier
        perf_degraded = False
        if self._ema_auc is not None and self._ema_auc < self.min_auc + 0.01:
            perf_degraded = True
            print(f'  ⚠️  Rolling AUC EMA={self._ema_auc:.4f} near floor — lowering drift gate')
            effective_limit = max(2, drift_limit - 2)
        else:
            effective_limit = drift_limit

        # FIX 11: Adjust effective_limit downward when HTF regime shift detected
        effective_limit_adj = max(2, effective_limit - htf_adjustment)
        if htf_adjustment > 0:
            print(f'  📡 HTF drift lowers consensus gate: {effective_limit} → {effective_limit_adj}')

        # Consensus drift check (with HTF adjustment)
        if len(consensus) < effective_limit_adj and not perf_degraded:
            print(f'  Consensus drift ({len(consensus)}) below limit ({effective_limit_adj}) — no retrain')
            return None

        if len(consensus) == 0 and not perf_degraded and htf_drift_count == 0:
            print(f'  No consensus drift (KS and PSI disagree) — no retrain')
            return None

        print(f'  ⚠️  Drift confirmed (consensus={len(consensus)}) — RETRAINING on {n - self.recent_bars:,} training bars...')

        # ── 5. FIX 8 (v27): Hold out df_recent BEFORE training ───────────────
        # Previous bug: df_recent was used BOTH as part of training data AND as
        # validation gate. The model could overfit to df_recent and still pass.
        # Fix: train ONLY on df_past (reference window), then validate on df_recent
        # which the model has never seen.
        df_train_only = df_window.iloc[:-(self.recent_bars)]   # exclude recent from training

        new_model = EnsembleModel()

        if RETRAIN_WARMSTART and current_model.is_trained:
            # Warm-start: LGBM (GBDT — now safe, Fix 3) + XGB + RF (Fix 10)
            print(f'  Warm-start: inheriting base model weights (LGBM GBDT + XGB + RF)...')
            try:
                if current_model.lgbm is not None:
                    new_model._warmstart_lgbm = current_model.lgbm
                if current_model.xgb is not None:
                    new_model._warmstart_xgb = current_model.xgb
                # FIX 10: RF warm-start
                if current_model.rf is not None:
                    new_model._warmstart_rf = current_model.rf
            except Exception:
                pass   # fall back to cold start silently

        try:
            # Train on df_train_only (NOT including df_recent — Fix 8)
            metrics = new_model.train(
                df_train_only, feature_cols, n_splits=3, verbose=False
            )
        except Exception as e:
            print(f'  ❌ Retrain failed: {e}')
            self._reject_streak += 1
            self._apply_backoff()
            return None

        cv_auc = metrics.get('cv_auc_mean', 0.0)
        print(f'  Retrain CV AUC: {cv_auc:.4f}')

        # ── 6. Validation gate — df_recent is truly OOS (Fix 8) ──────────────
        val_res = Backtester().run(df_recent, new_model, threshold=SIGNAL_THRESHOLD)
        if 'error' in val_res:
            print(f'  ❌ Validation: no trades — REJECTED')
            self._reject_streak += 1
            self._apply_backoff()
            self.registry.log_retrain({
                'resolution': resolution, 'status': 'rejected',
                'reason': 'no_trades', 'consensus_drift': len(consensus),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })
            return None

        win_rate = val_res['win_rate_pct']
        ret_pct  = val_res['total_return_pct']
        sharpe   = val_res['sharpe_ratio']
        n_trades = val_res['n_trades']
        print(f'  Validation → trades={n_trades} | WinRate={win_rate:.1f}% | '
              f'Return={ret_pct:.2f}% | Sharpe={sharpe:.3f}')

        # Uncertainty check: ensemble model disagreement on recent data
        if new_model.is_trained:
            X_recent = df_recent[feature_cols].dropna().values
            if len(X_recent) > 10:
                X_s       = new_model.scaler.transform(X_recent)
                unc       = new_model.predict_uncertainty(X_recent).mean()
                print(f'  Model uncertainty (mean std of base probs): {unc:.4f}')
                if unc > 0.15:
                    print(f'  ⚠️  High uncertainty ({unc:.3f}) — models disagree on recent data')

        passed = cv_auc >= self.min_auc and win_rate >= self.min_win_rate
        if not passed:
            print(f'  ❌ Gate FAILED (need AUC≥{self.min_auc}, WR≥{self.min_win_rate}%) — REJECTED')
            self._reject_streak += 1
            self._apply_backoff()
            self.registry.log_retrain({
                'resolution': resolution, 'status': 'rejected',
                'reason': 'validation_gate', 'cv_auc': cv_auc, 'win_rate': win_rate,
                'consensus_drift': len(consensus),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })
            return None

        # ── 7. Accept ─────────────────────────────────────────────────────────
        self._reject_streak = 0
        self.cooldown_hours = self.base_cooldown_hours   # reset backoff
        self._update_ema(cv_auc, win_rate)
        tag = f'auto_{int(time_module.time())}'
        self.registry.save_version(resolution, new_model, tag)
        self.registry.log_retrain({
            'resolution':     resolution,  'status': 'accepted', 'version': tag,
            'cv_auc':         cv_auc,      'win_rate': win_rate,
            'return_pct':     ret_pct,     'sharpe': sharpe,
            'consensus_drift':len(consensus), 'n_samples': n,
            'ema_auc':        self._ema_auc,  'ema_wr': self._ema_wr,
            'timestamp':      datetime.now(timezone.utc).isoformat(),
        })
        print(f'  ✅ Model ACCEPTED | version={tag} | EMA-AUC={self._ema_auc:.4f}')
        return new_model

    def _apply_backoff(self):
        """Double the cooldown on repeated failures (max 8h)."""
        self.cooldown_hours = min(8.0, self.cooldown_hours * 2)
        if self._reject_streak > 1:
            print(f'  ⏳ Backoff: cooldown extended to {self.cooldown_hours:.1f}h '
                  f'(streak={self._reject_streak})')


def hot_reload_model(resolution: str, registry: ModelRegistry) -> dict | None:
    """Always return the latest saved model, bypassing in-memory cache."""
    registry.invalidate_cache(resolution)
    return registry.load_latest(resolution)


class LiveTrader:
    """
    Live trading loop — thread-safe hot-swap, uncertainty-aware sizing. (v24)

    v24 additions:
    • Uncertainty-aware position sizing: model disagreement (std of base probs)
      reduces position size proportionally — prevents oversizing when models conflict.
    • Asymmetric signal thresholds (SIGNAL_THRESHOLD_LONG / _SHORT from config).
    • All v23 thread-safety fixes retained.
    """

    def __init__(
        self,
        client:         DeltaClient,
        model:          EnsembleModel,
        registry:       ModelRegistry  = None,
        retrain_engine: RetrainEngine  = None,
    ):
        self.client         = client
        self._model         = model
        self._model_lock    = threading.Lock()
        self.registry       = registry
        self.retrain_engine = retrain_engine
        self.position       = None
        self.trade_log      = []
        self.last_retrain   = datetime.now(timezone.utc)
        self.running        = False
        self.capital        = CAPITAL_USDT
        self.df_cache_5m      = pd.DataFrame()
        self.df_cache_15m     = pd.DataFrame()
        self.df_cache_1h      = pd.DataFrame()
        self.df_cache_funding = pd.DataFrame()
        self._cache_lock      = threading.Lock()   # BUG FIX 1: guards all cache R/W
        self._retrain_lock    = threading.Lock()   # prevents overlapping retrain threads
        # ISSUE 5 FIX: Drawdown circuit breaker
        self.peak_capital     = CAPITAL_USDT
        self.halted           = False              # True when max drawdown is breached

    @property
    def model(self) -> EnsembleModel:
        with self._model_lock:
            return self._model

    @model.setter
    def model(self, new_model: EnsembleModel):
        with self._model_lock:
            self._model = new_model

    def retrain(self):
        if not self._retrain_lock.acquire(blocking=False):
            print('  ℹ️  Retrain already in progress — skipping overlapping run')
            return
        print(f'\n🔄 [{datetime.now(timezone.utc).strftime("%H:%M:%S")}] Retraining...')
        try:
            self.last_retrain = datetime.now(timezone.utc)
            new_5m  = self.client.fetch_latest_candles(SYMBOL_5M,  CANDLE_RES_5M,  n_bars=5000)
            new_15m = self.client.fetch_latest_candles(SYMBOL_15M, CANDLE_RES_15M, n_bars=5000)
            new_1h  = self.client.fetch_latest_candles(SYMBOL_1H,  CANDLE_RES_1H,  n_bars=500)
            new_funding = fetch_funding_rate(SYMBOL_5M, n_bars=500)
            if new_5m.empty or new_15m.empty or new_1h.empty:
                print('  ⚠️  Incremental fetch empty — skipping')
                return
            if REQUIRE_FUNDING_DATA and (new_funding is None or new_funding.empty):
                print('  ⚠️  Funding fetch empty — skipping retrain to avoid placeholder features')
                return
            # BUG FIX 1: lock cache writes so on_bar() never reads a half-updated frame
            with self._cache_lock:
                for attr, new_df, cap in [
                    ('df_cache_5m',      new_5m,       100_000),
                    ('df_cache_15m',     new_15m,       50_000),
                    ('df_cache_1h',      new_1h,         5_000),
                    ('df_cache_funding', new_funding,      1_000),
                ]:
                    old    = getattr(self, attr)
                    merged = pd.concat([old, new_df]) if not old.empty else new_df
                    merged = (merged.drop_duplicates('timestamp')
                                    .sort_values('timestamp')
                                    .tail(cap)
                                    .reset_index(drop=True))
                    setattr(self, attr, merged)
                _df_1h_live   = self.df_cache_1h      if not self.df_cache_1h.empty      else None
                _df_fund_live = self.df_cache_funding  if not self.df_cache_funding.empty  else None
                df_feat = build_feature_matrix(
                    self.df_cache_5m,
                    self.df_cache_15m,
                    _df_1h_live,
                    _df_fund_live,
                    for_training=True,
                )
            if len(df_feat) < MIN_TRAIN_SAMPLES:
                print(f'  ⚠️  {len(df_feat)} rows < MIN_TRAIN_SAMPLES — skip')
                return
            if not self.retrain_engine:
                print('  ⚠️  RetrainEngine missing — refusing unvalidated fallback retrain')
                return
            _df_1h_rt = self.df_cache_1h if not self.df_cache_1h.empty else None
            new_model = self.retrain_engine.maybe_retrain('5m', df_feat, self.model, df_1h=_df_1h_rt)  # Fix 11
            if new_model is not None:
                self.model = new_model
                print('  ✅ Model hot-swapped via RetrainEngine v24')
        except Exception as e:
            print(f'  ❌ Retrain error: {e}')
        finally:
            self._retrain_lock.release()

    def get_latest_signal(self):
        """
        BUG FIX 2: Read from the rolling cache (populated by retrain()) instead of
        re-fetching full candle history on every 5-minute bar.
        Falls back to a fresh minimal fetch only if cache is cold (first call).
        BUG FIX 3: Uses model.feature_cols, not the global FEATURE_COLS.
        """
        feature_cols = getattr(self.model, 'feature_cols', None) or FEATURE_COLS

        # Thread-safe read of the rolling cache
        with self._cache_lock:
            df5   = self.df_cache_5m.copy()   if not self.df_cache_5m.empty      else pd.DataFrame()
            df15  = self.df_cache_15m.copy()  if not self.df_cache_15m.empty     else pd.DataFrame()
            df1h  = self.df_cache_1h.copy()   if not self.df_cache_1h.empty      else None
            dfund = self.df_cache_funding.copy() if not self.df_cache_funding.empty else None

        # Cold cache: do a one-time bootstrap fetch (happens at startup only)
        if df5.empty or df15.empty:
            warmup_5m  = max(500, WARMUP_CANDLES * 4 + 300)
            warmup_15m = max(400, WARMUP_CANDLES * 4 + 300)
            df5   = self.client.fetch_candles(SYMBOL_5M,  CANDLE_RES_5M,  n_bars=warmup_5m)
            df15  = self.client.fetch_candles(SYMBOL_15M, CANDLE_RES_15M, n_bars=warmup_15m)
            df1h  = self.client.fetch_candles(SYMBOL_1H,  CANDLE_RES_1H,  n_bars=300)
            dfund_raw = fetch_funding_rate(SYMBOL_5M, n_bars=200)
            dfund = dfund_raw if not dfund_raw.empty else None
            if REQUIRE_FUNDING_DATA and dfund is None:
                print('  ⚠️  Funding unavailable during cache bootstrap — returning flat')
                return 0, 0.5, 1.0
            # Warm the cache so next call is instant
            with self._cache_lock:
                self.df_cache_5m      = df5.copy()
                self.df_cache_15m     = df15.copy()
                self.df_cache_1h      = df1h.copy()  if df1h  is not None else pd.DataFrame()
                self.df_cache_funding = dfund.copy() if dfund is not None else pd.DataFrame()

        if df5.empty or df15.empty:
            return 0, 0.5, 1.0

        feat = build_feature_matrix(df5, df15, df1h, dfund, for_training=False)
        if feat.empty or len(feat) < 2:
            return 0, 0.5, 1.0

        last    = feat.iloc[-2]   # use last closed bar; inference matrix no longer loses the latest horizon window
        missing = [c for c in feature_cols if c not in last.index or pd.isna(last[c])]
        if missing:
            print(f'  ⚠️  NaN features ({len(missing)}): {missing[:5]} — returning flat')
            return 0, 0.5, 1.0

        X           = last[feature_cols].values.reshape(1, -1).astype('float32')
        X_df        = feat.iloc[[-2]][feature_cols]
        sig, proba  = self.model.predict_signal(X, X_df=X_df)
        uncertainty = float(self.model.predict_uncertainty(X)[0])
        return int(sig[0]), float(proba[0]), uncertainty

    def _position_size(self, capital: float, price: float, uncertainty: float) -> float:
        """
        Uncertainty-aware Kelly-capped position size.
        High model disagreement (uncertainty > 0.12) reduces size to protect capital.
        """
        base_size = capital * MAX_POSITION_PCT * LEVERAGE
        unc_scale = float(np.clip(1.0 - (uncertainty - 0.05) * 5, 0.3, 1.0))
        return min(base_size * unc_scale, capital * LEVERAGE)

    def open_position(self, side: str, price: float, uncertainty: float = 0.0):
        try:
            if LONG_ONLY_EXECUTION and side != 'long':
                print('  ⚠️  Short execution disabled because the target is trained as long/flat only')
                return
            size      = self._position_size(self.capital, price, uncertainty)
            contracts = max(1, int(size / price))
            # Improvement 6 (v28): Crisis guard — force flat during market stress
            with self._cache_lock:
                _df5   = self.df_cache_5m.copy() if not self.df_cache_5m.empty else pd.DataFrame()
                _df15  = self.df_cache_15m.copy() if not self.df_cache_15m.empty else pd.DataFrame()
                _df1h  = self.df_cache_1h.copy() if not self.df_cache_1h.empty else None
                _dfund = self.df_cache_funding.copy() if not self.df_cache_funding.empty else None
            _df_recent_feats = build_feature_matrix(_df5, _df15, _df1h, _dfund, for_training=False).tail(50)
            if is_crisis_regime(_df_recent_feats):
                print('⛔ Crisis regime detected — forcing flat, no signal generated')
                return

            resp      = self.client.place_order(
                SYMBOL_5M, side='buy' if side == 'long' else 'sell', size=contracts
            )
            self.position = {
                'side':        side,
                'entry_price': price,
                'contracts':   contracts,
                'entry_time':  datetime.now(timezone.utc),
                'uncertainty': round(uncertainty, 4),
                'sl': price * (1 - STOP_LOSS_PCT)  if side == 'long' else price * (1 + STOP_LOSS_PCT),
                'tp': price * (1 + TAKE_PROFIT_PCT) if side == 'long' else price * (1 - TAKE_PROFIT_PCT),
            }
            print(f'  📥 Opened {side} | {contracts} contracts @ {price:.2f} '
                  f'| unc={uncertainty:.3f} | SL={self.position["sl"]:.2f} | TP={self.position["tp"]:.2f}')
        except Exception as e:
            print(f'  ❌ Order error: {e}')

    def close_position(self, price: float, reason: str):
        if self.position is None:
            return
        pos = self.position
        side, ep = pos['side'], pos['entry_price']
        pnl_pct = ((price - ep) / ep) if side == 'long' else ((ep - price) / ep)
        pnl_usd = pos['contracts'] * price * pnl_pct / LEVERAGE
        try:
            self.client.place_order(
                SYMBOL_5M, side='sell' if side == 'long' else 'buy', size=pos['contracts']
            )
        except Exception as e:
            print(f'  ❌ Close error: {e}')
        self.capital += pnl_usd
        self.trade_log.append({
            'time': datetime.now(timezone.utc), 'side': side,
            'entry': ep, 'exit': price, 'pnl_pct': round(pnl_pct * 100, 3),
            'pnl_usd': round(pnl_usd, 2), 'reason': reason,
            'capital': round(self.capital, 2), 'uncertainty': pos.get('uncertainty', 0),
        })
        print(f'  📤 Closed {side} @ {price:.2f} | {reason} | '
              f'PnL={pnl_usd:+.2f} USDT | capital={self.capital:.2f}')
        self.position = None

    def on_bar(self):
        # ISSUE 5 FIX: Drawdown circuit breaker
        if self.halted:
            print('⛔ Bot halted — maximum drawdown limit reached. Manual review required.')
            return
        self.peak_capital = max(self.peak_capital, self.capital)
        _dd = (self.peak_capital - self.capital) / (self.peak_capital + 1e-9)
        if _dd > MAX_DRAWDOWN_HALT:
            self.halted = True
            print(f'⛔ HALT: Drawdown {_dd:.1%} exceeded {MAX_DRAWDOWN_HALT:.0%} limit')
            return

        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        try:
            price = self.client.get_ticker(SYMBOL_5M)
        except Exception as e:
            print(f'[{now}] Ticker error: {e}')
            return
        if self.position:
            p = self.position
            if p['side'] == 'long':
                if price <= p['sl']:  self.close_position(p['sl'], 'sl'); return
                if price >= p['tp']:  self.close_position(p['tp'], 'tp'); return
            else:
                if price >= p['sl']:  self.close_position(p['sl'], 'sl'); return
                if price <= p['tp']:  self.close_position(p['tp'], 'tp'); return
        mins_since = (datetime.now(timezone.utc) - self.last_retrain).seconds / 60
        if mins_since >= RETRAIN_INTERVAL_MINUTES:
            threading.Thread(target=self.retrain, daemon=True).start()
        sig, proba, unc = self.get_latest_signal()
        print(f'[{now}] price={price:.2f} | sig={sig:+d} | proba={proba:.3f} | '
              f'unc={unc:.3f} | pos={self.position["side"] if self.position else "flat"} | '
              f'capital={self.capital:.2f}')
        if self.position is None and sig == 1:
            self.open_position('long', price, unc)
        elif self.position is not None:
            cur = self.position['side']
            if (not LONG_ONLY_EXECUTION) and ((cur == 'long' and sig == -1) or (cur == 'short' and sig == 1)):
                self.close_position(price, 'signal')

    def start(self, dry_run: bool = True):
        if dry_run:
            print('⚠️  DRY RUN MODE — no real orders will be placed')
            self.client.place_order = lambda *a, **k: {'result': 'dry_run'}
        self.running = True
        print(f'🚀 LiveTrader v24 started | Capital={self.capital} USDT | '
              f'Retrain every {RETRAIN_INTERVAL_MINUTES}m')
        schedule.clear()
        schedule.every(5).minutes.do(self.on_bar)
        self.on_bar()
        while self.running:
            schedule.run_pending()
            time_module.sleep(1)

    def stop(self):
        self.running = False
        print('🛑 LiveTrader stopped')
        if self.trade_log:
            print('\n📋 Trade Log:')
            print(pd.DataFrame(self.trade_log).to_string(index=False))


print('✅ ModelRegistry, RetrainEngine v27 + LiveTrader v27 defined')
print('   Fix 8: retrain gate holds out df_recent BEFORE training (true OOS gate)')
print('   Fix 10: RF warm-start passed to new_model._warmstart_rf')
print('   Fix 11: HTF drift detection on native 1h data (not merged step-function)')
print('   Bug Fix 1: _cache_lock guards df_cache_* R/W (no race condition)')
print('   Bug Fix 2: get_latest_signal() reads rolling cache (no per-bar refetch)')
print('   Bug Fix 3: Backtester uses model.feature_cols not global FEATURE_COLS')

# ==== CELL 31 ====
# ── Cell 12: Offline Retrain Test ────────────────────────────────────────────
# Runs and exits cleanly. All config is in Cell 2 (RETRAIN_* variables).

from scipy.stats import ks_2samp
import matplotlib.pyplot as plt

print('=' * 60)
print('🔬 OFFLINE RETRAIN TEST (v27 — Fix 8: OOS gate | Fix 10: RF warm-start | Fix 11: HTF drift)')
print('=' * 60)
print(f'  Cycles         : {RETRAIN_CYCLES}')
print(f'  Past window    : {RETRAIN_WINDOW_PAST_BARS:,} bars')
print(f'  Recent window  : {RETRAIN_WINDOW_RECENT_BARS:,} bars')
print(f'  Drift limit    : {RETRAIN_DRIFT_FEATURE_LIMIT} features')
print(f'  Gate           : AUC≥{RETRAIN_VALIDATION_MIN_AUC} | WinRate≥{RETRAIN_VALIDATION_MIN_WR}%')

total_bars = len(df_features)
needed     = RETRAIN_WINDOW_PAST_BARS + RETRAIN_WINDOW_RECENT_BARS
if total_bars < needed:
    raise ValueError(
        f'Not enough data: {total_bars} bars available, '
        f'need {needed} (PAST + RECENT). '
        f'Reduce RETRAIN_WINDOW_PAST_BARS / RETRAIN_WINDOW_RECENT_BARS in Cell 2.'
    )

step_size   = max(1, (total_bars - needed) // max(1, RETRAIN_CYCLES - 1))
retrain_log = []
active_model = model  # start from the model trained in Cell 7
_df_1h_rt      = df_1h      if 'df_1h'      in globals() and not df_1h.empty      else None
_df_funding_rt = df_funding  if 'df_funding'  in globals() and not df_funding.empty  else None

for cycle in range(RETRAIN_CYCLES):
    offset     = cycle * step_size
    past_start = offset
    past_end   = offset + RETRAIN_WINDOW_PAST_BARS
    recent_end = past_end + RETRAIN_WINDOW_RECENT_BARS

    if recent_end > total_bars:
        print(f'\n  Cycle {cycle+1}: window exceeds data length — stopping early')
        break

    df_past   = df_features.iloc[past_start:past_end].copy()
    df_recent = df_features.iloc[past_end:recent_end].copy()
    df_window = df_features.iloc[past_start:recent_end].copy()

    t_past_start   = df_past['timestamp'].iloc[0].date()
    t_recent_start = df_recent['timestamp'].iloc[0].date()
    t_recent_end   = df_recent['timestamp'].iloc[-1].date()

    print(f'\n{"-"*60}')
    print(f'  Cycle {cycle+1}/{RETRAIN_CYCLES}')
    print(f'  Past   : {t_past_start} → {t_recent_start}  ({len(df_past):,} bars)')
    print(f'  Recent : {t_recent_start} → {t_recent_end}  ({len(df_recent):,} bars)')

    # ── Step 1: Drift detection ───────────────────────────────────────────────
    # ISSUE 2 FIX: Use KS+PSI consensus (matches live RetrainEngine.maybe_retrain() logic)
    # Old code used KS-only which is more trigger-happy than the live engine,
    # making Cell 12 retrain frequency metrics unrepresentative of production behaviour.
    ks_drifted  = set()
    psi_drifted = set()
    ks_details  = {}

    for col in FEATURE_COLS:
        if col not in df_past.columns:
            continue
        a = df_past[col].dropna().values
        b = df_recent[col].dropna().values
        if len(a) < 30 or len(b) < 30:
            continue
        try:
            stat, p_val = ks_2samp(a, b)
            if p_val < 0.01 and stat > 0.1:
                ks_drifted.add(col)
                ks_details[col] = (round(p_val, 5), round(stat, 4))
            psi = _psi_score(a, b)
            if psi > PSI_THRESHOLD:
                psi_drifted.add(col)
        except Exception:
            pass

    # Consensus: both KS and PSI must agree (matches live engine)
    drifted_consensus = ks_drifted & psi_drifted
    drifted = [(col, *ks_details.get(col, (0, 0))) for col in drifted_consensus]
    drifted_sorted = sorted(drifted, key=lambda x: x[2], reverse=True)

    print(f'  KS drifted     : {len(ks_drifted)} / {len(FEATURE_COLS)}')
    print(f'  PSI drifted    : {len(psi_drifted)} / {len(FEATURE_COLS)}')
    print(f'  Consensus (KS∩PSI): {len(drifted_consensus)} features')
    if drifted_sorted:
        print(f'  Top drifted    : {[d[0] for d in drifted_sorted[:5]]}')

    if len(drifted_consensus) < RETRAIN_DRIFT_FEATURE_LIMIT:
        print(f'  ✅ No retrain — consensus drift ({len(drifted_consensus)}) below limit ({RETRAIN_DRIFT_FEATURE_LIMIT})')
        retrain_log.append({
            'cycle': cycle + 1, 'period': f'{t_recent_start}→{t_recent_end}',
            'drifted': len(drifted_consensus), 'retrained': False, 'reason': 'below_drift_limit',
        })
        continue

    # ── Step 2: FIX 8 (v27) — Retrain on df_past ONLY, validate on df_recent ───
    # Previous bug: retraining on df_window (which included df_recent) meant
    # the model could overfit to df_recent and still pass the validation gate.
    print(f'  ⚠️  Drift exceeded — RETRAINING on {len(df_past):,} bars (past only, Fix 8)...')
    new_model = EnsembleModel()
    try:
        metrics = new_model.train(df_past, FEATURE_COLS, n_splits=3, verbose=False)
    except Exception as e:
        print(f'  ❌ Retrain failed: {e}')
        retrain_log.append({
            'cycle': cycle + 1, 'period': f'{t_recent_start}→{t_recent_end}',
            'drifted': len(drifted), 'retrained': False, 'reason': f'train_error: {e}',
        })
        continue

    cv_auc = metrics.get('cv_auc_mean', 0.0)
    print(f'  Retrain CV AUC : {cv_auc:.4f}')

    # ── Step 3: Validation gate — backtest on recent window ───────────────────
    val_res = Backtester().run(df_recent, new_model, threshold=SIGNAL_THRESHOLD)
    if 'error' in val_res:
        print(f'  ❌ Validation: no trades — REJECTED')
        retrain_log.append({
            'cycle': cycle + 1, 'period': f'{t_recent_start}→{t_recent_end}',
            'drifted': len(drifted), 'cv_auc': cv_auc,
            'retrained': False, 'reason': 'no_trades',
        })
        continue

    win_rate = val_res['win_rate_pct']
    ret_pct  = val_res['total_return_pct']
    sharpe   = val_res['sharpe_ratio']
    n_tr     = val_res['n_trades']
    print(f'  Validation     : trades={n_tr} | WinRate={win_rate:.1f}% | '
          f'Return={ret_pct:.2f}% | Sharpe={sharpe:.3f}')

    passed = cv_auc >= RETRAIN_VALIDATION_MIN_AUC and win_rate >= RETRAIN_VALIDATION_MIN_WR
    if passed:
        active_model = new_model
        active_model.save(MODEL_DIR)
        print(f'  ✅ ACCEPTED — model hot-swapped (AUC={cv_auc:.4f}, WR={win_rate:.1f}%)')
        retrain_log.append({
            'cycle': cycle + 1, 'period': f'{t_recent_start}→{t_recent_end}',
            'drifted': len(drifted), 'cv_auc': round(cv_auc, 4),
            'win_rate': win_rate, 'return_pct': ret_pct, 'sharpe': sharpe,
            'n_trades': n_tr, 'retrained': True, 'reason': 'accepted',
        })
    else:
        print(f'  ❌ REJECTED — gate failed '
              f'(need AUC≥{RETRAIN_VALIDATION_MIN_AUC}, WR≥{RETRAIN_VALIDATION_MIN_WR}%)')
        retrain_log.append({
            'cycle': cycle + 1, 'period': f'{t_recent_start}→{t_recent_end}',
            'drifted': len(drifted), 'cv_auc': round(cv_auc, 4),
            'win_rate': win_rate, 'retrained': False, 'reason': 'gate_failed',
        })

# ── Summary ───────────────────────────────────────────────────────────────────
print(f'\n{"="*60}')
print('📋 RETRAIN CYCLE SUMMARY')
print('=' * 60)
df_retrain_summary = pd.DataFrame(retrain_log)
display_cols = [c for c in [
    'cycle', 'period', 'drifted', 'cv_auc', 'win_rate',
    'return_pct', 'sharpe', 'n_trades', 'retrained', 'reason'
] if c in df_retrain_summary.columns]
print(df_retrain_summary[display_cols].to_string(index=False))

n_retrained = sum(r['retrained'] for r in retrain_log)
print(f'\n  Cycles run      : {len(retrain_log)}')
print(f'  Retrains fired  : {n_retrained}')
print(f'  Retrains accepted: {n_retrained}')
print(f'  Model in use    : {"hot-swapped" if n_retrained > 0 else "original (Cell 7)"}')
print('\n✅ Offline retrain test complete')

# Store for Cell 13
_retrain_log     = retrain_log
_retrain_summary = df_retrain_summary

# ==== CELL 33 ====
# ── Cell 13: Retrain Summary Visual ─────────────────────────────────────────
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

if '_retrain_summary' not in dir() or _retrain_summary.empty:
    print('No retrain log found — run Cell 12 first.')
else:
    df_s = _retrain_summary.copy()
    n    = len(df_s)
    cycles = df_s['cycle'].astype(str).tolist()

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), facecolor='#0d1117')
    fig.suptitle('Offline Retrain Test — Summary', color='#c9d1d9', fontsize=14)
    for ax in axes.flat:
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e')
        ax.spines[:].set_color('#30363d')

    # ── Plot 1: Drifted features per cycle ────────────────────────────────────
    ax = axes[0, 0]
    colors = ['#f85149' if d >= RETRAIN_DRIFT_FEATURE_LIMIT else '#58a6ff'
              for d in df_s['drifted']]
    ax.bar(cycles, df_s['drifted'], color=colors)
    ax.axhline(RETRAIN_DRIFT_FEATURE_LIMIT, color='#ff7b72', ls='--', lw=1, label=f'Limit={RETRAIN_DRIFT_FEATURE_LIMIT}')
    ax.set_title('Drifted Features / Cycle', color='#c9d1d9')
    ax.set_xlabel('Cycle', color='#8b949e')
    ax.legend(facecolor='#161b22', labelcolor='#c9d1d9', fontsize=8)

    # ── Plot 2: CV AUC per cycle ──────────────────────────────────────────────
    ax = axes[0, 1]
    if 'cv_auc' in df_s.columns:
        auc_vals = df_s['cv_auc'].fillna(0)
        bar_colors = ['#3fb950' if v >= RETRAIN_VALIDATION_MIN_AUC else '#f85149' for v in auc_vals]
        ax.bar(cycles, auc_vals, color=bar_colors)
        ax.axhline(RETRAIN_VALIDATION_MIN_AUC, color='#ff7b72', ls='--', lw=1,
                   label=f'Gate={RETRAIN_VALIDATION_MIN_AUC}')
        ax.set_ylim(0, 1)
        ax.set_title('Retrain CV AUC / Cycle', color='#c9d1d9')
        ax.set_xlabel('Cycle', color='#8b949e')
        ax.legend(facecolor='#161b22', labelcolor='#c9d1d9', fontsize=8)
    else:
        ax.text(0.5, 0.5, 'No AUC data\n(no retrains triggered)',
                ha='center', va='center', color='#8b949e', transform=ax.transAxes)
        ax.set_title('Retrain CV AUC / Cycle', color='#c9d1d9')

    # ── Plot 3: Win rate per cycle ────────────────────────────────────────────
    ax = axes[1, 0]
    if 'win_rate' in df_s.columns:
        wr_vals = df_s['win_rate'].fillna(0)
        wr_colors = ['#3fb950' if v >= RETRAIN_VALIDATION_MIN_WR else '#f85149' for v in wr_vals]
        ax.bar(cycles, wr_vals, color=wr_colors)
        ax.axhline(RETRAIN_VALIDATION_MIN_WR, color='#ff7b72', ls='--', lw=1,
                   label=f'Gate={RETRAIN_VALIDATION_MIN_WR}%')
        ax.set_title('Validation Win Rate % / Cycle', color='#c9d1d9')
        ax.set_xlabel('Cycle', color='#8b949e')
        ax.legend(facecolor='#161b22', labelcolor='#c9d1d9', fontsize=8)
    else:
        ax.text(0.5, 0.5, 'No win-rate data\n(no retrains triggered)',
                ha='center', va='center', color='#8b949e', transform=ax.transAxes)
        ax.set_title('Validation Win Rate % / Cycle', color='#c9d1d9')

    # ── Plot 4: Outcome status ────────────────────────────────────────────────
    ax = axes[1, 1]
    reasons = df_s['reason'].value_counts()
    pie_colors = {
        'accepted':         '#3fb950',
        'below_drift_limit':'#58a6ff',
        'gate_failed':      '#f85149',
        'no_trades':        '#ff7b72',
        'train_error':      '#6e7681',
    }
    wedge_colors = [pie_colors.get(r, '#8b949e') for r in reasons.index]
    ax.pie(reasons.values, labels=reasons.index, colors=wedge_colors,
           autopct='%1.0f%%', textprops={'color': '#c9d1d9', 'fontsize': 9})
    ax.set_title('Cycle Outcomes', color='#c9d1d9')

    plt.tight_layout()
    plt.savefig('/content/retrain_summary.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117')
    plt.show()
    print('💾 Chart saved to /content/retrain_summary.png')

# ==== CELL 34 ====
# ── Cell 14: Export artifacts (P8 — unified artifact bundle) ──────────────
# Downloads model directory as zip + confirms the unified artifact is present.
import shutil, sys, json as _json
from pathlib import Path
from datetime import datetime as _dt

BROWSER_DOWNLOAD = True   # Set False to only print paths
ALSO_COPY_ZIP_TO = None   # e.g. Path('/content/drive/MyDrive/JackSparrow_v24.zip')

root = Path(MODEL_DIR)
if not root.is_dir() or not any(root.iterdir()):
    print(f'No artifacts under {root} — run Cell 7 first.')
else:
    # ── P8: confirm / create unified artifact ────────────────────────────
    artifact_path = root / 'model_artifact_v27.pkl'
    if artifact_path.exists():
        print(f'✅ Unified artifact present: {artifact_path}')
    else:
        print('⚠️  model_artifact_v27.pkl not found — recreating from saved parts ...')
        import joblib as _jl
        _m = EnsembleModel()
        _m.load(str(root))
        _fe = _jl.load(str(root / 'feature_engineer.pkl')) if (root / 'feature_engineer.pkl').exists() else None
        _artifact = {
            'model':    _m,
            'features': _m.feature_cols,
            'scaler':   _m.scaler,
            'feature_engineer': _fe,
            'metadata': {'version': 'v27', 'recreated_at': _dt.utcnow().isoformat(), 'rethink': 'v27-11fixes'},
        }
        _jl.dump(_artifact, str(artifact_path))
        print(f'✅ Unified artifact saved: {artifact_path}')

    # ── Write human-readable metadata sidecar ────────────────────────────
    meta_path = root / 'metadata_v27.json'
    meta = {
        'version':    'v27',
        'symbol':     SYMBOL_5M,
        'exported_at': _dt.utcnow().isoformat(),
        'feature_count': len(FEATURE_COLS),
        'features':   FEATURE_COLS,
        'agent_load': (
            'artifact = joblib.load("model_artifact_v27.pkl")\n'
            'model    = artifact["model"]\n'
            'features = artifact["features"]\n'
            'fe       = artifact["feature_engineer"]\n'
            'df_feat  = fe.transform(df5, df15, df1h, df_funding, include_target=False)\n'
            'X        = df_feat[features].iloc[[-2]].values\n'
            'X_df     = df_feat[features].iloc[[-2]]\n'
            'proba    = model.predict_proba(X, X_df=X_df)'
        ),
    }
    meta_path.write_text(_json.dumps(meta, indent=2))
    print(f'✅ Metadata sidecar: {meta_path}')

    # ── Zip and download ─────────────────────────────────────────────────
    safe_sym = str(SYMBOL_5M).replace('/', '_')
    if 'google.colab' in sys.modules:
        zip_base = str(Path('/content') / f'JackSparrow_v27_models_{safe_sym}')
    else:
        zip_base = str(Path.cwd() / f'JackSparrow_v27_models_{safe_sym}')
    zip_path = zip_base + '.zip'
    shutil.make_archive(zip_base, 'zip', root_dir=str(root.parent), base_dir=root.name)
    print(f'✅ Archive: {zip_path}')
    if ALSO_COPY_ZIP_TO is not None:
        dest = Path(ALSO_COPY_ZIP_TO)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(zip_path, dest)
        print(f'✅ Copied to: {dest}')
    if BROWSER_DOWNLOAD and 'google.colab' in sys.modules:
        from google.colab import files
        files.download(zip_path)
        print('✅ Browser download started.')
    elif not BROWSER_DOWNLOAD:
        print('BROWSER_DOWNLOAD=False — copy from path above.')

print('\n📦 Agent load snippet:')
print('   artifact = joblib.load("model_artifact_v27.pkl")')
print('   model    = artifact["model"]')
print('   fe       = artifact["feature_engineer"]')
print('   df_feat  = fe.transform(df5, df15, df1h, df_funding, include_target=False)')
print('   X        = df_feat[artifact["features"]].iloc[[-2]].values')
print('   X_df     = df_feat[artifact["features"]].iloc[[-2]]')
print('   proba    = model.predict_proba(X, X_df=X_df)')

