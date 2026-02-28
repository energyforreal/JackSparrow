"""Test configuration and execution settings."""

import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class TestConfig:
    """Configuration for functionality tests."""

    # Service URLs
    backend_url: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    agent_websocket_url: str = os.getenv("AGENT_WEBSOCKET_URL", "ws://localhost:8002")
    backend_websocket_url: str = os.getenv("BACKEND_WEBSOCKET_URL", "ws://localhost:8000/ws")
    agent_event_websocket_url: str = os.getenv("AGENT_EVENT_WEBSOCKET_URL", "ws://localhost:8000/ws/agent")
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Database
    database_url: Optional[str] = os.getenv("DATABASE_URL")
    redis_url: Optional[str] = os.getenv("REDIS_URL")

    # Delta Exchange
    delta_exchange_base_url: Optional[str] = os.getenv("DELTA_EXCHANGE_BASE_URL")
    delta_exchange_api_key: Optional[str] = os.getenv("DELTA_EXCHANGE_API_KEY")
    delta_exchange_api_secret: Optional[str] = os.getenv("DELTA_EXCHANGE_API_SECRET")

    # Backend API Authentication
    api_key: Optional[str] = os.getenv("API_KEY")
    
    # Test execution
    max_workers: int = 4
    timeout_seconds: int = 300
    verbose: bool = False
    
    # Startup timing configuration
    startup_wait_timeout: int = 60
    health_check_retry_interval: float = 2.0
    health_check_max_retries: int = 30
    
    # Test groups configuration
    test_groups: Dict[str, List[str]] = field(default_factory=lambda: {
        "infrastructure": [
            "test_database_operations",
            "test_delta_exchange_connection",
            "test_agent_loading"
        ],
        "core-services": [
            "test_feature_computation",
            "test_ml_model_communication",
            "test_websocket_communication"
        ],
        "agent-logic": [
            "test_agent_decision",
            "test_risk_management",
            "test_signal_generation",
            "test_agent_functionality"
        ],
        "integration": [
            "test_agent_communication",
            "test_data_freshness",
            "test_portfolio_management",
            "test_learning_system",
            "test_frontend_functionality"
        ]
    })
    
    # Group dependencies
    group_dependencies: Dict[str, List[str]] = field(default_factory=lambda: {
        "core-services": ["infrastructure"],
        "agent-logic": ["core-services"],
        "integration": ["agent-logic"]
    })
    
    # Report settings
    report_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "tests" / "functionality" / "reports")
    report_formats: List[str] = field(default_factory=lambda: ["markdown", "json"])
    
    def __post_init__(self):
        """Load configuration from environment variables."""
        # Load from environment
        self.backend_url = os.getenv("TEST_BACKEND_URL", self.backend_url)
        self.agent_websocket_url = os.getenv("TEST_AGENT_WS_URL", self.agent_websocket_url)
        self.backend_websocket_url = os.getenv("TEST_BACKEND_WS_URL", self.backend_websocket_url)
        self.frontend_url = os.getenv("FRONTEND_URL", os.getenv("TEST_FRONTEND_URL", self.frontend_url))
        
        # Load database and Redis URLs - try multiple sources
        self.database_url = (
            os.getenv("DATABASE_URL") or 
            os.getenv("TEST_DATABASE_URL") or 
            self.database_url
        )
        self.redis_url = (
            os.getenv("REDIS_URL") or 
            os.getenv("TEST_REDIS_URL") or 
            self.redis_url or
            "redis://localhost:6379"  # Default fallback
        )
        
        self.delta_exchange_base_url = os.getenv("DELTA_EXCHANGE_BASE_URL", self.delta_exchange_base_url)
        self.delta_exchange_api_key = os.getenv("DELTA_EXCHANGE_API_KEY", self.delta_exchange_api_key)
        self.delta_exchange_api_secret = os.getenv("DELTA_EXCHANGE_API_SECRET", self.delta_exchange_api_secret)
        
        # Load API key for backend authentication
        self.api_key = (
            os.getenv("API_KEY") or 
            os.getenv("TEST_API_KEY") or 
            self.api_key
        )
        
        # Startup timing configuration from environment
        self.startup_wait_timeout = int(os.getenv("STARTUP_WAIT_TIMEOUT", str(self.startup_wait_timeout)))
        self.health_check_retry_interval = float(os.getenv("HEALTH_CHECK_RETRY_INTERVAL", str(self.health_check_retry_interval)))
        self.health_check_max_retries = int(os.getenv("HEALTH_CHECK_MAX_RETRIES", str(self.health_check_max_retries)))
        
        # Create report directory
        self.report_dir.mkdir(parents=True, exist_ok=True)
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """Validate configuration and return issues.
        
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        # Database URL validation
        if not self.database_url:
            issues.append("Database URL not configured. Set DATABASE_URL or TEST_DATABASE_URL environment variable.")
        elif not self.database_url.startswith(("postgresql://", "postgres://")):
            issues.append(f"Database URL format may be invalid. Expected postgresql:// or postgres://, got: {self.database_url[:20]}...")
        
        # Redis URL validation
        if not self.redis_url:
            issues.append("Redis URL not configured. Set REDIS_URL or TEST_REDIS_URL environment variable.")
        elif not self.redis_url.startswith("redis://"):
            issues.append(f"Redis URL format may be invalid. Expected redis://, got: {self.redis_url[:20]}...")
        
        return len(issues) == 0, issues
    
    def get_test_group(self, test_name: str) -> Optional[str]:
        """Get the test group for a given test name."""
        for group_name, tests in self.test_groups.items():
            if test_name in tests:
                return group_name
        return None
    
    def get_group_dependencies(self, group_name: str) -> List[str]:
        """Get dependencies for a test group."""
        return self.group_dependencies.get(group_name, [])


# Global config instance
config = TestConfig()

