"""Standalone script to validate model inference pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_node import MCPModelRequest, MCPModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry

logger = structlog.get_logger()


def _load_metadata(model_path: Path) -> Dict:
    """Load metadata for a given model, if available."""
    candidates = [
        model_path.with_suffix(".json"),
        model_path.parent / "metadata.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                with open(candidate, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                # When metadata stores multiple entries, try to match by filename
                if isinstance(data, dict) and "models" in data:
                    return data["models"].get(model_path.stem, data)
                return data
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "model_metadata_load_failed",
                    model_path=str(model_path),
                    metadata_path=str(candidate),
                    error=str(exc),
                )
    return {}


def _build_feature_vector(model_info: Dict) -> Tuple[List[float], List[str]]:
    features_required = model_info.get("features_required")
    if isinstance(features_required, list) and features_required:
        feature_names = [str(name) for name in features_required]
    else:
        feature_names = [f"feature_{idx}" for idx in range(10)]

    feature_values = [
        float(model_info.get("feature_seed", 0.5)) + (idx * 0.01) for idx, _ in enumerate(feature_names)
    ]
    return feature_values, feature_names


async def _test_model(model_node) -> MCPModelPrediction:
    model_info = model_node.get_model_info()
    metadata = _load_metadata(Path(model_info.get("model_path", ""))) if model_info.get("model_path") else {}
    feature_values, feature_names = _build_feature_vector(metadata or model_info)

    request = MCPModelRequest(
        request_id=str(uuid.uuid4()),
        features=feature_values,
        context={"feature_names": feature_names},
        require_explanation=False,
    )
    return await model_node.predict(request)


async def run(model_dir: Path, model_path: Path | None) -> int:
    registry = MCPModelRegistry()
    await registry.initialize()
    discovery = ModelDiscovery(registry)
    discovery.model_dir = model_dir
    discovery.model_path = model_path

    logger.info("model_inference_test_start", model_dir=str(model_dir), model_path=str(model_path or ""))
    discovered = await discovery.discover_models()
    if not discovered:
        logger.error("model_inference_no_models_found", model_dir=str(model_dir))
        return 1

    logger.info("model_inference_models_loaded", models=discovered)

    predictions: List[MCPModelPrediction] = []
    failures: Dict[str, str] = {}

    for model_name, model_node in registry.models.items():
        try:
            prediction = await _test_model(model_node)
            predictions.append(prediction)
            logger.info(
                "model_inference_success",
                model_name=model_name,
                prediction=prediction.prediction,
                confidence=prediction.confidence,
                health_status=prediction.health_status,
            )
        except Exception as exc:
            failures[model_name] = str(exc)
            logger.error(
                "model_inference_failed",
                model_name=model_name,
                error=str(exc),
                exc_info=True,
            )

    if failures:
        logger.error("model_inference_failures", failures=failures)

    if predictions:
        confidence_values = [pred.confidence for pred in predictions]
        logger.info(
            "model_inference_summary",
            tested=len(predictions),
            avg_confidence=statistics.mean(confidence_values),
            min_confidence=min(confidence_values),
            max_confidence=max(confidence_values),
        )

    await registry.shutdown()
    return 0 if not failures else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test ML model inference pipeline.")
    parser.add_argument(
        "--model-dir",
        default="./agent/model_storage",
        type=str,
        help="Directory containing uploaded models (defaults to agent/model_storage).",
    )
    parser.add_argument(
        "--model-path",
        default=None,
        type=str,
        help="Specific production model to test (overrides model discovery).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(run(Path(args.model_dir), Path(args.model_path) if args.model_path else None))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

