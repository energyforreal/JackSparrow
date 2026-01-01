#!/usr/bin/env python3
"""
Environment variable validation script for JackSparrow Trading Agent.

Validates that the root .env file contains all required variables with correct formats.
This script should be run before starting services to catch configuration issues early.
"""

import os
import platform
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


class EnvValidator:
    """Validates environment variables from .env file."""
    
    def __init__(self, env_path: Optional[Path] = None):
        """Initialize validator with path to .env file.
        
        Args:
            env_path: Path to .env file. If None, uses project root .env
        """
        if env_path is None:
            # Get project root (parent of scripts directory)
            script_path = Path(__file__).resolve()
            project_root = script_path.parent.parent
            env_path = project_root / ".env"
        
        self.env_path = env_path
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.env_vars: Dict[str, str] = {}
    
    def load_env_file(self) -> bool:
        """Load environment variables from .env file.
        
        Returns:
            True if file exists and was loaded, False otherwise
        """
        if not self.env_path.exists():
            self.errors.append(f".env file not found at: {self.env_path}")
            return False
        
        try:
            with self.env_path.open("r", encoding="utf-8") as f:
                for line_num, raw_line in enumerate(f, 1):
                    line = raw_line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    
                    # Skip lines without equals sign
                    if "=" not in line:
                        continue
                    
                    # Parse key=value
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    
                    if key:
                        self.env_vars[key] = value
                        
        except Exception as e:
            self.errors.append(f"Failed to read .env file: {e}")
            return False
        
        return True
    
    def validate_required_vars(self) -> bool:
        """Validate that all required variables are present.
        
        Returns:
            True if all required vars present, False otherwise
        """
        required_vars = {
            "DATABASE_URL": "PostgreSQL connection URL (e.g., postgresql://user:pass@host:port/dbname)",
            "DELTA_EXCHANGE_API_KEY": "Delta Exchange API key",
            "DELTA_EXCHANGE_API_SECRET": "Delta Exchange API secret",
        }
        
        # Backend-specific required vars
        backend_required = {
            "JWT_SECRET_KEY": "JWT secret key for authentication (minimum 32 characters recommended)",
            "API_KEY": "API key for authentication (minimum 32 characters recommended)",
        }
        
        # Risk management settings (should match between backend and agent)
        risk_settings = {
            "STOP_LOSS_PERCENTAGE": "Stop loss percentage (e.g., 0.02 for 2%)",
            "TAKE_PROFIT_PERCENTAGE": "Take profit percentage (e.g., 0.05 for 5%)",
        }
        
        missing = []
        for var, description in required_vars.items():
            if var not in self.env_vars or not self.env_vars[var].strip():
                missing.append(f"  - {var}: {description}")
        
        # Check backend vars (warn if missing, but don't fail for agent-only validation)
        backend_missing = []
        for var, description in backend_required.items():
            if var not in self.env_vars or not self.env_vars[var].strip():
                backend_missing.append(f"  - {var}: {description}")
        
        if missing:
            self.errors.append("Missing required environment variables:")
            self.errors.extend(missing)
        
        if backend_missing:
            self.warnings.append("Missing backend-specific variables (required for backend service):")
            self.warnings.extend(backend_missing)
        
        # Check risk settings (warn if missing, but don't fail - defaults exist)
        risk_missing = []
        for var, description in risk_settings.items():
            if var not in self.env_vars or not self.env_vars[var].strip():
                risk_missing.append(f"  - {var}: {description} (using default)")
        
        if risk_missing:
            self.warnings.append("Risk management settings not set (using defaults):")
            self.warnings.extend(risk_missing)
        
        return len(missing) == 0
    
    def validate_database_url(self) -> bool:
        """Validate DATABASE_URL format.
        
        Returns:
            True if valid, False otherwise
        """
        if "DATABASE_URL" not in self.env_vars:
            return False  # Already reported as missing
        
        db_url = self.env_vars["DATABASE_URL"].strip()
        if not db_url:
            return False
        
        # Check format: postgresql://user:pass@host:port/dbname
        # Also support postgresql+asyncpg:// format
        if "+" in db_url and "://" in db_url:
            scheme_part, rest = db_url.split("://", 1)
            db_url = f"postgresql://{rest}"
        
        try:
            parsed = urlparse(db_url)
            
            if parsed.scheme not in ("postgresql", "postgres"):
                self.errors.append(
                    f"DATABASE_URL has invalid scheme '{parsed.scheme}'. "
                    f"Expected 'postgresql://' or 'postgres://'"
                )
                return False
            
            if not parsed.hostname:
                self.errors.append("DATABASE_URL missing hostname")
                return False
            
            if not parsed.path or parsed.path == "/":
                self.errors.append("DATABASE_URL missing database name")
                return False
            
            # Warn if no password (might be intentional for local dev)
            if not parsed.password:
                self.warnings.append(
                    "DATABASE_URL has no password. Ensure PostgreSQL is configured "
                    "for passwordless authentication."
                )
            
        except Exception as e:
            self.errors.append(f"DATABASE_URL format invalid: {e}")
            return False
        
        return True
    
    def validate_redis_url(self) -> bool:
        """Validate REDIS_URL format if present.
        
        Returns:
            True if valid or not present, False otherwise
        """
        redis_url = self.env_vars.get("REDIS_URL", "redis://localhost:6379")
        if not redis_url:
            return True  # Will use default
        
        try:
            parsed = urlparse(redis_url)
            
            if parsed.scheme not in ("redis", "rediss"):
                self.errors.append(
                    f"REDIS_URL has invalid scheme '{parsed.scheme}'. "
                    f"Expected 'redis://' or 'rediss://'"
                )
                return False
            
            if not parsed.hostname:
                self.errors.append("REDIS_URL missing hostname")
                return False
            
        except Exception as e:
            self.errors.append(f"REDIS_URL format invalid: {e}")
            return False
        
        return True
    
    def validate_api_keys(self) -> bool:
        """Validate API key formats.
        
        Returns:
            True if valid, False otherwise
        """
        valid = True
        
        # Delta Exchange API keys
        if "DELTA_EXCHANGE_API_KEY" in self.env_vars:
            api_key = self.env_vars["DELTA_EXCHANGE_API_KEY"].strip()
            if len(api_key) < 10:
                self.warnings.append(
                    "DELTA_EXCHANGE_API_KEY seems too short. "
                    "Ensure it's the complete API key from Delta Exchange."
                )
        
        if "DELTA_EXCHANGE_API_SECRET" in self.env_vars:
            api_secret = self.env_vars["DELTA_EXCHANGE_API_SECRET"].strip()
            if len(api_secret) < 10:
                self.warnings.append(
                    "DELTA_EXCHANGE_API_SECRET seems too short. "
                    "Ensure it's the complete API secret from Delta Exchange."
                )
        
        # Security keys
        if "JWT_SECRET_KEY" in self.env_vars:
            jwt_secret = self.env_vars["JWT_SECRET_KEY"].strip()
            if len(jwt_secret) < 32:
                self.warnings.append(
                    "JWT_SECRET_KEY should be at least 32 characters for security. "
                    f"Current length: {len(jwt_secret)}"
                )
            if jwt_secret in ("dev-jwt-secret", "your_secret_key_here"):
                self.errors.append(
                    "JWT_SECRET_KEY is set to default/placeholder value. "
                    "Please set a secure random value."
                )
                valid = False
        
        if "API_KEY" in self.env_vars:
            api_key = self.env_vars["API_KEY"].strip()
            if len(api_key) < 32:
                self.warnings.append(
                    "API_KEY should be at least 32 characters for security. "
                    f"Current length: {len(api_key)}"
                )
            if api_key in ("dev-api-key", "your_api_key_here"):
                self.errors.append(
                    "API_KEY is set to default/placeholder value. "
                    "Please set a secure random value."
                )
                valid = False
        
        return valid
    
    def validate_urls(self) -> bool:
        """Validate URL format variables.
        
        Returns:
            True if valid, False otherwise
        """
        valid = True
        
        url_vars = {
            "DELTA_EXCHANGE_BASE_URL": ["https://api.india.delta.exchange"],
            "FEATURE_SERVER_URL": ["http://localhost:8001"],
            "QDRANT_URL": None,  # Optional
        }
        
        for var_name, default_values in url_vars.items():
            if var_name not in self.env_vars:
                continue
            
            url = self.env_vars[var_name].strip()
            if not url:
                continue
            
            try:
                parsed = urlparse(url)
                if not parsed.scheme:
                    self.errors.append(f"{var_name} missing scheme (http:// or https://)")
                    valid = False
                elif parsed.scheme not in ("http", "https"):
                    self.errors.append(
                        f"{var_name} has invalid scheme '{parsed.scheme}'. "
                        f"Expected 'http://' or 'https://'"
                    )
                    valid = False
            except Exception as e:
                self.errors.append(f"{var_name} format invalid: {e}")
                valid = False
        
        return valid
    
    def validate_risk_settings(self) -> bool:
        """Validate risk management settings format and values.
        
        Returns:
            True if valid or not set (using defaults), False otherwise
        """
        valid = True
        
        # Validate STOP_LOSS_PERCENTAGE if set
        if "STOP_LOSS_PERCENTAGE" in self.env_vars:
            stop_loss_str = self.env_vars["STOP_LOSS_PERCENTAGE"].strip()
            if stop_loss_str:
                try:
                    stop_loss = float(stop_loss_str)
                    if stop_loss <= 0 or stop_loss >= 1:
                        self.errors.append(
                            f"STOP_LOSS_PERCENTAGE must be between 0 and 1 (e.g., 0.02 for 2%). "
                            f"Got: {stop_loss}"
                        )
                        valid = False
                    elif stop_loss > 0.1:  # More than 10% stop loss is unusual
                        self.warnings.append(
                            f"STOP_LOSS_PERCENTAGE is quite high ({stop_loss*100:.1f}%). "
                            f"Typical values are 1-5%."
                        )
                except ValueError:
                    self.errors.append(
                        f"STOP_LOSS_PERCENTAGE must be a number. Got: {stop_loss_str}"
                    )
                    valid = False
        
        # Validate TAKE_PROFIT_PERCENTAGE if set
        if "TAKE_PROFIT_PERCENTAGE" in self.env_vars:
            take_profit_str = self.env_vars["TAKE_PROFIT_PERCENTAGE"].strip()
            if take_profit_str:
                try:
                    take_profit = float(take_profit_str)
                    if take_profit <= 0 or take_profit >= 1:
                        self.errors.append(
                            f"TAKE_PROFIT_PERCENTAGE must be between 0 and 1 (e.g., 0.05 for 5%). "
                            f"Got: {take_profit}"
                        )
                        valid = False
                    elif take_profit < 0.01:  # Less than 1% take profit is very small
                        self.warnings.append(
                            f"TAKE_PROFIT_PERCENTAGE is quite low ({take_profit*100:.1f}%). "
                            f"Typical values are 3-10%."
                        )
                except ValueError:
                    self.errors.append(
                        f"TAKE_PROFIT_PERCENTAGE must be a number. Got: {take_profit_str}"
                    )
                    valid = False
        
        # Validate that take profit is greater than stop loss if both are set
        if "STOP_LOSS_PERCENTAGE" in self.env_vars and "TAKE_PROFIT_PERCENTAGE" in self.env_vars:
            stop_loss_str = self.env_vars["STOP_LOSS_PERCENTAGE"].strip()
            take_profit_str = self.env_vars["TAKE_PROFIT_PERCENTAGE"].strip()
            if stop_loss_str and take_profit_str:
                try:
                    stop_loss = float(stop_loss_str)
                    take_profit = float(take_profit_str)
                    if take_profit <= stop_loss:
                        self.warnings.append(
                            f"TAKE_PROFIT_PERCENTAGE ({take_profit*100:.1f}%) should be greater than "
                            f"STOP_LOSS_PERCENTAGE ({stop_loss*100:.1f}%) for profitable trading."
                        )
                except ValueError:
                    pass  # Already handled above
        
        return valid
    
    def validate_model_files(self) -> bool:
        """Validate ML model files if MODEL_PATH is specified.
        
        Returns:
            True if valid or not specified, False otherwise
        """
        script_path = Path(__file__).resolve()
        project_root = script_path.parent.parent
        
        # Check if model discovery is enabled
        discovery_enabled = self.env_vars.get("MODEL_DISCOVERY_ENABLED", "true").lower() in ("true", "1", "yes")
        
        # Check MODEL_PATH if specified
        if "MODEL_PATH" in self.env_vars:
            model_path_str = self.env_vars["MODEL_PATH"].strip()
            if model_path_str:
                # Handle relative paths
                if not Path(model_path_str).is_absolute():
                    model_path = project_root / model_path_str
                else:
                    model_path = Path(model_path_str)
                
                if not model_path.exists():
                    if discovery_enabled:
                        # If discovery is enabled, MODEL_PATH is optional
                        self.warnings.append(
                            f"MODEL_PATH points to non-existent file: {model_path_str}. "
                            f"Since MODEL_DISCOVERY_ENABLED=true, this is optional - models will be discovered from MODEL_DIR instead."
                        )
                    else:
                        # If discovery is disabled, MODEL_PATH is more critical
                        self.warnings.append(
                            f"MODEL_PATH points to non-existent file: {model_path_str}. "
                            f"Agent may fail to start if model is required. Consider enabling MODEL_DISCOVERY_ENABLED=true or training models first."
                        )
                elif not model_path.suffix.lower() in (".pkl", ".h5", ".pb", ".onnx"):
                    self.warnings.append(
                        f"MODEL_PATH file extension '{model_path.suffix}' may not be a valid model format. "
                        f"Expected: .pkl, .h5, .pb, or .onnx"
                    )
        
        # Check MODEL_DIR for discoverable models
        model_dir_str = self.env_vars.get("MODEL_DIR", "./agent/model_storage")
        if model_dir_str:
            # Handle relative paths
            if not Path(model_dir_str).is_absolute():
                model_dir = project_root / model_dir_str
            else:
                model_dir = Path(model_dir_str)
            
            if model_dir.exists():
                # Look for model files
                model_files = list(model_dir.rglob("*.pkl")) + \
                             list(model_dir.rglob("*.h5")) + \
                             list(model_dir.rglob("*.pb")) + \
                             list(model_dir.rglob("*.onnx"))
                
                if not model_files:
                    if discovery_enabled:
                        self.warnings.append(
                            f"No model files found in MODEL_DIR: {model_dir_str}. "
                            f"Agent will start in monitoring mode. Train models using: python scripts/train_price_prediction_models.py"
                        )
                    else:
                        # Only warn if discovery is enabled (otherwise MODEL_DIR is ignored)
                        pass
            else:
                if discovery_enabled:
                    self.warnings.append(
                        f"MODEL_DIR does not exist: {model_dir_str}. "
                        f"Model discovery will be skipped. Create the directory or train models first."
                    )
        
        return True
    
    def validate_all(self) -> bool:
        """Run all validation checks.
        
        Returns:
            True if all validations pass, False otherwise
        """
        if not self.load_env_file():
            return False
        
        valid = True
        valid &= self.validate_required_vars()
        valid &= self.validate_database_url()
        valid &= self.validate_redis_url()
        valid &= self.validate_api_keys()
        valid &= self.validate_urls()
        valid &= self.validate_risk_settings()
        self.validate_model_files()  # Warnings only, don't fail validation
        
        return valid
    
    def print_results(self) -> None:
        """Print validation results to console."""
        # Use ASCII-safe characters on Windows
        is_windows = platform.system() == "Windows"
        error_symbol = "X" if is_windows else "❌"
        warning_symbol = "!" if is_windows else "⚠️"
        success_symbol = "OK" if is_windows else "✅"
        
        print(f"\n{'='*70}")
        print("Environment Variable Validation")
        print(f"{'='*70}\n")
        
        if self.errors:
            print(f"{error_symbol} ERRORS FOUND:")
            for error in self.errors:
                print(f"  {error}")
            print()
        
        if self.warnings:
            print(f"{warning_symbol}  WARNINGS:")
            for warning in self.warnings:
                print(f"  {warning}")
            print()
        
        if not self.errors and not self.warnings:
            print(f"{success_symbol} All environment variables validated successfully!")
            print()
        elif not self.errors:
            print(f"{success_symbol} No critical errors found, but please review warnings above.")
            print()
        else:
            print(f"{error_symbol} Validation failed. Please fix the errors above before starting services.")
            print()
            print("Next steps:")
            print("  1. Review the errors above")
            print("  2. Edit the .env file at:", self.env_path)
            print("  3. Ensure all required variables are set correctly")
            print("  4. Run this validation again: python scripts/validate-env.py")
            print()


def main():
    """Main entry point."""
    validator = EnvValidator()
    
    if not validator.validate_all():
        validator.print_results()
        sys.exit(1)
    
    validator.print_results()
    sys.exit(0)


if __name__ == "__main__":
    main()

