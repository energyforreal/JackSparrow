"""
Security Audit Checks

This module contains all security audit checks for the JackSparrow project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_secrets_scan() -> AuditResult:
    """Scan for hardcoded secrets and sensitive information."""
    try:
        # Patterns to search for
        secret_patterns = [
            # API keys and tokens
            r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)(secret[_-]?key|secretkey)\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)(access[_-]?token|accesstoken)\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)(bearer[_-]?token|bearertoken)\s*[=:]\s*["\']([^"\']+)["\']',

            # Passwords
            r'(?i)password\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)passwd\s*[=:]\s*["\']([^"\']+)["\']',

            # Database credentials
            r'(?i)(db[_-]?password|dbpassword)\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)(database[_-]?password|databasepassword)\s*[=:]\s*["\']([^"\']+)["\']',

            # JWT secrets
            r'(?i)(jwt[_-]?secret|jwtsecret)\s*[=:]\s*["\']([^"\']+)["\']',

            # Private keys (basic pattern)
            r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----',

            # AWS credentials
            r'(?i)(aws[_-]?access[_-]?key[_-]?id|awsaccesskeyid)\s*[=:]\s*["\']([^"\']+)["\']',
            r'(?i)(aws[_-]?secret[_-]?access[_-]?key|awssecretaccesskey)\s*[=:]\s*["\']([^"\']+)["\']',

            # Generic tokens
            r'(?i)token\s*[=:]\s*["\']([a-zA-Z0-9_-]{20,})["\']',
            r'(?i)key\s*[=:]\s*["\']([a-zA-Z0-9_-]{20,})["\']',
        ]

        # Files to exclude from scanning
        exclude_patterns = [
            '.git/',
            'node_modules/',
            '__pycache__/',
            '*.pyc',
            '*.log',
            'logs/',
            '.env',
            '.env.*',
            '*.key',
            '*.pem',
            '*.crt',
            '*.p12',
            '*.pfx',
            'redis-tmp/',
            '*.rdb',
        ]

        findings = []

        # Walk through project files
        for root, dirs, files in os.walk(project_root):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not any(pattern in os.path.join(root, d) for pattern in exclude_patterns)]

            for file in files:
                file_path = Path(root) / file

                # Skip excluded files
                if any(pattern in str(file_path) for pattern in exclude_patterns):
                    continue

                # Skip binary files and large files
                try:
                    if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
                        continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                        for pattern in secret_patterns:
                            matches = re.findall(pattern, content)
                            if matches:
                                for match in matches:
                                    # Handle both single captures and tuple captures
                                    if isinstance(match, tuple):
                                        secret_value = match[1] if len(match) > 1 else match[0]
                                    else:
                                        secret_value = match

                                    # Skip obviously fake/test values
                                    if any(fake in secret_value.lower() for fake in [
                                        'test', 'example', 'sample', 'fake', 'dummy', 'placeholder',
                                        'your_', 'xxx', '123456', 'abcdef'
                                    ]):
                                        continue

                                    findings.append({
                                        'file': str(file_path.relative_to(project_root)),
                                        'pattern': pattern,
                                        'value': secret_value[:20] + '...' if len(secret_value) > 20 else secret_value
                                    })

                except (UnicodeDecodeError, OSError):
                    # Skip binary files or files that can't be read
                    continue

        if not findings:
            return AuditResult(
                check_name="secrets_scan",
                category="security",
                severity="high",
                status="pass",
                message="No hardcoded secrets found in codebase",
                details="Scanned all source files for API keys, passwords, tokens, and other sensitive information"
            )
        else:
            # Group findings by file
            file_findings = {}
            for finding in findings:
                file_path = finding['file']
                if file_path not in file_findings:
                    file_findings[file_path] = []
                file_findings[file_path].append(finding)

            details = f"Found potential secrets in {len(file_findings)} files:\n\n"
            for file_path, file_secrets in file_findings.items():
                details += f"**{file_path}** ({len(file_secrets)} issues):\n"
                for secret in file_secrets[:3]:  # Limit to 3 per file for readability
                    details += f"  - {secret['value']} (pattern: {secret['pattern'][:30]}...)\n"
                if len(file_secrets) > 3:
                    details += f"  - ... and {len(file_secrets) - 3} more\n"
                details += "\n"

            return AuditResult(
                check_name="secrets_scan",
                category="security",
                severity="high",
                status="fail",
                message=f"Found {len(findings)} potential hardcoded secrets",
                details=details.strip(),
                recommendations=[
                    "Move all secrets to environment variables",
                    "Use .env files for local development (ensure .env is in .gitignore)",
                    "Use secret management services in production",
                    "Review and remove any real secrets from version control",
                    "Consider using tools like git-secrets for prevention"
                ]
            )

    except Exception as e:
        return AuditResult(
            check_name="secrets_scan",
            category="security",
            severity="high",
            status="error",
            message=f"Secrets scan failed: {str(e)}",
            details=f"Unexpected error during secrets scan: {str(e)}"
        )


def check_dependency_vulnerabilities() -> AuditResult:
    """Check for dependency vulnerabilities using safety and npm audit."""
    vulnerabilities = []

    # Check Python dependencies with safety
    try:
        result = subprocess.run(
            [sys.executable, "-m", "safety", "check", "--file", "backend/requirements.txt"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60
        )

        if result.returncode != 0:
            # Parse safety output
            lines = result.stdout.split('\n')
            vuln_lines = [line for line in lines if any(keyword in line.upper() for keyword in ['VULNERABILITY', 'UNSAFE', 'WARNING'])]

            if vuln_lines:
                vulnerabilities.extend([f"Python: {line.strip()}" for line in vuln_lines[:10]])

    except (subprocess.TimeoutExpired, FileNotFoundError):
        vulnerabilities.append("Python: Could not check (safety not available or timeout)")

    # Check Python agent dependencies
    try:
        result = subprocess.run(
            [sys.executable, "-m", "safety", "check", "--file", "agent/requirements.txt"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60
        )

        if result.returncode != 0:
            lines = result.stdout.split('\n')
            vuln_lines = [line for line in lines if any(keyword in line.upper() for keyword in ['VULNERABILITY', 'UNSAFE', 'WARNING'])]

            if vuln_lines:
                vulnerabilities.extend([f"Python (agent): {line.strip()}" for line in vuln_lines[:10]])

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # Already noted python issues above

    # Check Node.js dependencies
    frontend_dir = project_root / "frontend"
    if frontend_dir.exists():
        try:
            result = subprocess.run(
                ["npm", "audit", "--audit-level", "moderate"],
                capture_output=True,
                text=True,
                cwd=frontend_dir,
                timeout=60
            )

            if result.returncode != 0:
                lines = result.stdout.split('\n')
                vuln_lines = [line for line in lines if 'vulnerability' in line.lower() or 'severity' in line.lower()]

                if vuln_lines:
                    vulnerabilities.extend([f"Node.js: {line.strip()}" for line in vuln_lines[:10]])

        except (subprocess.TimeoutExpired, FileNotFoundError):
            vulnerabilities.append("Node.js: Could not check (npm not available or timeout)")

    # Check for outdated packages that might have security issues
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30
        )

        if result.returncode == 0:
            import json
            try:
                outdated = json.loads(result.stdout)
                security_relevant = ['cryptography', 'requests', 'urllib3', 'jwt', 'oauth', 'auth']

                outdated_security = [
                    pkg for pkg in outdated
                    if any(relevant in pkg.get('name', '').lower() for relevant in security_relevant)
                ]

                if outdated_security:
                    vulnerabilities.extend([
                        f"Python: Outdated security package - {pkg['name']} ({pkg.get('version', 'unknown')} -> {pkg.get('latest_version', 'unknown')})"
                        for pkg in outdated_security[:5]
                    ])
            except json.JSONDecodeError:
                pass

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass

    if not vulnerabilities:
        return AuditResult(
            check_name="dependency_vulnerabilities",
            category="security",
            severity="high",
            status="pass",
            message="No dependency vulnerabilities found",
            details="Checked Python (backend/agent) and Node.js dependencies for known security vulnerabilities"
        )
    else:
        severity = "high" if len(vulnerabilities) > 2 else "medium"

        return AuditResult(
            check_name="dependency_vulnerabilities",
            category="security",
            severity=severity,
            status="fail",
            message=f"Found {len(vulnerabilities)} dependency vulnerabilities",
            details="Vulnerabilities found:\n" + '\n'.join(f"- {vuln}" for vuln in vulnerabilities),
            recommendations=[
                "Update vulnerable dependencies to latest secure versions",
                "Run 'pip install --upgrade <package>' for Python packages",
                "Run 'npm update' for Node.js packages",
                "Review changelogs for breaking changes before updating",
                "Consider using tools like Dependabot for automated updates",
                "Run 'safety check --file requirements.txt' regularly"
            ]
        )


def check_security_practices() -> AuditResult:
    """Check security best practices implementation."""
    issues = []

    # Check for environment variable usage in config files
    config_files = [
        "backend/core/config.py",
        "agent/core/config.py",
        "scripts/validate-env.py"
    ]

    hardcoded_secrets_found = []

    for config_file in config_files:
        file_path = project_root / config_file
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                    # Look for hardcoded secrets
                    secret_indicators = [
                        'password.*=.*["\']', 'secret.*=.*["\']', 'key.*=.*["\']',
                        'token.*=.*["\']', 'credential.*=.*["\']'
                    ]

                    for indicator in secret_indicators:
                        if re.search(indicator, content, re.IGNORECASE):
                            lines = content.split('\n')
                            for i, line in enumerate(lines):
                                if re.search(indicator, line, re.IGNORECASE):
                                    # Check if it's actually an env var reference
                                    if not ('os.environ' in line or 'os.getenv' in line or 'getenv' in line):
                                        hardcoded_secrets_found.append(f"{config_file}:{i+1}: {line.strip()}")

            except (UnicodeDecodeError, OSError):
                continue

    if hardcoded_secrets_found:
        issues.append(f"Found {len(hardcoded_secrets_found)} potential hardcoded secrets in config files")

    # Check for proper error handling that doesn't expose sensitive info
    error_files = [
        "backend/api/main.py",
        "backend/api/routes/health.py",
        "agent/core/intelligent_agent.py"
    ]

    for error_file in error_files:
        file_path = project_root / error_file
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                    # Check for generic exception handlers that might expose internals
                    if re.search(r'except.*Exception.*:', content):
                        # Look for proper error handling patterns
                        if not re.search(r'logger\.(error|warning)', content):
                            issues.append(f"Generic exception handling without logging in {error_file}")

            except (UnicodeDecodeError, OSError):
                continue

    # Check for HTTPS-only settings
    docker_compose = project_root / "docker-compose.yml"
    if docker_compose.exists():
        try:
            with open(docker_compose, 'r', encoding='utf-8') as f:
                content = f.read()
                if "http://" in content and "https://" not in content:
                    issues.append("Docker compose uses HTTP URLs - consider HTTPS for production")
        except (UnicodeDecodeError, OSError):
            pass

    # Check for CORS configuration
    backend_main = project_root / "backend" / "api" / "main.py"
    if backend_main.exists():
        try:
            with open(backend_main, 'r', encoding='utf-8') as f:
                content = f.read()
                if "CORS" in content or "cors" in content:
                    # Basic check - has some CORS config
                    pass
                else:
                    issues.append("No CORS configuration found in backend")
        except (UnicodeDecodeError, OSError):
            pass

    if not issues:
        return AuditResult(
            check_name="security_practices",
            category="security",
            severity="medium",
            status="pass",
            message="Security best practices are properly implemented",
            details="Checked for hardcoded secrets, error handling, HTTPS usage, and CORS configuration"
        )
    else:
        severity = "high" if len([i for i in issues if "hardcoded" in i.lower()]) > 0 else "medium"

        return AuditResult(
            check_name="security_practices",
            category="security",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} security practice issues",
            details="Issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Move all secrets to environment variables",
                "Implement proper error handling without exposing sensitive information",
                "Use HTTPS in production environments",
                "Configure CORS properly for frontend-backend communication",
                "Review and fix all identified security issues"
            ]
        )


def check_api_security() -> AuditResult:
    """Check API security implementation."""
    issues = []

    # Check FastAPI security features
    main_api_file = project_root / "backend" / "api" / "main.py"
    if main_api_file.exists():
        try:
            with open(main_api_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for basic security features
                security_features = {
                    "JWT authentication": "jwt" in content.lower() or "bearer" in content.lower(),
                    "CORS middleware": "cors" in content.lower() or "CORSMiddleware" in content,
                    "Rate limiting": "rate" in content.lower() or "limit" in content.lower(),
                    "Input validation": "pydantic" in content.lower() or "BaseModel" in content,
                }

                missing_features = [feature for feature, present in security_features.items() if not present]

                if missing_features:
                    issues.extend([f"Missing {feature}" for feature in missing_features])

        except (UnicodeDecodeError, OSError):
            issues.append("Could not read main API file")

    # Check for proper authentication on protected routes
    routes_dir = project_root / "backend" / "api" / "routes"
    if routes_dir.exists():
        for route_file in routes_dir.glob("*.py"):
            try:
                with open(route_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                    # Look for routes that might need authentication
                    route_patterns = [
                        r'@router\.(post|put|delete|get)\s*\(',
                        r'@app\.(post|put|delete|get)\s*\('
                    ]

                    for pattern in route_patterns:
                        matches = re.findall(pattern, content)
                        if matches:
                            # Check if these routes have authentication
                            if not re.search(r'Depends\(|get_current_user|auth', content):
                                issues.append(f"No authentication found in {route_file.name}")

            except (UnicodeDecodeError, OSError):
                continue

    # Check for SQL injection prevention
    models_dir = project_root / "backend" / "models"
    if models_dir.exists():
        for model_file in models_dir.glob("*.py"):
            try:
                with open(model_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                    # Look for raw SQL usage
                    if re.search(r'\.execute\s*\(\s*["\'].*?%.*["\']', content):
                        issues.append(f"Potential SQL injection in {model_file.name} (string formatting in SQL)")

            except (UnicodeDecodeError, OSError):
                continue

    # Check for secure headers
    if main_api_file.exists():
        try:
            with open(main_api_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Look for security headers
                security_headers = [
                    "X-Content-Type-Options",
                    "X-Frame-Options",
                    "X-XSS-Protection",
                    "Strict-Transport-Security"
                ]

                found_headers = sum(1 for header in security_headers if header in content)

                if found_headers < len(security_headers) * 0.5:  # Less than 50% of security headers
                    issues.append(f"Missing security headers ({found_headers}/{len(security_headers)} found)")

        except (UnicodeDecodeError, OSError):
            pass

    if not issues:
        return AuditResult(
            check_name="api_security",
            category="security",
            severity="high",
            status="pass",
            message="API security implementation is adequate",
            details="Checked for authentication, input validation, SQL injection prevention, and security headers"
        )
    else:
        return AuditResult(
            check_name="api_security",
            category="security",
            severity="high",
            status="fail",
            message=f"Found {len(issues)} API security issues",
            details="Security issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Implement JWT authentication on all protected routes",
                "Add CORS middleware for cross-origin requests",
                "Implement rate limiting to prevent abuse",
                "Use parameterized queries to prevent SQL injection",
                "Add security headers (CSP, HSTS, X-Frame-Options, etc.)",
                "Use Pydantic models for all API input validation"
            ]
        )