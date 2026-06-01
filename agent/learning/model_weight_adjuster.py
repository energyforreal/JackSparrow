"""Model weight adjuster stub — single IC node (NO-ML branch)."""

from __future__ import annotations

from typing import Dict


class ModelWeightAdjuster:
    """Returns unit weight for the sole intelligence node."""

    def calculate_weights(self, model_names: list[str]) -> Dict[str, float]:
        if not model_names:
            return {}
        w = 1.0 / len(model_names)
        return {name: w for name in model_names}
