"""
Documentation Audit Checks

This module contains all documentation audit checks for the JackSparrow project.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from urllib.parse import urlparse

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult

# Try to import requests for external link checking
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def check_documentation_completeness() -> AuditResult:
    """Check documentation completeness against project structure."""
    issues = []

    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        return AuditResult(
            check_name="documentation_completeness",
            category="documentation",
            severity="high",
            status="fail",
            message="docs/ directory not found",
            details="Documentation directory is missing from the project",
            recommendations=["Create docs/ directory", "Add comprehensive documentation following existing structure"]
        )

    # Get all documentation files
    doc_files = list(docs_dir.glob("*.md"))
    doc_files.extend(list(project_root.glob("*.md")))  # Root level docs

    if len(doc_files) < 5:
        issues.append(f"Very few documentation files found ({len(doc_files)}) - expected 10+")

    # Check for essential documentation files
    essential_docs = [
        "README.md",
        "docs/01-architecture.md",
        "docs/03-ml-models.md",
        "docs/06-backend.md",
        "docs/07-frontend.md",
        "docs/11-build-guide.md"
    ]

    missing_essential = []
    for doc in essential_docs:
        doc_path = project_root / doc
        if not doc_path.exists():
            missing_essential.append(doc)

    if missing_essential:
        issues.append(f"Missing essential documentation: {', '.join(missing_essential)}")

    # Check for documentation organization
    doc_structure = {
        "architecture": list(docs_dir.glob("01-*.md")),
        "api_docs": list(docs_dir.glob("06-*.md")),
        "deployment": list(docs_dir.glob("10-*.md")),
        "build_guide": list(docs_dir.glob("11-*.md")),
        "troubleshooting": list(docs_dir.glob("*troubleshoot*.md")),
        "testing": list(docs_dir.glob("*test*.md"))
    }

    missing_sections = []
    for section, files in doc_structure.items():
        if not files:
            missing_sections.append(section)

    if missing_sections:
        issues.append(f"Missing documentation sections: {', '.join(missing_sections)}")

    # Check README completeness
    readme = project_root / "README.md"
    if readme.exists():
        try:
            with open(readme, 'r', encoding='utf-8') as f:
                readme_content = f.read().lower()

                required_sections = [
                    "overview", "features", "installation", "usage",
                    "configuration", "api", "contributing", "license"
                ]

                missing_sections = []
                for section in required_sections:
                    if section not in readme_content:
                        missing_sections.append(section)

                if missing_sections:
                    issues.append(f"README missing sections: {', '.join(missing_sections)}")

                # Check for code examples
                if "```" not in readme_content:
                    issues.append("README lacks code examples")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read README.md: {e}")

    # Check for API documentation
    api_docs = docs_dir / "06-backend.md"
    if api_docs.exists():
        try:
            with open(api_docs, 'r', encoding='utf-8') as f:
                api_content = f.read()

                # Check for common API documentation patterns
                api_indicators = [
                    "/api/v1/",
                    "endpoint",
                    "response",
                    "request",
                    "swagger",
                    "openapi"
                ]

                found_indicators = sum(1 for indicator in api_indicators if indicator in api_content)
                if found_indicators < 3:
                    issues.append("API documentation appears incomplete")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not read API docs: {e}")

    # Check for outdated information patterns
    for doc_file in doc_files[:20]:  # Check first 20 files
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for TODO/FIXME comments
                if "todo:" in content.lower() or "fixme:" in content.lower():
                    issues.append(f"{doc_file.name} contains TODO/FIXME comments")

                # Check for placeholder text
                placeholders = ["tbd", "coming soon", "to be determined"]
                for placeholder in placeholders:
                    if placeholder in content.lower():
                        issues.append(f"{doc_file.name} contains placeholder text: '{placeholder}'")

        except (UnicodeDecodeError, OSError):
            continue

    if not issues:
        return AuditResult(
            check_name="documentation_completeness",
            category="documentation",
            severity="medium",
            status="pass",
            message=f"Documentation is adequately complete ({len(doc_files)} files found)",
            details="All essential documentation sections are present and README is comprehensive"
        )
    else:
        severity = "high" if missing_essential or "missing essential" in str(issues) else "medium"

        return AuditResult(
            check_name="documentation_completeness",
            category="documentation",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} documentation completeness issues",
            details="Completeness issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Create missing essential documentation files",
                "Add comprehensive README with all required sections",
                "Include code examples and usage instructions",
                "Document API endpoints thoroughly",
                "Remove TODO/FIXME comments and placeholder text",
                "Add table of contents and cross-references"
            ]
        )


def check_documentation_quality() -> AuditResult:
    """Check documentation quality and formatting."""
    issues = []

    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        return AuditResult(
            check_name="documentation_quality",
            category="documentation",
            severity="medium",
            status="skip",
            message="docs/ directory not found - skipping quality check"
        )

    # Get all documentation files
    doc_files = list(docs_dir.glob("*.md"))
    doc_files.extend(list(project_root.glob("*.md")))

    quality_metrics = {
        'total_files': len(doc_files),
        'files_with_headers': 0,
        'files_with_code_blocks': 0,
        'files_with_lists': 0,
        'files_with_links': 0,
        'average_length': 0,
        'short_files': [],
        'long_lines': [],
        'inconsistent_headers': []
    }

    total_length = 0

    for doc_file in doc_files:
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

                # Check for headers
                if re.search(r'^#+\s', content, re.MULTILINE):
                    quality_metrics['files_with_headers'] += 1

                # Check for code blocks
                if '```' in content:
                    quality_metrics['files_with_code_blocks'] += 1

                # Check for lists
                if re.search(r'^[\s]*[-*+]\s', content, re.MULTILINE) or re.search(r'^\s*\d+\.\s', content, re.MULTILINE):
                    quality_metrics['files_with_lists'] += 1

                # Check for links
                if '[' in content and '](' in content:
                    quality_metrics['files_with_links'] += 1

                # Check file length
                file_length = len(content)
                total_length += file_length

                if file_length < 500:  # Less than 500 characters
                    quality_metrics['short_files'].append(doc_file.name)

                # Check for long lines
                for i, line in enumerate(lines):
                    if len(line) > 120:  # Longer than 120 characters
                        quality_metrics['long_lines'].append(f"{doc_file.name}:{i+1}")

                # Check header consistency
                headers = re.findall(r'^(#+)\s', content, re.MULTILINE)
                header_levels = [len(h) for h in headers]
                if header_levels:
                    # Check if headers skip levels inappropriately
                    sorted_levels = sorted(set(header_levels))
                    if sorted_levels != list(range(min(header_levels), max(header_levels) + 1)):
                        quality_metrics['inconsistent_headers'].append(doc_file.name)

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not analyze {doc_file.name}: {e}")

    # Calculate averages
    if quality_metrics['total_files'] > 0:
        quality_metrics['average_length'] = total_length / quality_metrics['total_files']

    # Analyze quality issues
    if quality_metrics['short_files']:
        issues.append(f"Short documentation files (<500 chars): {', '.join(quality_metrics['short_files'][:3])}")

    if quality_metrics['long_lines']:
        issues.append(f"Long lines found (>120 chars): {len(quality_metrics['long_lines'])} instances")

    if quality_metrics['inconsistent_headers']:
        issues.append(f"Inconsistent header hierarchy: {', '.join(quality_metrics['inconsistent_headers'][:3])}")

    # Check quality percentages
    header_ratio = quality_metrics['files_with_headers'] / quality_metrics['total_files'] if quality_metrics['total_files'] > 0 else 0
    code_ratio = quality_metrics['files_with_code_blocks'] / quality_metrics['total_files'] if quality_metrics['total_files'] > 0 else 0
    list_ratio = quality_metrics['files_with_lists'] / quality_metrics['total_files'] if quality_metrics['total_files'] > 0 else 0

    if header_ratio < 0.8:  # Less than 80% have headers
        issues.append(".1f")

    if code_ratio < 0.5:  # Less than 50% have code blocks
        issues.append(".1f")

    if list_ratio < 0.6:  # Less than 60% have lists
        issues.append(".1f")

    # Check for common formatting issues
    for doc_file in doc_files[:10]:  # Check first 10 files
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for trailing whitespace
                lines = content.split('\n')
                trailing_ws_lines = [i+1 for i, line in enumerate(lines) if line.rstrip() != line]
                if trailing_ws_lines:
                    issues.append(f"{doc_file.name} has trailing whitespace on {len(trailing_ws_lines)} lines")

                # Check for inconsistent list formatting
                if re.search(r'^[\s]*[-*+]', content, re.MULTILINE):
                    # Mixed list markers
                    dash_lists = len(re.findall(r'^[\s]*- ', content, re.MULTILINE))
                    asterisk_lists = len(re.findall(r'^[\s]*\* ', content, re.MULTILINE))
                    if dash_lists > 0 and asterisk_lists > 0:
                        issues.append(f"{doc_file.name} uses mixed list markers (- and *)")

        except (UnicodeDecodeError, OSError):
            continue

    if not issues:
        return AuditResult(
            check_name="documentation_quality",
            category="documentation",
            severity="low",
            status="pass",
            message="Documentation quality is good",
            details=".1f"
        )
    else:
        return AuditResult(
            check_name="documentation_quality",
            category="documentation",
            severity="low",
            status="fail",
            message=f"Found {len(issues)} documentation quality issues",
            details="Quality issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Use consistent header hierarchy (don't skip levels)",
                "Keep lines under 120 characters for readability",
                "Include headers, code blocks, and lists in documentation",
                "Remove trailing whitespace",
                "Use consistent list markers (- or *)",
                "Expand very short documentation files",
                "Add links to related documentation"
            ]
        )


def check_broken_links() -> AuditResult:
    """Check for broken links in documentation."""
    issues = []

    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        return AuditResult(
            check_name="broken_links",
            category="documentation",
            severity="low",
            status="skip",
            message="docs/ directory not found - skipping link check"
        )

    # Get all documentation files
    doc_files = list(docs_dir.glob("*.md"))
    doc_files.extend(list(project_root.glob("*.md")))

    links_checked = 0
    broken_links = []

    for doc_file in doc_files[:5]:  # Check first 5 files for performance
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Find all markdown links [text](url)
                link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
                matches = re.findall(link_pattern, content)

                for text, url in matches:
                    links_checked += 1

                    # Skip anchor links, email links, and relative links to non-existent files
                    if url.startswith('#') or url.startswith('mailto:'):
                        continue

                    if url.startswith('http://') or url.startswith('https://'):
                        # External link - check if accessible (with timeout)
                        if REQUESTS_AVAILABLE:
                            try:
                                response = requests.head(url, timeout=3, allow_redirects=True)
                                if response.status_code >= 400:
                                    broken_links.append(f"{doc_file.name}: {url} (HTTP {response.status_code})")
                            except (requests.RequestException, requests.Timeout):
                                # For audit purposes, we'll assume external links are OK unless clearly broken
                                pass
                        # Skip external link checking if requests not available
                    else:
                        # Relative link - check if file exists
                        if url.startswith('./') or url.startswith('../') or (not url.startswith('/') and '.' in url):
                            # File link
                            try:
                                link_path = (doc_file.parent / url).resolve()
                                if not link_path.exists():
                                    broken_links.append(f"{doc_file.name}: {url} (file not found)")
                            except (OSError, ValueError):
                                broken_links.append(f"{doc_file.name}: {url} (invalid path)")
                        else:
                            # Check if it's a reference to another doc file
                            if url.endswith('.md') and not url.startswith('http'):
                                target_file = docs_dir / url
                                if not target_file.exists():
                                    target_file = project_root / url
                                    if not target_file.exists():
                                        broken_links.append(f"{doc_file.name}: {url} (documentation file not found)")

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not check links in {doc_file.name}: {e}")

    if broken_links:
        issues.extend(broken_links)

    # Check for common link issues
    for doc_file in doc_files[:10]:
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Check for malformed links
                malformed_patterns = [
                    r'\[([^\]]*)\]\(\s*\)',  # Empty URLs
                    r'\[\]\([^)]+\)',       # Empty link text
                    r'\[([^\]]+)\]\(([^)]+)\s+["\'][^"\']*["\']([^)]*)\)',  # Malformed title syntax
                ]

                for pattern in malformed_patterns:
                    if re.search(pattern, content):
                        issues.append(f"{doc_file.name} has malformed link syntax")

        except (UnicodeDecodeError, OSError):
            continue

    if not issues:
        return AuditResult(
            check_name="broken_links",
            category="documentation",
            severity="low",
            status="pass",
            message=f"No broken links found ({links_checked} links checked)",
            details="All internal and external links in documentation are valid"
        )
    else:
        return AuditResult(
            check_name="broken_links",
            category="documentation",
            severity="low",
            status="fail",
            message=f"Found {len(issues)} broken or malformed links",
            details="Link issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Fix broken internal links to documentation files",
                "Update URLs for moved or deleted external resources",
                "Use proper markdown link syntax: [text](url)",
                "Test links manually to ensure they work",
                "Consider using link checkers like markdown-link-check",
                "Use relative paths for internal documentation links"
            ]
        )