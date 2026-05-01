"""v15 feature dict smoke (train/serve alignment)."""

import math

from feature_store.v15_feature_compute import build_v15_feature_dict_for_tf


def test_build_v15_feature_dict_15m_nonempty() -> None:
    candles = []
    for i in range(200):
        p = 100.0 + 0.2 * i
        candles.append(
            {
                "open": p,
                "high": p + 0.5,
                "low": p - 0.5,
                "close": p + 0.1,
                "volume": 1000.0,
            }
        )
    d = build_v15_feature_dict_for_tf(candles, "15m")
    assert len(d) >= 5
    finite = [v for v in d.values() if isinstance(v, (float, int)) and math.isfinite(float(v))]
    assert len(finite) >= 5
