# Test Environment Configuration
# This file contains test-specific environment variables

import os

# Test environment variables
TEST_ENV_VARS = {
    # Database Configuration
    'DATABASE_URL': 'postgresql://test_user:test_password@localhost:5432/test_db',

    # Redis Configuration
    'REDIS_URL': 'redis://localhost:6379/1',

    # API Configuration
    'API_KEY': 'test_api_key_12345',
    'JWT_SECRET_KEY': 'test_jwt_secret_key_for_testing',

    # Delta Exchange API (Test Credentials)
    'DELTA_EXCHANGE_API_KEY': 'test_delta_api_key',
    'DELTA_EXCHANGE_API_SECRET': 'test_delta_api_secret',

    # Agent Configuration
    'MODEL_DIR': './agent/model_storage',
    'MODEL_DISCOVERY_ENABLED': 'true',
    'MODEL_AUTO_REGISTER': 'true',

    # Feature Server Configuration
    'FEATURE_SERVER_PORT': '8002',

    # Backend Configuration
    'BACKEND_PORT': '8000',
    'AGENT_PORT': '8001',

    # WebSocket URLs
    'NEXT_PUBLIC_WS_URL': 'ws://localhost:8000/ws',
    'NEXT_PUBLIC_API_URL': 'http://localhost:8000',

    # Paper Trading Mode
    'TRADING_MODE': 'PAPER',

    # Logging
    'LOG_LEVEL': 'INFO',
    'STRUCTLOG_LOG_LEVEL': 'INFO',

    # Test-specific settings
    'TESTING': 'true',
    'SKIP_REAL_API_CALLS': 'true'
}

def set_test_env_vars():
    """Set test environment variables."""
    for key, value in TEST_ENV_VARS.items():
        os.environ[key] = value

def get_test_env_vars():
    """Get test environment variables dict."""
    return TEST_ENV_VARS.copy()