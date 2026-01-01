"""Report generator for comprehensive test results."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from tests.functionality.config import config
from tests.functionality.utils import TestStatus, TestSuiteResult, generate_solution


class ReportGenerator:
    """Generates comprehensive test reports."""
    
    def __init__(self):
        self.results: Dict[str, List[TestSuiteResult]] = {}
        self.startup_info: Optional[Dict[str, Any]] = None
        self.timestamp = datetime.now(timezone.utc)
        self.report_dir = config.report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)
    
    def add_results(self, group_name: str, results: List[TestSuiteResult]):
        """Add test results for a group."""
        self.results[group_name] = results
    
    def add_startup_info(self, services_status: Dict[str, bool], 
                        startup_errors: List[Dict[str, Any]] = None,
                        startup_warnings: List[Dict[str, Any]] = None):
        """Add startup validation information to report.
        
        Args:
            services_status: Dictionary mapping service name to health status
            startup_errors: List of startup error dictionaries
            startup_warnings: List of startup warning dictionaries
        """
        self.startup_info = {
            "services_status": services_status,
            "all_services_ready": all(services_status.values()) if services_status else False,
            "startup_errors": startup_errors or [],
            "startup_warnings": startup_warnings or [],
            "errors_count": len(startup_errors) if startup_errors else 0,
            "warnings_count": len(startup_warnings) if startup_warnings else 0
        }
    
    def generate_all_reports(self) -> Dict[str, Path]:
        """Generate all report formats."""
        reports = {}
        
        if "markdown" in config.report_formats:
            reports["markdown"] = self.generate_markdown_report()
        
        if "json" in config.report_formats:
            reports["json"] = self.generate_json_report()
        
        if "html" in config.report_formats:
            reports["html"] = self.generate_html_report()
        
        return reports
    
    def generate_markdown_report(self) -> Path:
        """Generate markdown report."""
        timestamp_str = self.timestamp.strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"comprehensive_test_report_{timestamp_str}.md"
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(self._generate_markdown_content())
        
        return report_path
    
    def generate_json_report(self) -> Path:
        """Generate JSON report."""
        timestamp_str = self.timestamp.strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"comprehensive_test_report_{timestamp_str}.json"
        
        report_data = self._generate_report_data()
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=str)
        
        return report_path
    
    def generate_html_report(self) -> Path:
        """Generate HTML report."""
        timestamp_str = self.timestamp.strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"comprehensive_test_report_{timestamp_str}.html"
        
        html_content = self._generate_html_content()
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        return report_path
    
    def _generate_report_data(self) -> Dict[str, Any]:
        """Generate report data structure."""
        summary = self._calculate_summary()
        all_issues = self._collect_all_issues()
        all_solutions = self._collect_all_solutions()
        
        report_data = {
            "timestamp": self.timestamp.isoformat(),
            "summary": summary,
            "startup": self.startup_info,
            "test_groups": {
                group_name: [
                    {
                        "suite_name": result.suite_name,
                        "status": result.status.value,
                        "duration_ms": result.duration_ms,
                        "total_tests": len(result.results),
                        "passed": sum(1 for r in result.results if r.status == TestStatus.PASS),
                        "failed": sum(1 for r in result.results if r.status == TestStatus.FAIL),
                        "warnings": sum(1 for r in result.results if r.status == TestStatus.WARNING),
                        "issues": result.issues,
                        "solutions": result.solutions,
                        "results": [
                            {
                                "name": r.name,
                                "status": r.status.value,
                                "duration_ms": r.duration_ms,
                                "details": r.details,
                                "issues": r.issues,
                                "solutions": r.solutions,
                                "error": r.error
                            }
                            for r in result.results
                        ]
                    }
                    for result in group_results
                ]
                for group_name, group_results in self.results.items()
            },
            "all_issues": all_issues,
            "all_solutions": all_solutions,
            "recommendations": self._generate_recommendations()
        }
        
        # Add startup errors and warnings to all_issues if present
        if self.startup_info:
            if self.startup_info.get("startup_errors"):
                for error in self.startup_info["startup_errors"]:
                    all_issues.append({
                        "group": "startup",
                        "suite": "system_startup",
                        "test": error.get("service", "unknown"),
                        "issue": error.get("message", "Startup error"),
                        "solution": error.get("solution", "Review startup logs and fix configuration")
                    })
            
            if self.startup_info.get("startup_warnings"):
                for warning in self.startup_info["startup_warnings"]:
                    all_issues.append({
                        "group": "startup",
                        "suite": "system_startup",
                        "test": warning.get("service", "unknown"),
                        "issue": warning.get("message", "Startup warning"),
                        "solution": warning.get("solution", "Review startup logs")
                    })
        
        report_data["all_issues"] = all_issues
        return report_data
    
    def _calculate_summary(self) -> Dict[str, Any]:
        """Calculate overall summary."""
        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_warnings = 0
        total_degraded = 0
        total_duration = 0.0
        
        for results in self.results.values():
            for result in results:
                total_tests += len(result.results)
                total_duration += result.duration_ms
                for test_result in result.results:
                    if test_result.status == TestStatus.PASS:
                        total_passed += 1
                    elif test_result.status == TestStatus.FAIL:
                        total_failed += 1
                    elif test_result.status == TestStatus.WARNING:
                        total_warnings += 1
                    elif test_result.status == TestStatus.DEGRADED:
                        total_degraded += 1
        
        health_score = (total_passed / total_tests * 100) if total_tests > 0 else 0.0
        
        return {
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "warnings": total_warnings,
            "degraded": total_degraded,
            "health_score": round(health_score, 2),
            "total_duration_ms": round(total_duration, 2),
            "groups_tested": len(self.results)
        }
    
    def _collect_all_issues(self) -> List[Dict[str, Any]]:
        """Collect all issues from all test results."""
        issues = []
        for group_name, results in self.results.items():
            for result in results:
                for test_result in result.results:
                    for issue in test_result.issues:
                        issues.append({
                            "group": group_name,
                            "suite": result.suite_name,
                            "test": test_result.name,
                            "issue": issue,
                            "solution": generate_solution(issue, test_result.details)
                        })
        return issues
    
    def _collect_all_solutions(self) -> List[str]:
        """Collect all solutions."""
        solutions = set()
        for results in self.results.values():
            for result in results:
                solutions.update(result.solutions)
                for test_result in result.results:
                    solutions.update(test_result.solutions)
        return list(solutions)
    
    def _generate_recommendations(self) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []
        summary = self._calculate_summary()
        
        # Startup recommendations
        if self.startup_info:
            if not self.startup_info.get("all_services_ready", True):
                recommendations.append("Some services failed to start or are not ready. Check service logs and configuration")
            
            if self.startup_info.get("errors_count", 0) > 0:
                recommendations.append(f"Address {self.startup_info['errors_count']} startup errors before running tests")
            
            if self.startup_info.get("warnings_count", 0) > 0:
                recommendations.append(f"Review {self.startup_info['warnings_count']} startup warnings")
        
        # Test recommendations
        if summary["failed"] > 0:
            recommendations.append(f"Address {summary['failed']} failing tests to improve system reliability")
        
        if summary["warnings"] > 0:
            recommendations.append(f"Review {summary['warnings']} warnings to identify potential issues")
        
        if summary["health_score"] < 80:
            recommendations.append("System health score is below 80%. Review failing tests and warnings")
        
        if summary["total_duration_ms"] > 300000:  # 5 minutes
            recommendations.append("Test execution time is high. Consider optimizing slow tests")
        
        return recommendations
    
    def _generate_markdown_content(self) -> str:
        """Generate markdown report content."""
        summary = self._calculate_summary()
        all_issues = self._collect_all_issues()
        recommendations = self._generate_recommendations()
        
        content = f"""# Comprehensive Functionality Test Report

**Generated**: {self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}

## Executive Summary

- **Total Tests**: {summary['total_tests']}
- **Passed**: {summary['passed']} ({(summary['passed']/summary['total_tests']*100) if summary['total_tests'] > 0 else 0:.1f}%)
- **Failed**: {summary['failed']}
- **Warnings**: {summary['warnings']}
- **Degraded**: {summary['degraded']}
- **Health Score**: {summary['health_score']}%
- **Total Duration**: {summary['total_duration_ms']/1000:.2f}s
- **Groups Tested**: {summary['groups_tested']}

"""
        
        # Add startup information section
        if self.startup_info:
            content += "## System Startup Status\n\n"
            services_status = self.startup_info.get("services_status", {})
            all_ready = self.startup_info.get("all_services_ready", False)
            
            status_icon = "✅" if all_ready else "❌"
            content += f"**Overall Status**: {status_icon} {'All services ready' if all_ready else 'Some services not ready'}\n\n"
            
            content += "### Service Health\n\n"
            for service_name, is_ready in services_status.items():
                icon = "✅" if is_ready else "❌"
                content += f"- {icon} **{service_name}**: {'Ready' if is_ready else 'Not Ready'}\n"
            content += "\n"
            
            errors_count = self.startup_info.get("errors_count", 0)
            warnings_count = self.startup_info.get("warnings_count", 0)
            if errors_count > 0 or warnings_count > 0:
                content += f"- **Startup Errors**: {errors_count}\n"
                content += f"- **Startup Warnings**: {warnings_count}\n\n"
        
        content += "## Test Results by Category\n\n"
        
        for group_name, results in self.results.items():
            content += f"### {group_name.replace('_', ' ').title()}\n\n"
            for result in results:
                status_emoji = "✅" if result.status == TestStatus.PASS else "❌" if result.status == TestStatus.FAIL else "⚠️"
                content += f"#### {status_emoji} {result.suite_name}\n\n"
                content += f"- **Status**: {result.status.value}\n"
                content += f"- **Duration**: {result.duration_ms:.2f}ms\n"
                content += f"- **Tests**: {len(result.results)} (Passed: {sum(1 for r in result.results if r.status == TestStatus.PASS)}, Failed: {sum(1 for r in result.results if r.status == TestStatus.FAIL)})\n\n"
                
                if result.issues:
                    content += "**Issues**:\n"
                    for issue in result.issues:
                        content += f"- {issue}\n"
                    content += "\n"
        
        if all_issues:
            content += "## Issues Found\n\n"
            for issue in all_issues:
                content += f"### {issue['test']} ({issue['suite']})\n\n"
                content += f"**Issue**: {issue['issue']}\n\n"
                content += f"**Solution**: {issue['solution']}\n\n"
        
        if recommendations:
            content += "## Recommendations\n\n"
            for rec in recommendations:
                content += f"- {rec}\n"
            content += "\n"
        
        return content
    
    def _generate_html_content(self) -> str:
        """Generate HTML report content."""
        summary = self._calculate_summary()
        all_issues = self._collect_all_issues()
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Comprehensive Test Report - {self.timestamp.strftime("%Y-%m-%d %H:%M:%S")}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .summary {{ background: #f5f5f5; padding: 20px; border-radius: 5px; }}
        .pass {{ color: green; }}
        .fail {{ color: red; }}
        .warning {{ color: orange; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <h1>Comprehensive Functionality Test Report</h1>
    <p><strong>Generated</strong>: {self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    
    <div class="summary">
        <h2>Executive Summary</h2>
        <p><strong>Total Tests</strong>: {summary['total_tests']}</p>
        <p><strong>Passed</strong>: <span class="pass">{summary['passed']}</span></p>
        <p><strong>Failed</strong>: <span class="fail">{summary['failed']}</span></p>
        <p><strong>Health Score</strong>: {summary['health_score']}%</p>
    </div>
    
    <h2>Test Results</h2>
    <table>
        <tr>
            <th>Group</th>
            <th>Suite</th>
            <th>Status</th>
            <th>Tests</th>
            <th>Duration (ms)</th>
        </tr>
"""
        
        for group_name, results in self.results.items():
            for result in results:
                status_class = "pass" if result.status == TestStatus.PASS else "fail" if result.status == TestStatus.FAIL else "warning"
                html += f"""
        <tr>
            <td>{group_name}</td>
            <td>{result.suite_name}</td>
            <td class="{status_class}">{result.status.value}</td>
            <td>{len(result.results)}</td>
            <td>{result.duration_ms:.2f}</td>
        </tr>
"""
        
        html += """
    </table>
</body>
</html>
"""
        
        return html

