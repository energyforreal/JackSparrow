"""One-off patch: jacksparrow_v43_delta_india_training.ipynb → multi-head export.

STALE — do not run on major-rework. Export lives in notebook cell 25 with
primary_execution_horizon_bars=2 (scalp_10m). This script targets obsolete cell
indices and would corrupt the notebook.
"""
from __future__ import annotations

import json
from pathlib import Path

raise RuntimeError(
    "patch_v43_notebook_multihead.py is stale on major-rework — "
    "do not run. Use notebooks/jacksparrow_v43_delta_india_training.ipynb cell 25."
)

NB = Path(__file__).resolve().parents[1] / "notebooks" / "jacksparrow_v43_delta_india_training.ipynb"

CELL_0 = """# JackSparrow v43 multi-head — Delta Exchange India (Colab)

Train one **multi-head** bundle (`metadata_v43.json` + `model_artifact_v43.pkl`) with intraday horizons:

| Key | Forward bars | ~Minutes |
|-----|----------------|----------|
| scalp_10m | 2 | 10m |
| intraday_30m | 6 | 30m |
| trend_1h | 12 | 1h |
| swing_2h | 24 | 2h |

Local export: `python scripts/train_v43_multihead_export.py --feature-csv <path>`
"""

CELL_12 = """## 3) Features and multi-head labels (v43 contract)

- Features: `build_v43_feature_matrix(...)` then `V43_CANONICAL_FEATURES` order.
- Labels: per-head simple forward returns via `train_multihead_from_feature_matrix` (2/6/12/24 bars).
- Export: single `MultiHeadBundle` artifact + `horizons{}` metadata (see §5).
"""

CELL_13 = """df_feat = build_v43_feature_matrix(
    df_5m,
    None,
    None,
    df_funding,
    for_training=True,
    primary_interval="5m",
)

close = pd.to_numeric(df_5m["close"], errors="coerce").reindex(df_feat.index)
feat_cols = list(V43_CANONICAL_FEATURES)

from feature_store.jacksparrow_v43_train_multihead import train_multihead_from_feature_matrix

multi_bundle, metadata = train_multihead_from_feature_matrix(
    df_feat[feat_cols],
    close,
    feat_cols=feat_cols,
    validation_fraction=0.15,
)

validation_metrics = metadata["horizons"]["intraday_30m"]["validation_metrics"]
split_metadata = metadata.get("split", {})
ensemble = multi_bundle.get_head(6)
print("Multi-head training complete. Horizons:", list(metadata.get("horizons", {}).keys()))
print("Primary execution head (6 bars) validation_corr:", validation_metrics.get("validation_corr"))
"""

CELL_14 = """## 4) Legacy single-head cells (skipped)

Per-head training, meta-stack, and walk-forward analysis now run inside
`feature_store/jacksparrow_v43_train_multihead.py` for all four horizons in one export.
"""

SKIP_CODE = "# Legacy single-head training removed — see multi-head train cell above.\n"

CELL_20_PREFIX = """# Multi-head export (replaces single ensemble export below)
from feature_store.jacksparrow_v43_train_multihead import artifact_dict_from_bundle
from feature_store.jacksparrow_v43_multihead import V43_MULTIHEAD_MODEL_FAMILY, V43_MULTIHEAD_ARTIFACT_FORMAT

"""


def main() -> None:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    nb["cells"][0]["source"] = [CELL_0]
    nb["cells"][12]["source"] = [CELL_12]
    nb["cells"][13]["source"] = [CELL_13]
    nb["cells"][14]["source"] = [CELL_14]
    for i in (15, 17, 18):
        nb["cells"][i]["source"] = [SKIP_CODE]
    src20 = "".join(nb["cells"][20]["source"])
    src20 = src20.replace('"model": ensemble,', '"model": multi_bundle,')
    src20 = src20.replace(
        'artifact_payload = {\n    "model": multi_bundle,',
        'artifact_payload = artifact_dict_from_bundle(multi_bundle, fe)\nartifact_payload.update({',
        1,
    )
    src20 = src20.replace(
        '"validation_metrics": validation_metrics,\n}',
        "})\n",
        1,
    )
    src20 = src20.replace(
        'meta = {\n    "version": "v43",',
        'meta = dict(metadata)\nmeta.update({\n    "version": "v43",',
        1,
    )
    src20 = src20.replace(
        '"training_forward_bars": V43_FORWARD_TARGET_BARS,',
        '"model_family": V43_MULTIHEAD_MODEL_FAMILY,\n    "artifact_format": V43_MULTIHEAD_ARTIFACT_FORMAT,\n    "primary_execution_horizon_bars": 6,',
        1,
    )
    src20 = src20.replace(
        '"split": split_metadata,\n    "validation_metrics": validation_metrics,',
        '"split": split_metadata,',
        1,
    )
    if "artifact_dict_from_bundle" not in src20:
        src20 = CELL_20_PREFIX + src20
    nb["cells"][20]["source"] = [src20]
    c22 = "".join(nb["cells"][22]["source"])
    c22 = c22.replace("ensemble.predict", "multi_bundle.get_head(6).predict")
    c22 = c22.replace(
        'assert meta_loaded["split"]["embargo_bars"] == V43_FORWARD_TARGET_BARS',
        'assert "horizons" in meta_loaded and "intraday_30m" in meta_loaded["horizons"]',
    )
    nb["cells"][22]["source"] = [c22]
    NB.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print("Patched", NB)


if __name__ == "__main__":
    main()
