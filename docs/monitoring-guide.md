# Monitoring Guide

This guide explains how to set up and use monitoring for the JackSparrow Trading Agent system.

## Overview

The monitoring system provides:
- Continuous health monitoring
- Service status tracking
- Alert generation
- Performance metrics

## Monitoring Scripts

### System Monitor

Continuous monitoring of all services:
```bash
python tools/commands/monitor-system.py
```

Options:
- `--interval`: Monitoring interval in seconds (default: 30)
- `--backend-url`: Backend API URL (default: http://localhost:8000)
- `--frontend-url`: Frontend URL (default: http://localhost:3000)

Example:
```bash
python tools/commands/monitor-system.py --interval 60
```

### Health Check

One-time health check:
```bash
python tools/commands/health-check.py
```

Options:
- `--backend-url`: Backend API URL
- `--frontend-url`: Frontend URL
- `--no-wait`: Don't wait for services to start
- `--max-wait`: Maximum wait time in seconds

### Enhanced Health Validation

Detailed health report:
```bash
python tools/commands/validate-health.py
```

Options:
- `--backend-url`: Backend API URL
- `--frontend-url`: Frontend URL
- `--no-wait`: Don't wait for services
- `--max-wait`: Maximum wait time

## Monitoring Features

### Service Health Checks

The monitoring system checks:
- **Backend**: API availability and health endpoint
- **Frontend**: Web interface accessibility
- **Agent**: Agent status and model availability
- **Database**: Connection status
- **Redis**: Connection status

### Metrics Collected

- Service availability
- Response times
- Error rates
- Model counts
- Health scores

### Alerts

Alerts are generated for:
- Service downtime
- Health check failures
- High error rates
- Model loading failures

## Setting Up Continuous Monitoring

### Basic Setup

1. Start monitoring:
   ```bash
   python tools/commands/monitor-system.py
   ```

2. Monitor runs continuously until stopped (Ctrl+C)

3. Check logs for alerts and status updates

### Advanced Setup

#### Background Monitoring

On Linux/Mac:
```bash
nohup python tools/commands/monitor-system.py > monitor.log 2>&1 &
```

On Windows (PowerShell):
```powershell
Start-Process python -ArgumentList "tools/commands/monitor-system.py" -WindowStyle Hidden
```

#### Scheduled Health Checks

Use cron (Linux/Mac) or Task Scheduler (Windows) to run periodic health checks:

Linux/Mac (crontab):
```bash
# Run health check every 5 minutes
*/5 * * * * cd /path/to/project && python tools/commands/health-check.py
```

Windows (Task Scheduler):
- Create task to run `python tools/commands/health-check.py` on schedule

## Monitoring Best Practices

### Regular Checks

- Run health checks before deployments
- Monitor continuously in production
- Set up alerts for critical issues

### Alert Thresholds

Configure appropriate thresholds:
- Service downtime: Immediate alert
- High error rates: Alert after 5 minutes
- Degraded performance: Alert after 15 minutes

### Log Management

- Rotate logs regularly
- Archive old logs
- Monitor log file sizes

## Troubleshooting

### Monitoring Script Not Running

- Check Python path
- Verify dependencies installed
- Check file permissions

### False Alerts

- Verify service URLs are correct
- Check network connectivity
- Review alert thresholds

### High Resource Usage

- Increase monitoring interval
- Reduce check frequency
- Optimize health check endpoints

## Integration with External Monitoring

### Prometheus Integration

Export metrics for Prometheus:
```python
# Add Prometheus exporter
from prometheus_client import start_http_server, Counter

health_check_counter = Counter('health_checks_total', 'Total health checks')
```

### Grafana Dashboards

Create dashboards using:
- Service availability metrics
- Response time metrics
- Error rate metrics

### Alerting Systems

Integrate with:
- PagerDuty
- Slack
- Email
- SMS

## Additional Resources

- [Health Check Script](../tools/commands/health-check.py)
- [System Monitor Script](../tools/commands/monitor-system.py)
- [Project Documentation](README.md)

