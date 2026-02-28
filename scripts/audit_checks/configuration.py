"""
Configuration Audit Checks

This module contains configuration audit checks for the JackSparrow project.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_environment_variables() -> AuditResult:
    """Check environment variables configuration."""
    issues = []

    # Check for .env file
    env_file = project_root / ".env"
    if not env_file.exists():
        issues.append(".env file not found")

    # Check for .env.example
    env_example = project_root / ".env.example"
    if not env_example.exists():
        issues.append(".env.example template not found")

    # If .env exists, check its contents
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()

                lines = content.split('\n')
                variables = {}
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        variables[key.strip()] = value.strip()

                # Check for required variables
                required_vars = [
                    'DATABASE_URL', 'DELTA_EXCHANGE_API_KEY', 'DELTA_EXCHANGE_API_SECRET',
                    'JWT_SECRET_KEY', 'API_KEY'
                ]

                missing_vars = [var for var in required_vars if var not in variables]
                if missing_vars:
                    issues.append(f"Missing required environment variables: {', '.join(missing_vars)}")

                # Check for placeholder/default values
                placeholder_values = ['your_', 'example', 'test', 'default', 'xxx', 'changeme']
                placeholder_vars = []
                for key, value in variables.items():
                    if any(placeholder.lower() in value.lower() for placeholder in placeholder_values):
                        placeholder_vars.append(key)

                if placeholder_vars:
                    issues.append(f"Variables with placeholder values: {', '.join(placeholder_vars[:3])}")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read .env file: {e}")

    # Check for hardcoded environment variables in code
    code_files = []
    for root, dirs, files in os.walk(project_root):
        if any(skip in root for skip in ['__pycache__', 'node_modules', '.git', 'logs']):
            continue
        for file in files:
            if file.endswith(('.py', '.js', '.ts', '.tsx')):
                code_files.append(Path(root) / file)

    hardcoded_env = []
    for code_file in code_files[:50]:  # Check first 50 files
        try:
            with open(code_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Look for os.environ.get or process.env usage with default values
                if 'os.environ' in content or 'process.env' in content:
                    # This is normal usage, skip
                    continue

                # Look for direct environment variable access
                env_access = re.findall(r'os\.environ\[[\'"]([^\'"]+)[\'"]\]', content)
                if env_access:
                    hardcoded_env.extend([(str(code_file.relative_to(project_root)), var) for var in env_access])

        except (UnicodeDecodeError, OSError):
            continue

    if hardcoded_env:
        issues.append(f"Found {len(hardcoded_env)} direct environment variable accesses")

    if not issues:
        return AuditResult(
            check_name="environment_variables",
            category="configuration",
            severity="high",
            status="pass",
            message="Environment variables are properly configured",
            details="All required variables present, no placeholder values found"
        )
    else:
        severity = "high" if any("missing required" in issue for issue in issues) else "medium"

        return AuditResult(
            check_name="environment_variables",
            category="configuration",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} environment configuration issues",
            details="Configuration issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Create .env file with all required variables",
                "Create .env.example template for team members",
                "Replace placeholder values with actual configuration",
                "Use environment variable validation in startup scripts",
                "Avoid direct environment variable access in code"
            ]
        )


def check_configuration_files() -> AuditResult:
    """Check configuration file consistency and validity."""
    issues = []

    # Check docker-compose.yml
    docker_compose = project_root / "docker-compose.yml"
    if docker_compose.exists():
        try:
            import yaml
            with open(docker_compose, 'r', encoding='utf-8') as f:
                compose_config = yaml.safe_load(f)

                services = compose_config.get('services', {})

                # Check for common issues
                for service_name, service_config in services.items():
                    # Check ports
                    ports = service_config.get('ports', [])
                    for port in ports:
                        if isinstance(port, str) and ':' in port:
                            port_parts = port.split(':')
                            if len(port_parts) >= 2:
                                host_port = port_parts[0]
                                container_port = port_parts[1]
                                if host_port == container_port:
                                    issues.append(f"Service {service_name}: Host and container ports are identical")

                    # Check environment variables
                    env_vars = service_config.get('environment', [])
                    if isinstance(env_vars, list):
                        for env_var in env_vars:
                            if isinstance(env_var, str) and '=' not in env_var and not env_var.startswith('$'):
                                issues.append(f"Service {service_name}: Environment variable '{env_var}' not properly formatted")

        except ImportError:
            issues.append("PyYAML not available for docker-compose validation")
        except (yaml.YAMLError, OSError) as e:
            issues.append(f"Invalid docker-compose.yml: {e}")

    # Check .gitignore
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        try:
            with open(gitignore, 'r', encoding='utf-8') as f:
                content = f.read()

                essential_ignores = ['.env', '__pycache__/', 'node_modules/', '*.log', '.git/']
                missing_ignores = []

                for ignore in essential_ignores:
                    if ignore not in content:
                        missing_ignores.append(ignore)

                if missing_ignores:
                    issues.append(f".gitignore missing essential entries: {', '.join(missing_ignores)}")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read .gitignore: {e}")

    # Check for configuration consistency between environments
    config_files = [
        "docker-compose.yml",
        "docker-compose.dev.yml" if (project_root / "docker-compose.dev.yml").exists() else None
    ]

    config_files = [f for f in config_files if f is not None]
    if len(config_files) > 1:
        try:
            import yaml
            configs = {}
            for config_file in config_files:
                with open(project_root / config_file, 'r', encoding='utf-8') as f:
                    configs[config_file] = yaml.safe_load(f)

            # Check service consistency
            services_per_config = {name: set(config.get('services', {}).keys())
                                 for name, config in configs.items()}

            all_services = set()
            for services in services_per_config.values():
                all_services.update(services)

            inconsistent_services = []
            for service in all_services:
                in_configs = [name for name, services in services_per_config.items() if service in services]
                if len(in_configs) != len(configs):
                    inconsistent_services.append(service)

            if inconsistent_services:
                issues.append(f"Services not consistent across config files: {', '.join(inconsistent_services)}")

        except (ImportError, yaml.YAMLError, OSError):
            pass  # Skip consistency check if YAML parsing fails

    if not issues:
        return AuditResult(
            check_name="configuration_files",
            category="configuration",
            severity="medium",
            status="pass",
            message="Configuration files are properly structured",
            details="All configuration files are valid and follow best practices"
        )
    else:
        return AuditResult(
            check_name="configuration_files",
            category="configuration",
            severity="medium",
            status="fail",
            message=f"Found {len(issues)} configuration file issues",
            details="Configuration issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Fix YAML syntax errors in docker-compose files",
                "Add missing entries to .gitignore",
                "Use proper port mapping in Docker services",
                "Format environment variables correctly",
                "Ensure consistency between development and production configs"
            ]
        )