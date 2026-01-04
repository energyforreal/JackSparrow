#!/usr/bin/env python3
"""
WebSocket Performance Monitor for JackSparrow Trading Agent

Monitors WebSocket connections, message throughput, and real-time performance
metrics for the Delta Exchange WebSocket integration.
"""

import asyncio
import json
import time
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import argparse
import sys
from pathlib import Path

# Add project root to path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root))

from agent.core.config import settings
from agent.data.delta_client import DeltaExchangeWebSocketClient
from tests.functionality.fixtures import get_shared_backend_websocket


class WebSocketPerformanceMonitor:
    """Monitors WebSocket performance and connection health."""

    def __init__(self, duration_seconds: int = 300):
        """Initialize performance monitor.

        Args:
            duration_seconds: How long to monitor (default: 5 minutes)
        """
        self.duration_seconds = duration_seconds
        self.start_time = None
        self.end_time = None

        # Connection metrics
        self.connection_attempts = 0
        self.connection_successes = 0
        self.connection_failures = 0
        self.reconnections = 0

        # Message metrics
        self.messages_received = 0
        self.message_timestamps = []
        self.message_sizes = []
        self.message_types = {}

        # Performance metrics
        self.latency_measurements = []
        self.throughput_measurements = []

        # Error tracking
        self.errors = []
        self.last_error_time = None

        # WebSocket clients
        self.delta_ws_client = None
        self.backend_ws_client = None

    async def initialize_clients(self):
        """Initialize WebSocket clients for monitoring."""
        try:
            # Initialize Delta Exchange WebSocket client
            self.delta_ws_client = DeltaExchangeWebSocketClient(
                api_key=settings.delta_exchange_api_key,
                api_secret=settings.delta_exchange_api_secret,
                base_url=settings.websocket_url
            )

            # Set up message handler for Delta Exchange
            self.delta_ws_client.add_message_handler("ticker", self._handle_delta_message)
            self.delta_ws_client.add_message_handler("v2/ticker", self._handle_delta_message)

            # Initialize backend WebSocket client
            self.backend_ws_client = await get_shared_backend_websocket()

            print("✅ WebSocket clients initialized")

        except Exception as e:
            print(f"❌ Failed to initialize WebSocket clients: {e}")
            raise

    def _handle_delta_message(self, message: Dict[str, Any]):
        """Handle incoming Delta Exchange WebSocket messages."""
        try:
            current_time = time.time()

            # Track message metrics
            self.messages_received += 1
            self.message_timestamps.append(current_time)

            # Track message size
            message_size = len(json.dumps(message))
            self.message_sizes.append(message_size)

            # Track message types
            msg_type = message.get("type", "unknown")
            self.message_types[msg_type] = self.message_types.get(msg_type, 0) + 1

            # Calculate latency (time since message timestamp)
            if "timestamp" in message:
                msg_timestamp = message["timestamp"]
                # Convert microseconds to seconds
                if msg_timestamp > 1e12:
                    msg_timestamp /= 1_000_000
                elif msg_timestamp > 1e10:
                    msg_timestamp /= 1_000

                latency = current_time - msg_timestamp
                self.latency_measurements.append(latency)

            # Keep only recent measurements (last 1000)
            if len(self.message_timestamps) > 1000:
                self.message_timestamps = self.message_timestamps[-1000:]
            if len(self.message_sizes) > 1000:
                self.message_sizes = self.message_sizes[-1000:]
            if len(self.latency_measurements) > 1000:
                self.latency_measurements = self.latency_measurements[-1000:]

        except Exception as e:
            self.errors.append({
                "time": time.time(),
                "error": str(e),
                "type": "message_handling"
            })

    async def monitor_delta_exchange_connection(self):
        """Monitor Delta Exchange WebSocket connection."""
        try:
            self.connection_attempts += 1

            # Connect to Delta Exchange
            await self.delta_ws_client.connect()
            self.connection_successes += 1

            # Subscribe to BTCUSD ticker
            await self.delta_ws_client.subscribe_ticker(["BTCUSD"])

            print("✅ Connected to Delta Exchange WebSocket")

            # Keep connection alive for monitoring period
            while time.time() - self.start_time < self.duration_seconds:
                await asyncio.sleep(1)

                # Send periodic heartbeat check
                if hasattr(self.delta_ws_client, 'websocket') and self.delta_ws_client.websocket:
                    try:
                        # Simple ping to check connection health
                        await self.delta_ws_client.websocket.ping()
                    except Exception as e:
                        self.errors.append({
                            "time": time.time(),
                            "error": f"Ping failed: {e}",
                            "type": "connection_health"
                        })

        except Exception as e:
            self.connection_failures += 1
            self.errors.append({
                "time": time.time(),
                "error": str(e),
                "type": "connection_failure"
            })
            print(f"❌ Delta Exchange WebSocket error: {e}")

        finally:
            if self.delta_ws_client:
                await self.delta_ws_client.disconnect()

    async def monitor_backend_connection(self):
        """Monitor backend WebSocket connection."""
        try:
            # Subscribe to market_tick channel
            subscribe_msg = {
                "type": "subscribe",
                "channels": ["market_tick"]
            }
            await self.backend_ws_client.send(json.dumps(subscribe_msg))

            # Listen for messages
            backend_messages = 0
            start_listen = time.time()

            while time.time() - self.start_time < self.duration_seconds:
                try:
                    # Set a timeout for receiving messages
                    message = await asyncio.wait_for(
                        self.backend_ws_client.recv(),
                        timeout=5.0
                    )

                    backend_messages += 1
                    data = json.loads(message)

                    if data.get("type") == "market_tick":
                        # This is a forwarded Delta Exchange message
                        pass

                except asyncio.TimeoutError:
                    # No message received within timeout - this is normal
                    continue
                except Exception as e:
                    self.errors.append({
                        "time": time.time(),
                        "error": f"Backend message error: {e}",
                        "type": "backend_message"
                    })
                    break

        except Exception as e:
            self.errors.append({
                "time": time.time(),
                "error": str(e),
                "type": "backend_connection"
            })

    async def calculate_throughput(self):
        """Calculate message throughput metrics."""
        while time.time() - self.start_time < self.duration_seconds:
            await asyncio.sleep(10)  # Calculate every 10 seconds

            if len(self.message_timestamps) >= 2:
                # Calculate messages per second over the last 10 seconds
                recent_timestamps = [t for t in self.message_timestamps
                                   if time.time() - t <= 10]
                if len(recent_timestamps) >= 2:
                    time_span = recent_timestamps[-1] - recent_timestamps[0]
                    if time_span > 0:
                        throughput = len(recent_timestamps) / time_span
                        self.throughput_measurements.append(throughput)

    async def run_monitoring(self):
        """Run the complete monitoring session."""
        print("🚀 Starting WebSocket Performance Monitoring")
        print(f"Duration: {self.duration_seconds} seconds")
        print("=" * 60)

        self.start_time = time.time()

        try:
            # Initialize clients
            await self.initialize_clients()

            # Start monitoring tasks
            tasks = [
                self.monitor_delta_exchange_connection(),
                self.monitor_backend_connection(),
                self.calculate_throughput()
            ]

            # Run all monitoring tasks concurrently
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            print(f"❌ Monitoring error: {e}")
        finally:
            self.end_time = time.time()
            await self.generate_report()

    async def generate_report(self):
        """Generate comprehensive performance report."""
        duration = self.end_time - self.start_time

        print("\n" + "=" * 80)
        print("📊 WebSocket Performance Report")
        print("=" * 80)
        print(f"Monitoring Duration: {duration:.2f} seconds")
        print(f"Start Time: {datetime.fromtimestamp(self.start_time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"End Time: {datetime.fromtimestamp(self.end_time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Connection Metrics
        print("\n🔌 Connection Metrics:")
        print(f"  Connection Attempts: {self.connection_attempts}")
        print(f"  Successful Connections: {self.connection_successes}")
        print(f"  Failed Connections: {self.connection_failures}")
        print(f"  Reconnections: {self.reconnections}")

        connection_success_rate = (self.connection_successes / max(self.connection_attempts, 1)) * 100
        print(f"  Success Rate: {connection_success_rate:.1f}%")

        # Message Metrics
        print("\n💬 Message Metrics:")
        print(f"  Total Messages Received: {self.messages_received}")
        if duration > 0:
            messages_per_second = self.messages_received / duration
            print(f"  Average Throughput: {messages_per_second:.2f} msg/s")

        if self.message_types:
            print("  Message Types:")
            for msg_type, count in sorted(self.message_types.items()):
                print(f"    {msg_type}: {count}")

        if self.message_sizes:
            avg_size = statistics.mean(self.message_sizes)
            print(f"  Average Message Size: {avg_size:.0f} bytes")

        # Performance Metrics
        print("\n⚡ Performance Metrics:")
        if self.latency_measurements:
            avg_latency = statistics.mean(self.latency_measurements) * 1000  # Convert to ms
            min_latency = min(self.latency_measurements) * 1000
            max_latency = max(self.latency_measurements) * 1000
            print(f"  Average Latency: {avg_latency:.2f} ms")
            print(f"  Min Latency: {min_latency:.2f} ms")
            print(f"  Max Latency: {max_latency:.2f} ms")

        if self.throughput_measurements:
            avg_throughput = statistics.mean(self.throughput_measurements)
            print(f"  Average Throughput: {avg_throughput:.2f} msg/s")

        # Error Analysis
        print("\n🚨 Error Analysis:")
        print(f"  Total Errors: {len(self.errors)}")
        if self.errors:
            error_types = {}
            for error in self.errors:
                error_type = error.get("type", "unknown")
                error_types[error_type] = error_types.get(error_type, 0) + 1

            print("  Error Types:")
            for error_type, count in sorted(error_types.items()):
                print(f"    {error_type}: {count}")

            # Show recent errors
            print("  Recent Errors:")
            for error in self.errors[-3:]:  # Show last 3 errors
                error_time = datetime.fromtimestamp(error["time"], timezone.utc)
                print(f"    {error_time.strftime('%H:%M:%S')}: {error['error'][:60]}...")

        # Health Assessment
        print("\n🏥 Health Assessment:")
        health_score = 100

        # Deduct points for various issues
        if self.connection_failures > 0:
            health_score -= 20
        if len(self.errors) > 5:
            health_score -= 15
        if self.messages_received == 0:
            health_score -= 50
        if duration > 0 and (self.messages_received / duration) < 0.1:
            health_score -= 20

        health_score = max(0, min(100, health_score))

        if health_score >= 90:
            status = "🟢 EXCELLENT"
        elif health_score >= 75:
            status = "🟡 GOOD"
        elif health_score >= 60:
            status = "🟠 FAIR"
        else:
            status = "🔴 POOR"

        print(f"  Overall Health Score: {health_score}/100 ({status})")

        # Recommendations
        print("\n💡 Recommendations:")
        if self.connection_failures > 0:
            print("  - Investigate connection stability issues")
        if len(self.errors) > 5:
            print("  - Review error handling and logging")
        if self.messages_received == 0:
            print("  - Check WebSocket subscription and API credentials")
        if health_score >= 90:
            print("  - System performing optimally! ✅")

        print("\n" + "=" * 80)

        # Generate alerts for production monitoring
        alerts = self._generate_alerts()
        if alerts:
            print("\n🚨 PRODUCTION ALERTS:")
            for alert in alerts:
                print(f"  {alert['level']}: {alert['message']}")

    def _generate_alerts(self) -> List[Dict[str, str]]:
        """Generate production alerts based on monitoring results."""
        alerts = []

        # WebSocket connection alerts
        if self.connection_failures > 0:
            alerts.append({
                "level": "🔴 CRITICAL",
                "message": f"WebSocket connection failures detected ({self.connection_failures} failures)"
            })

        # Data quality alerts
        if self.messages_received == 0:
            alerts.append({
                "level": "🔴 CRITICAL",
                "message": "No market data received - WebSocket streaming failed"
            })

        # Performance alerts
        if hasattr(self, 'latency_measurements') and self.latency_measurements:
            avg_latency = statistics.mean(self.latency_measurements) * 1000
            if avg_latency > 5000:  # 5 seconds
                alerts.append({
                    "level": "🟡 WARNING",
                    "message": f"High latency detected ({avg_latency:.0f}ms average)"
                })

        # Error rate alerts
        error_rate = len(self.errors) / max(self.duration_seconds, 1)
        if error_rate > 0.1:  # More than 0.1 errors per second
            alerts.append({
                "level": "🟡 WARNING",
                "message": f"High error rate detected ({error_rate:.2f} errors/second)"
            })

        return alerts


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor WebSocket performance for JackSparrow trading agent"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Monitoring duration in seconds (default: 300 = 5 minutes)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    print("🎯 JackSparrow WebSocket Performance Monitor")
    print(f"Monitoring for {args.duration} seconds...")
    print("Press Ctrl+C to stop early\n")

    monitor = WebSocketPerformanceMonitor(duration_seconds=args.duration)

    try:
        await monitor.run_monitoring()
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring stopped by user")
        monitor.end_time = time.time()
        await monitor.generate_report()
    except Exception as e:
        print(f"\n❌ Monitoring failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
