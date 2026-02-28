"""
Data validation utilities for ensuring data consistency between backend and frontend.

Provides utilities to validate data structures, compare expected vs actual data,
and log data mismatches for debugging integration issues.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from decimal import Decimal
from datetime import datetime, date
import structlog

from backend.core.communication_logger import log_communication

logger = structlog.get_logger()


class DataValidationError(Exception):
    """Raised when data validation fails."""
    pass


class DataMismatch:
    """Represents a data mismatch between expected and actual data."""

    def __init__(
        self,
        field_path: str,
        expected_value: Any,
        actual_value: Any,
        mismatch_type: str,
        description: str = ""
    ):
        self.field_path = field_path
        self.expected_value = expected_value
        self.actual_value = actual_value
        self.mismatch_type = mismatch_type  # "type", "value", "missing", "extra", "structure"
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "field_path": self.field_path,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "mismatch_type": self.mismatch_type,
            "description": self.description
        }


class DataValidator:
    """Utility for validating data structures and content."""

    def __init__(self, strict_mode: bool = False):
        """Initialize validator.

        Args:
            strict_mode: If True, raise exceptions on validation failures.
                         If False, log warnings instead.
        """
        self.strict_mode = strict_mode
        self.mismatches: List[DataMismatch] = []

    def validate_structure(
        self,
        data: Any,
        expected_schema: Dict[str, Any],
        path: str = ""
    ) -> List[DataMismatch]:
        """Validate data structure against expected schema.

        Args:
            data: The data to validate
            expected_schema: Expected structure/schema
            path: Current path in the data structure (for error reporting)

        Returns:
            List of mismatches found
        """
        mismatches = []

        if expected_schema.get("type") == "object":
            mismatches.extend(self._validate_object_structure(data, expected_schema, path))
        elif expected_schema.get("type") == "array":
            mismatches.extend(self._validate_array_structure(data, expected_schema, path))
        else:
            mismatches.extend(self._validate_primitive(data, expected_schema, path))

        # Check required fields
        if expected_schema.get("required", False) and data is None:
            mismatches.append(DataMismatch(
                path,
                "non-null value",
                None,
                "missing",
                "Required field is null or missing"
            ))

        self.mismatches.extend(mismatches)
        return mismatches

    def _validate_object_structure(
        self,
        data: Any,
        schema: Dict[str, Any],
        path: str
    ) -> List[DataMismatch]:
        """Validate object structure."""
        mismatches = []

        if not isinstance(data, dict):
            return [DataMismatch(
                path,
                "object",
                type(data).__name__,
                "type",
                "Expected object but got different type"
            )]

        expected_properties = schema.get("properties", {})

        # Check for missing required properties
        required_props = schema.get("required", [])
        for prop in required_props:
            if prop not in data:
                mismatches.append(DataMismatch(
                    f"{path}.{prop}" if path else prop,
                    "present",
                    "missing",
                    "missing",
                    f"Required property '{prop}' is missing"
                ))

        # Check existing properties
        for prop, prop_schema in expected_properties.items():
            prop_path = f"{path}.{prop}" if path else prop
            if prop in data:
                mismatches.extend(self.validate_structure(data[prop], prop_schema, prop_path))
            elif prop_schema.get("required", False):
                mismatches.append(DataMismatch(
                    prop_path,
                    "present",
                    "missing",
                    "missing",
                    f"Required property '{prop}' is missing"
                ))

        # Check for extra properties if schema is strict
        if schema.get("additionalProperties", True) is False:
            allowed_props = set(expected_properties.keys())
            actual_props = set(data.keys())
            extra_props = actual_props - allowed_props
            for extra_prop in extra_props:
                prop_path = f"{path}.{extra_prop}" if path else extra_prop
                mismatches.append(DataMismatch(
                    prop_path,
                    "not present",
                    data[extra_prop],
                    "extra",
                    f"Extra property '{extra_prop}' not allowed by schema"
                ))

        return mismatches

    def _validate_array_structure(
        self,
        data: Any,
        schema: Dict[str, Any],
        path: str
    ) -> List[DataMismatch]:
        """Validate array structure."""
        mismatches = []

        if not isinstance(data, list):
            return [DataMismatch(
                path,
                "array",
                type(data).__name__,
                "type",
                "Expected array but got different type"
            )]

        item_schema = schema.get("items", {})

        # Validate array length constraints
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")

        if min_items is not None and len(data) < min_items:
            mismatches.append(DataMismatch(
                path,
                f"at least {min_items} items",
                len(data),
                "value",
                f"Array has {len(data)} items but minimum is {min_items}"
            ))

        if max_items is not None and len(data) > max_items:
            mismatches.append(DataMismatch(
                path,
                f"at most {max_items} items",
                len(data),
                "value",
                f"Array has {len(data)} items but maximum is {max_items}"
            ))

        # Validate each item
        for i, item in enumerate(data):
            item_path = f"{path}[{i}]"
            mismatches.extend(self.validate_structure(item, item_schema, item_path))

        return mismatches

    def _validate_primitive(
        self,
        data: Any,
        schema: Dict[str, Any],
        path: str
    ) -> List[DataMismatch]:
        """Validate primitive values."""
        mismatches = []

        expected_type = schema.get("type")
        if expected_type:
            actual_type = self._get_json_type(data)

            # Allow numeric types to be flexible (int/float/Decimal)
            if expected_type in ["number", "integer", "float"]:
                if actual_type not in ["number", "integer", "float"]:
                    mismatches.append(DataMismatch(
                        path,
                        expected_type,
                        actual_type,
                        "type",
                        f"Expected {expected_type} but got {actual_type}"
                    ))
            elif expected_type != actual_type:
                mismatches.append(DataMismatch(
                    path,
                    expected_type,
                    actual_type,
                    "type",
                    f"Expected {expected_type} but got {actual_type}"
                ))

        # Validate enum values
        enum_values = schema.get("enum")
        if enum_values and data not in enum_values:
            mismatches.append(DataMismatch(
                path,
                enum_values,
                data,
                "value",
                f"Value {data} not in allowed enum values {enum_values}"
            ))

        return mismatches

    def _get_json_type(self, value: Any) -> str:
        """Get JSON-compatible type name."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, (int, float, Decimal)):
            return "number"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, list):
            return "array"
        elif isinstance(value, dict):
            return "object"
        else:
            return type(value).__name__

    def compare_data(
        self,
        expected: Any,
        actual: Any,
        path: str = "",
        tolerance: float = 0.0
    ) -> List[DataMismatch]:
        """Compare expected vs actual data for equality.

        Args:
            expected: Expected data
            actual: Actual data
            path: Current path in data structure
            tolerance: Numeric tolerance for floating point comparisons

        Returns:
            List of mismatches found
        """
        mismatches = []

        # Handle None/null values
        if expected is None and actual is None:
            return mismatches
        elif expected is None or actual is None:
            return [DataMismatch(
                path,
                expected,
                actual,
                "value",
                "One value is null, other is not"
            )]

        # Handle different types
        if type(expected) != type(actual):
            # Special case: allow int/float interchange for numeric values
            if isinstance(expected, (int, float, Decimal)) and isinstance(actual, (int, float, Decimal)):
                pass  # Continue with numeric comparison
            else:
                return [DataMismatch(
                    path,
                    type(expected).__name__,
                    type(actual).__name__,
                    "type",
                    "Types do not match"
                )]

        # Compare based on type
        if isinstance(expected, dict):
            mismatches.extend(self._compare_dicts(expected, actual, path, tolerance))
        elif isinstance(expected, list):
            mismatches.extend(self._compare_lists(expected, actual, path, tolerance))
        elif isinstance(expected, (int, float, Decimal)):
            if not self._numeric_equal(expected, actual, tolerance):
                mismatches.append(DataMismatch(
                    path,
                    expected,
                    actual,
                    "value",
                    f"Numeric values differ (tolerance: {tolerance})"
                ))
        elif expected != actual:
            mismatches.append(DataMismatch(
                path,
                expected,
                actual,
                "value",
                "Values are not equal"
            ))

        self.mismatches.extend(mismatches)
        return mismatches

    def _compare_dicts(
        self,
        expected: Dict[str, Any],
        actual: Dict[str, Any],
        path: str,
        tolerance: float
    ) -> List[DataMismatch]:
        """Compare two dictionaries."""
        mismatches = []

        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())

        # Check for missing keys
        missing_keys = expected_keys - actual_keys
        for key in missing_keys:
            mismatches.append(DataMismatch(
                f"{path}.{key}" if path else key,
                expected[key],
                "missing",
                "missing",
                f"Expected key '{key}' is missing"
            ))

        # Check for extra keys
        extra_keys = actual_keys - expected_keys
        for key in extra_keys:
            mismatches.append(DataMismatch(
                f"{path}.{key}" if path else key,
                "not expected",
                actual[key],
                "extra",
                f"Unexpected key '{key}' found"
            ))

        # Compare common keys
        for key in expected_keys & actual_keys:
            key_path = f"{path}.{key}" if path else key
            mismatches.extend(self.compare_data(expected[key], actual[key], key_path, tolerance))

        return mismatches

    def _compare_lists(
        self,
        expected: List[Any],
        actual: List[Any],
        path: str,
        tolerance: float
    ) -> List[DataMismatch]:
        """Compare two lists."""
        mismatches = []

        if len(expected) != len(actual):
            mismatches.append(DataMismatch(
                path,
                len(expected),
                len(actual),
                "structure",
                "List lengths do not match"
            ))
            return mismatches

        for i, (exp_item, act_item) in enumerate(zip(expected, actual)):
            item_path = f"{path}[{i}]"
            mismatches.extend(self.compare_data(exp_item, act_item, item_path, tolerance))

        return mismatches

    def _numeric_equal(self, a: Union[int, float, Decimal], b: Union[int, float, Decimal], tolerance: float) -> bool:
        """Check if two numeric values are equal within tolerance."""
        return abs(float(a) - float(b)) <= tolerance

    def log_mismatches(
        self,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log all accumulated mismatches."""
        if not self.mismatches:
            return

        # Log summary
        log_communication(
            direction="internal",
            protocol="validation",
            message_type="data_validation",
            correlation_id=correlation_id,
            payload={
                "mismatch_count": len(self.mismatches),
                "mismatches": [m.to_dict() for m in self.mismatches]
            },
            target="system",
            error="Data validation failed" if self.strict_mode else None,
            **(context or {})
        )

        # Raise exception in strict mode
        if self.strict_mode:
            raise DataValidationError(f"Data validation failed with {len(self.mismatches)} mismatches")

    def clear_mismatches(self) -> None:
        """Clear accumulated mismatches."""
        self.mismatches.clear()


# Global validator instances
default_validator = DataValidator(strict_mode=False)
strict_validator = DataValidator(strict_mode=True)


def validate_websocket_message(
    message: Dict[str, Any],
    expected_schema: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> List[DataMismatch]:
    """Validate a WebSocket message structure.

    Args:
        message: WebSocket message to validate
        expected_schema: Expected schema for the message
        correlation_id: Correlation ID for logging

    Returns:
        List of validation mismatches
    """
    validator = DataValidator()

    # Basic WebSocket envelope validation
    envelope_schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "required": True},
            "resource": {"type": "string"},
            "data": {"type": "object"},
            "timestamp": {"type": "string"},
            "correlation_id": {"type": "string"},
            "request_id": {"type": "string"}
        }
    }

    mismatches = validator.validate_structure(message, envelope_schema)

    # Validate message-specific schema if provided
    if expected_schema and "data" in message:
        data_mismatches = validator.validate_structure(message["data"], expected_schema, "data")
        mismatches.extend(data_mismatches)

    validator.log_mismatches(correlation_id, {"validation_type": "websocket_message"})
    return validator.mismatches


def compare_backend_frontend_data(
    backend_data: Any,
    frontend_received_data: Any,
    data_type: str,
    correlation_id: Optional[str] = None,
    tolerance: float = 0.001
) -> List[DataMismatch]:
    """Compare data sent by backend with what frontend received.

    Args:
        backend_data: Data sent by backend
        frontend_received_data: Data received by frontend
        data_type: Type of data being compared (e.g., "portfolio", "signal")
        correlation_id: Correlation ID for tracking
        tolerance: Numeric tolerance for comparisons

    Returns:
        List of data mismatches
    """
    validator = DataValidator()

    mismatches = validator.compare_data(
        backend_data,
        frontend_received_data,
        tolerance=tolerance
    )

    if mismatches:
        validator.log_mismatches(correlation_id, {
            "validation_type": "backend_frontend_comparison",
            "data_type": data_type,
            "backend_data_summary": {
                "type": type(backend_data).__name__,
                "size": len(json.dumps(backend_data, default=str)) if backend_data else 0
            },
            "frontend_data_summary": {
                "type": type(frontend_received_data).__name__,
                "size": len(json.dumps(frontend_received_data, default=str)) if frontend_received_data else 0
            }
        })

    return mismatches