# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 13:01:06 UTC

## Executive Summary

- **Total Tests**: 14
- **Passed**: 10 (71.4%)
- **Failed**: 0
- **Warnings**: 4
- **Degraded**: 0
- **Health Score**: 71.43%
- **Total Duration**: 16.23s
- **Groups Tested**: 1

## Test Results by Category

### Infrastructure

#### ⚠️ database operations

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 2, Failed: 0)

**Issues**:
- Database URL not configured

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 16234.68ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Backend service may not be available
- Database URL not configured
- Vector memory store not available

## Issues Found

### database_connection (database operations)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### service_health_check (agent loading)

**Issue**: Backend service may not be available

**Solution**: Review logs and documentation for troubleshooting steps

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

## Recommendations

- Review 4 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

