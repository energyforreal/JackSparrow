"""Sanity check: nested metadata layout under MODEL_DIR is discoverable via rglob."""

from pathlib import Path
import tempfile


def test_nested_metadata_json_is_findable_by_rglob():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        nested = root / "jacksparrow_vX_BTCUSD"
        nested.mkdir(parents=True)
        meta = nested / "metadata_BTCUSD_5m.json"
        meta.write_text("{}", encoding="utf-8")

        top = list(root.glob("metadata_BTCUSD_*.json"))
        deep = list(root.rglob("metadata_BTCUSD_*.json"))
        assert top == []
        assert len(deep) == 1
        assert deep[0] == meta
