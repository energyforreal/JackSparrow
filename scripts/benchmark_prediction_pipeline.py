#!/usr/bin/env python3
"""
Prediction Pipeline Performance Benchmark

Measures latency and performance of the complete MCP prediction pipeline.
"""

import asyncio
import time
import statistics
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.core.mcp_orchestrator import MCPOrchestrator


class PerformanceBenchmark:
    """Performance benchmarking suite."""

    def __init__(self):
        self.orchestrator = None
        self.results = {
            "initialization_time": None,
            "prediction_latencies": [],
            "memory_usage": [],
            "individual_model_latencies": [],
            "feature_computation_times": [],
            "consensus_calculation_times": [],
            "reasoning_times": []
        }

    async def setup(self):
        """Setup benchmark environment."""
        print("🚀 Setting up performance benchmark...")

        start_time = time.time()
        self.orchestrator = MCPOrchestrator()
        await self.orchestrator.initialize()
        self.results["initialization_time"] = time.time() - start_time

        print(".2f")

    async def teardown(self):
        """Clean up benchmark environment."""
        if self.orchestrator:
            await self.orchestrator.shutdown()
        print("✅ Benchmark teardown complete")

    async def run_prediction_benchmark(self, num_runs=10):
        """Run prediction performance benchmark."""
        print(f"📊 Running prediction benchmark ({num_runs} runs)...")

        for i in range(num_runs):
            print(f"  Run {i+1}/{num_runs}...", end=" ", flush=True)

            # Vary the context slightly for realistic testing
            context = {
                "current_price": 50000 + (i * 100),  # Vary price slightly
                "market_regime": "bull_trending",
                "volatility": 0.02 + (i * 0.001),  # Vary volatility
                "timestamp": f"2025-01-27T12:{i:02d}:00Z"
            }

            start_time = time.time()
            result = await self.orchestrator.process_prediction_request(
                symbol="BTCUSD",
                context=context
            )
            latency = time.time() - start_time

            self.results["prediction_latencies"].append(latency)

            # Extract detailed timing from result
            if "models" in result and "predictions" in result["models"]:
                model_latencies = [p.get("computation_time_ms", 0) / 1000
                                 for p in result["models"]["predictions"]]
                if model_latencies:
                    self.results["individual_model_latencies"].append(model_latencies)

            print(".3f")

        # Calculate statistics
        latencies = self.results["prediction_latencies"]
        self.results["latency_stats"] = {
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "min": min(latencies),
            "max": max(latencies),
            "p95": sorted(latencies)[int(len(latencies) * 0.95)],
            "p99": sorted(latencies)[int(len(latencies) * 0.99)]
        }

    async def run_concurrent_benchmark(self, num_concurrent=3):
        """Test concurrent prediction performance."""
        print(f"🔄 Testing concurrent predictions ({num_concurrent} concurrent)...")

        async def single_prediction(task_id):
            context = {
                "current_price": 50000 + (task_id * 50),
                "market_regime": "bull_trending",
                "task_id": task_id
            }

            start_time = time.time()
            result = await self.orchestrator.process_prediction_request(
                symbol=f"BTCUSD_{task_id}",
                context=context
            )
            latency = time.time() - start_time
            return latency, result

        # Run concurrent predictions
        start_time = time.time()
        tasks = [single_prediction(i) for i in range(num_concurrent)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        latencies = [r[0] for r in results]
        self.results["concurrent_stats"] = {
            "total_time": total_time,
            "individual_latencies": latencies,
            "max_concurrent_latency": max(latencies),
            "throughput": num_concurrent / total_time
        }

        print(".2f"
    async def generate_report(self):
        """Generate comprehensive performance report."""
        print("\n" + "="*60)
        print("📈 PERFORMANCE BENCHMARK REPORT")
        print("="*60)

        # Initialization
        if self.results["initialization_time"]:
            print("\n🚀 Initialization:")
            print(".2f")
        # Prediction Latency
        if "latency_stats" in self.results:
            stats = self.results["latency_stats"]
            print("\n⚡ Prediction Latency (seconds):")
            print(".3f")
            print(".3f")
            print(".3f")
            print(".3f")
            print(".3f")
            print(".3f")
        # Concurrent Performance
        if "concurrent_stats" in self.results:
            concurrent = self.results["concurrent_stats"]
            print("\n🔄 Concurrent Performance:")
            print(".2f")
            print(".3f")
            print(".1f")

        # Individual Model Performance
        if self.results["individual_model_latencies"]:
            avg_model_latencies = []
            for run_latencies in self.results["individual_model_latencies"]:
                avg_model_latencies.extend(run_latencies)

            if avg_model_latencies:
                print("\n🤖 Individual Model Performance:")
                print(".3f")
                print(".3f")
                print(".3f")

        # Performance Assessment
        print("\n🎯 Performance Assessment:")        if "latency_stats" in self.results:
            p95 = self.results["latency_stats"]["p95"]
            if p95 < 2.0:
                status = "🟢 EXCELLENT"
                note = "Well within target (< 2s)"
            elif p95 < 5.0:
                status = "🟡 GOOD"
                note = "Acceptable for production"
            else:
                status = "🔴 NEEDS OPTIMIZATION"
                note = "Too slow for real-time use"

            print(f"  Overall Performance: {status} ({note})")
            print(f"  95th percentile latency: {p95:.3f}s")

        # Recommendations
        print("\n💡 Recommendations:")        if "latency_stats" in self.results and self.results["latency_stats"]["p95"] > 3.0:
            print("  • Consider parallel model inference optimization")
            print("  • Implement model result caching")
            print("  • Review feature computation efficiency")

        if self.results.get("concurrent_stats", {}).get("throughput", 0) < 1.0:
            print("  • Optimize for concurrent workloads")
            print("  • Consider async processing improvements")

        print("  • Monitor memory usage in production")
        print("  • Implement performance alerting")

    async def run_full_benchmark(self):
        """Run complete benchmark suite."""
        try:
            await self.setup()

            # Run benchmarks
            await self.run_prediction_benchmark(num_runs=5)
            await self.run_concurrent_benchmark(num_concurrent=3)

            # Generate report
            await self.generate_report()

        finally:
            await self.teardown()


async def main():
    """Main benchmark runner."""
    benchmark = PerformanceBenchmark()
    await benchmark.run_full_benchmark()


if __name__ == "__main__":
    asyncio.run(main())
