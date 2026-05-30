"""Insert section 3c (optional return heads) into v43 training notebook."""
import json
from pathlib import Path

nb_path = Path(__file__).resolve().parents[1] / "notebooks/jacksparrow_v43_delta_india_training.ipynb"
nb = json.loads(nb_path.read_text(encoding="utf-8"))

if any(c.get("id") == "v43-3c-return-code" for c in nb["cells"]):
    print("3c cells already present")
    raise SystemExit(0)

md = {
    "cell_type": "markdown",
    "metadata": {},
    "source": [
        "## 3c) Optional return-regression heads (diagnostic)\n",
        "\n",
        "Trained when `V43_TRAIN_RETURN_HEADS` is `minimal` (primary horizon) or `full` (all horizons). "
        "Set `none` for a conditions-only bundle. With `V43_PRIMARY_SIGNAL_MODE=conditions`, "
        "runtime direction comes from state heads, not return regression.\n",
    ],
    "id": "v43-3c-return-md",
}
code = {
    "cell_type": "code",
    "metadata": {},
    "source": [
        "from feature_store.jacksparrow_v43_multihead import resolve_train_return_horizons\n",
        "from feature_store.jacksparrow_v43_labels import resolve_v43_primary_signal_mode\n",
        "\n",
        "_return_keys = resolve_train_return_horizons()\n",
        '_use_meta = os.environ.get("V43_USE_META_STACK", "false").strip().lower() in ("1", "true", "yes")\n',
        "if _return_keys:\n",
        "    _ret_bundle, _ret_meta = train_multihead_from_feature_matrix(\n",
        "        df_feat[feat_cols],\n",
        "        close,\n",
        "        feat_cols=feat_cols,\n",
        '        validation_fraction=float(os.environ.get("V43_VALIDATION_FRACTION", "0.15")),\n',
        "        rng=_train_rng,\n",
        "        maker_fee=_maker_fee,\n",
        "        slippage=_slippage,\n",
        "        leverage=_leverage,\n",
        "        cost_aware_labels=False,\n",
        "        use_meta_stack=_use_meta,\n",
        "        horizon_keys=_return_keys,\n",
        "    )\n",
        "    for _fb in _ret_bundle.head_bars():\n",
        "        multi_bundle.set_head(_fb, _ret_bundle.get_head(_fb))\n",
        '    metadata["horizons"] = _ret_meta.get("horizons", {})\n',
        '    metadata["split"] = _ret_meta.get("split", {})\n',
        '    metadata["target_definition"] = _ret_meta.get("target_definition")\n',
        '    metadata["runtime_cost_assumptions"] = _ret_meta.get("runtime_cost_assumptions", {})\n',
        '    metadata["return_heads_trained"] = _return_keys\n',
        '    _primary_key = {2: "scalp_10m", 6: "intraday_30m", 12: "trend_1h", 24: "swing_2h"}.get(_primary_bars, "trend_1h")\n',
        '    validation_metrics = metadata["horizons"][_primary_key]["validation_metrics"]\n',
        '    split_metadata = metadata.get("split", {})\n',
        "    primary_ensemble = multi_bundle.get_head(_primary_bars)\n",
        '    print("Return heads trained:", _return_keys)\n',
        '    print(f"Return diagnostic corr ({_primary_key}):", validation_metrics.get("validation_corr"))\n',
        '    print("round_trip_cost_pct:", metadata.get("runtime_cost_assumptions", {}).get("round_trip_cost_pct"))\n',
        "else:\n",
        '    metadata["horizons"] = {}\n',
        '    metadata["return_heads_trained"] = []\n',
        "    validation_metrics = {}\n",
        "    split_metadata = {}\n",
        "    primary_ensemble = None\n",
        '    print("Skipped return-regression heads (V43_TRAIN_RETURN_HEADS=none)")\n',
        'metadata["primary_signal_mode"] = resolve_v43_primary_signal_mode()\n',
    ],
    "id": "v43-3c-return-code",
}

idx = None
for i, c in enumerate(nb["cells"]):
    if c.get("cell_type") == "code" and "train_state_heads_from_feature_matrix" in "".join(
        c.get("source", [])
    ):
        idx = i + 1
        break
if idx is None:
    raise SystemExit("state head cell not found")

nb["cells"][idx:idx] = [md, code]
nb_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("inserted 3c at cell index", idx)
