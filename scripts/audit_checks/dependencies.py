"""
Dependency Audit Checks

This module contains all dependency audit checks for the JackSparrow project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_python_dependencies() -> AuditResult:
    """Check Python dependency management."""
    issues = []

    # Check backend requirements.txt
    backend_req = project_root / "backend" / "requirements.txt"
    if not backend_req.exists():
        issues.append("backend/requirements.txt not found")
    else:
        try:
            with open(backend_req, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for version pinning
                lines = content.split('\n')
                unpinned_deps = []
                total_deps = 0

                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        total_deps += 1
                        # Check if version is pinned (not just ==, >=, etc.)
                        if not re.search(r'[=<>~!]', line):
                            # Allow some common unpinned packages that are typically safe
                            pkg_name = line.split()[0] if ' ' in line else line.split('==')[0] if '==' in line else line
                            if pkg_name.lower() not in ['pip', 'setuptools', 'wheel']:
                                unpinned_deps.append(pkg_name)

                if unpinned_deps:
                    issues.append(f"Unpinned dependencies in backend: {', '.join(unpinned_deps[:5])}")
                    if len(unpinned_deps) > 5:
                        issues[-1] += f" (+{len(unpinned_deps) - 5} more)"

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read backend requirements.txt: {e}")

    # Check agent requirements.txt
    agent_req = project_root / "agent" / "requirements.txt"
    if not agent_req.exists():
        issues.append("agent/requirements.txt not found")
    else:
        try:
            with open(agent_req, 'r', encoding='utf-8') as f:
                content = f.read()

                lines = content.split('\n')
                agent_deps = []
                total_agent_deps = 0

                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        total_agent_deps += 1
                        pkg_name = line.split()[0] if ' ' in line else line.split('==')[0] if '==' in line else line
                        agent_deps.append(pkg_name)

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read agent requirements.txt: {e}")

    # Check for duplicate dependencies between backend and agent
    if 'agent_deps' in locals() and 'backend_req' in locals():
        try:
            with open(backend_req, 'r', encoding='utf-8') as f:
                backend_content = f.read()
                backend_lines = [line.strip() for line in backend_content.split('\n') if line.strip() and not line.startswith('#')]
                backend_deps = []
                for line in backend_lines:
                    pkg_name = line.split()[0] if ' ' in line else line.split('==')[0] if '==' in line else line
                    backend_deps.append(pkg_name)

                duplicates = set(backend_deps) & set(agent_deps)
                if duplicates:
                    issues.append(f"Duplicate dependencies between backend and agent: {', '.join(sorted(duplicates))}")
        except (UnicodeDecodeError, OSError):
            pass

    # Check for outdated packages
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30
        )

        if result.returncode == 0:
            try:
                outdated = json.loads(result.stdout)
                if outdated:
                    major_updates = [
                        pkg for pkg in outdated
                        if pkg.get('latest_version', '').split('.')[0] != pkg.get('version', '').split('.')[0]
                    ]

                    issues.append(f"{len(outdated)} packages are outdated ({len(major_updates)} have major version updates)")

                    # Show top 5 most outdated
                    sorted_outdated = sorted(outdated, key=lambda x: x.get('latest_version', ''), reverse=True)
                    outdated_list = [
                        f"{pkg['name']} ({pkg.get('version', '?')} -> {pkg.get('latest_version', '?')})"
                        for pkg in sorted_outdated[:5]
                    ]
                    issues.append(f"Most critical updates: {', '.join(outdated_list)}")

            except json.JSONDecodeError:
                issues.append("Could not parse pip outdated output")
        else:
            issues.append("Could not check for outdated packages")

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        issues.append("Timeout checking for outdated packages")

    # Check for development vs production dependencies
    dev_indicators = ['pytest', 'black', 'ruff', 'mypy', 'radon', 'interrogate', 'safety']
    for req_file in [backend_req, agent_req]:
        if req_file.exists():
            try:
                with open(req_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                    dev_deps_found = []
                    for indicator in dev_indicators:
                        if indicator in content.lower():
                            dev_deps_found.append(indicator)

                    if dev_deps_found:
                        issues.append(f"Development dependencies in {req_file.name}: {', '.join(dev_deps_found)}")

            except (UnicodeDecodeError, OSError):
                pass

    if not issues:
        return AuditResult(
            check_name="python_dependencies",
            category="dependencies",
            severity="medium",
            status="pass",
            message="Python dependencies are properly managed",
            details="Checked requirements.txt files, version pinning, duplicates, and outdated packages"
        )
    else:
        severity = "high" if any("unpinned" in issue.lower() or "duplicate" in issue.lower() for issue in issues) else "medium"

        return AuditResult(
            check_name="python_dependencies",
            category="dependencies",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} Python dependency issues",
            details="Issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Pin all dependency versions to ensure reproducible builds",
                "Remove duplicate dependencies between backend and agent",
                "Update outdated packages carefully, checking for breaking changes",
                "Move development dependencies to requirements-dev.txt",
                "Consider using pip-tools or poetry for better dependency management"
            ]
        )


def check_nodejs_dependencies() -> AuditResult:
    """Check Node.js dependency management."""
    frontend_dir = project_root / "frontend"
    issues = []

    if not frontend_dir.exists():
        return AuditResult(
            check_name="nodejs_dependencies",
            category="dependencies",
            severity="low",
            status="skip",
            message="Frontend directory not found - skipping Node.js dependency checks"
        )

    # Check package.json
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        issues.append("frontend/package.json not found")
        return AuditResult(
            check_name="nodejs_dependencies",
            category="dependencies",
            severity="medium",
            status="fail",
            message="Node.js dependencies cannot be checked - package.json missing",
            details="frontend/package.json file is required for Node.js projects",
            recommendations=["Initialize the frontend project with 'npm init' or restore package.json"]
        )

    try:
        with open(package_json, 'r', encoding='utf-8') as f:
            package_data = json.load(f)

        # Check for dependency sections
        dep_sections = ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies']
        found_sections = [section for section in dep_sections if section in package_data]

        if not found_sections:
            issues.append("No dependency sections found in package.json")
        else:
            total_deps = sum(len(package_data.get(section, {})) for section in found_sections)
            dev_deps = len(package_data.get('devDependencies', {}))

            # Check for unpinned dependencies
            unpinned_deps = []
            for section in found_sections:
                deps = package_data.get(section, {})
                for pkg_name, version in deps.items():
                    # Allow some patterns that are typically acceptable
                    if version in ['*', 'latest', 'git+', 'file:', 'link:'] or version.startswith(('^', '~', '>', '<')):
                        unpinned_deps.append(f"{pkg_name}@{version}")

            if unpinned_deps:
                issues.append(f"Unpinned dependencies: {', '.join(unpinned_deps[:5])}")
                if len(unpinned_deps) > 5:
                    issues[-1] += f" (+{len(unpinned_deps) - 5} more)"

    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        issues.append(f"Could not parse package.json: {e}")

    # Check package-lock.json
    package_lock = frontend_dir / "package-lock.json"
    if package_json.exists() and not package_lock.exists():
        issues.append("package-lock.json missing - dependencies may not be reproducible")

    # Check for outdated packages
    try:
        result = subprocess.run(
            ["npm", "outdated", "--json"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            timeout=30
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                outdated = json.loads(result.stdout)
                if outdated:
                    outdated_count = len(outdated)
                    issues.append(f"{outdated_count} packages are outdated")

                    # Find major version updates
                    major_updates = []
                    for pkg_name, info in outdated.items():
                        current = info.get('current', '0').split('.')[0]
                        latest = info.get('latest', '0').split('.')[0]
                        if current != latest:
                            major_updates.append(pkg_name)

                    if major_updates:
                        issues.append(f"Major version updates available: {', '.join(major_updates[:3])}")

            except json.JSONDecodeError:
                issues.append("Could not parse npm outdated output")
        elif result.returncode != 0:
            # npm outdated returns non-zero when there are outdated packages
            try:
                outdated = json.loads(result.stdout)
                if outdated:
                    outdated_count = len(outdated)
                    issues.append(f"{outdated_count} packages are outdated")
            except json.JSONDecodeError:
                issues.append("Could not check for outdated packages")

    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append("Could not check for outdated packages (npm not available)")

    # Check for security issues
    try:
        result = subprocess.run(
            ["npm", "audit", "--audit-level", "info", "--json"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            timeout=30
        )

        if result.returncode != 0:
            try:
                audit_data = json.loads(result.stdout)
                vulnerabilities = audit_data.get('metadata', {}).get('vulnerabilities', {})

                total_vulns = sum(vulnerabilities.values())
                if total_vulns > 0:
                    issues.append(f"{total_vulns} security vulnerabilities found in dependencies")

                    # Detail by severity
                    severity_details = []
                    for severity, count in vulnerabilities.items():
                        if count > 0:
                            severity_details.append(f"{count} {severity}")
                    if severity_details:
                        issues.append(f"By severity: {', '.join(severity_details)}")

            except json.JSONDecodeError:
                issues.append("Security vulnerabilities found (could not parse audit output)")

    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append("Could not check for security vulnerabilities (npm not available)")

    if not issues:
        return AuditResult(
            check_name="nodejs_dependencies",
            category="dependencies",
            severity="medium",
            status="pass",
            message="Node.js dependencies are properly managed",
            details="Checked package.json, package-lock.json, outdated packages, and security vulnerabilities"
        )
    else:
        severity = "high" if any("security" in issue.lower() or "vulnerabilit" in issue.lower() for issue in issues) else "medium"

        return AuditResult(
            check_name="nodejs_dependencies",
            category="dependencies",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} Node.js dependency issues",
            details="Issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Pin dependency versions for reproducible builds",
                "Keep package-lock.json committed to ensure consistent installs",
                "Update outdated packages regularly",
                "Fix security vulnerabilities with 'npm audit fix'",
                "Consider using npm ci in CI/CD for faster, reliable installs"
            ]
        )


def check_docker_dependencies() -> AuditResult:
    """Check Docker dependency management."""
    issues = []

    # Check docker-compose.yml
    docker_compose = project_root / "docker-compose.yml"
    if not docker_compose.exists():
        issues.append("docker-compose.yml not found")
    else:
        try:
            with open(docker_compose, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for latest tag usage
                if ':latest' in content:
                    issues.append("Using 'latest' tag in Docker images - not recommended for production")

                # Check for outdated base images (basic check)
                image_lines = re.findall(r'image:\s*(\S+)', content)
                for image in image_lines:
                    # Flag common outdated patterns
                    if any(pattern in image.lower() for pattern in ['python:3.8', 'python:3.9', 'node:14', 'node:16']):
                        issues.append(f"Potentially outdated base image: {image}")

                # Check for security issues
                if 'root' in content and 'user:' not in content:
                    issues.append("Services may be running as root user")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read docker-compose.yml: {e}")

    # Check docker-compose.dev.yml if it exists
    docker_compose_dev = project_root / "docker-compose.dev.yml"
    if docker_compose_dev.exists():
        try:
            with open(docker_compose_dev, 'r', encoding='utf-8') as f:
                dev_content = f.read()

                # Check for development-specific security issues
                if 'DEBUG=true' in dev_content or 'debug: true' in dev_content.lower():
                    issues.append("Debug mode enabled in development compose file")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read docker-compose.dev.yml: {e}")

    # Check Dockerfile(s)
    dockerfiles = list(project_root.glob("**/Dockerfile*"))
    for dockerfile in dockerfiles:
        try:
            with open(dockerfile, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for security best practices
                if 'apt-get update' in content and 'apt-get install' in content:
                    if 'rm -rf /var/lib/apt/lists/*' not in content:
                        issues.append(f"{dockerfile.name}: apt cache not cleaned")

                if 'pip install' in content and '--no-cache-dir' not in content:
                    issues.append(f"{dockerfile.name}: pip cache not disabled")

                if 'WORKDIR' not in content:
                    issues.append(f"{dockerfile.name}: No WORKDIR specified")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read {dockerfile.name}: {e}")

    # Check for .dockerignore
    dockerignore = project_root / ".dockerignore"
    if not dockerignore.exists():
        issues.append(".dockerignore file missing - Docker context may include unnecessary files")

    if not issues:
        return AuditResult(
            check_name="docker_dependencies",
            category="dependencies",
            severity="low",
            status="pass",
            message="Docker configuration follows best practices",
            details="Checked docker-compose.yml, Dockerfiles, and build optimization"
        )
    else:
        severity = "medium" if any("latest" in issue or "root" in issue for issue in issues) else "low"

        return AuditResult(
            check_name="docker_dependencies",
            category="dependencies",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} Docker configuration issues",
            details="Issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Use specific version tags instead of 'latest' for production",
                "Update base images to latest stable versions",
                "Run containers as non-root user for security",
                "Clean apt/pip caches in Dockerfiles to reduce image size",
                "Create .dockerignore to exclude unnecessary files",
                "Set WORKDIR in Dockerfiles for consistent file paths"
            ]
        )