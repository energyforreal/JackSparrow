"""Unit tests for learning subsystem utility components."""

from agent.learning.confidence_calibrator import ConfidenceCalibrator
from agent.learning.performance_tracker import PerformanceTracker
from agent.learning.strategy_adapter import StrategyAdapter


def test_performance_tracker_accuracy_uses_evaluated_predictions_only() -> None:
    tracker = PerformanceTracker()
    tracker.record_prediction("m1", prediction=0.2)
    tracker.record_prediction("m1", prediction=0.3, actual_outcome=0.1)
    tracker.record_prediction("m1", prediction=-0.4, actual_outcome=-0.2)

    perf = tracker.get_model_performance("m1")
    assert perf["total_predictions"] == 3
    assert perf["evaluated_predictions"] == 2
    assert perf["correct_predictions"] == 2
    assert perf["accuracy"] == 1.0


def test_performance_tracker_treats_neutral_prediction_as_neutral() -> None:
    tracker = PerformanceTracker()
    tracker.record_prediction("m1", prediction=0.0, actual_outcome=0.0)
    tracker.record_prediction("m1", prediction=0.0, actual_outcome=1.0)

    perf = tracker.get_model_performance("m1")
    assert perf["evaluated_predictions"] == 2
    assert perf["correct_predictions"] == 1
    assert perf["accuracy"] == 0.5


def test_confidence_calibrator_does_not_zero_new_model_confidence() -> None:
    tracker = PerformanceTracker()
    calibrator = ConfidenceCalibrator(tracker)

    calibrated = calibrator.calibrate_confidence(
        raw_confidence=0.8,
        model_name="new_model",
        signal_strength=0.6,
    )
    assert 0.5 <= calibrated <= 0.9


def test_strategy_adapter_returns_base_params_for_insufficient_data() -> None:
    tracker = PerformanceTracker()
    adapter = StrategyAdapter(tracker)
    tracker.record_prediction("m1", prediction=0.5, actual_outcome=0.4, profit=10.0)

    params = adapter.adapt_parameters()
    assert params == adapter.base_params


def test_strategy_adapter_scales_risk_with_strong_performance() -> None:
    tracker = PerformanceTracker()
    adapter = StrategyAdapter(tracker)
    for _ in range(14):
        tracker.record_prediction("m1", prediction=0.6, actual_outcome=0.2, profit=25.0)
    tracker.record_prediction("m1", prediction=-0.6, actual_outcome=0.3, profit=25.0)

    params = adapter.adapt_parameters()
    assert params["position_size_multiplier"] > 1.0
    assert params["confidence_threshold"] < adapter.base_params["confidence_threshold"]
