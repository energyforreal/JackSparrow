"""
Development file watcher for agent hot-reload.

Watches for Python file changes and restarts the agent process automatically.
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import structlog

logger = structlog.get_logger()


class AgentFileHandler(FileSystemEventHandler):
    """Handler for file system events that restarts the agent."""
    
    def __init__(self, restart_callback):
        """Initialize handler with restart callback."""
        self.restart_callback = restart_callback
        self.last_restart_time = 0
        self.debounce_seconds = 1.0  # Debounce rapid file changes
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
            
        # Only watch Python files
        if not event.src_path.endswith('.py'):
            return
            
        # Debounce rapid changes
        current_time = time.time()
        if current_time - self.last_restart_time < self.debounce_seconds:
            return
            
        # Ignore __pycache__ and .pyc files
        if '__pycache__' in event.src_path or event.src_path.endswith('.pyc'):
            return
            
        logger.info(
            "agent_file_changed",
            service="agent",
            file=event.src_path,
            message="Python file changed, restarting agent..."
        )
        
        self.last_restart_time = current_time
        self.restart_callback()


class AgentWatcher:
    """File watcher that restarts agent on code changes."""
    
    def __init__(self, watch_path: Optional[str] = None):
        """Initialize watcher.
        
        Args:
            watch_path: Directory to watch for changes (defaults to /app/agent or ./agent)
        """
        # Default to /app/agent in Docker, or ./agent for local development
        if watch_path is None:
            watch_path = os.environ.get("AGENT_WATCH_PATH", "/app/agent")
            # If /app/agent doesn't exist, try ./agent (local development)
            if not Path(watch_path).exists() and Path("./agent").exists():
                watch_path = "./agent"
        
        self.watch_path = Path(watch_path)
        self.observer = None
        self.agent_process = None
        self.running = False
        
    def start_agent(self):
        """Start the agent process."""
        if self.agent_process and self.agent_process.poll() is None:
            logger.info(
                "agent_stopping",
                service="agent",
                message="Stopping existing agent process for restart"
            )
            # Gracefully terminate the process
            self.agent_process.terminate()
            try:
                self.agent_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "agent_force_kill",
                    service="agent",
                    message="Agent process did not terminate gracefully, forcing kill"
                )
                self.agent_process.kill()
                self.agent_process.wait()
        
        logger.info(
            "agent_starting",
            service="agent",
            message="Starting agent process"
        )
        
        # Start agent process
        self.agent_process = subprocess.Popen(
            [sys.executable, "-m", "agent.core.intelligent_agent"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy()
        )
        
        # Start thread to stream output
        import threading
        def stream_output():
            if self.agent_process:
                for line in iter(self.agent_process.stdout.readline, ''):
                    if line:
                        print(line.rstrip())
                    if self.agent_process.poll() is not None:
                        break
        
        output_thread = threading.Thread(target=stream_output, daemon=True)
        output_thread.start()
    
    def restart_agent(self):
        """Restart the agent process."""
        self.start_agent()
    
    def start_watching(self):
        """Start watching for file changes."""
        if not self.watch_path.exists():
            logger.error(
                "agent_watch_path_not_found",
                service="agent",
                path=str(self.watch_path),
                message=f"Watch path does not exist: {self.watch_path}"
            )
            return
        
        logger.info(
            "agent_watcher_starting",
            service="agent",
            watch_path=str(self.watch_path),
            message="Starting file watcher for hot-reload"
        )
        
        # Start agent initially
        self.start_agent()
        
        # Setup file watcher
        event_handler = AgentFileHandler(self.restart_agent)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.watch_path), recursive=True)
        self.observer.start()
        self.running = True
        
        logger.info(
            "agent_watcher_ready",
            service="agent",
            message="File watcher is ready. Agent will auto-reload on Python file changes."
        )
        
        try:
            # Keep the watcher running
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(
                "agent_watcher_stopping",
                service="agent",
                message="Stopping file watcher"
            )
        finally:
            self.stop()
    
    def stop(self):
        """Stop watching and terminate agent."""
        self.running = False
        
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        if self.agent_process:
            logger.info(
                "agent_stopping",
                service="agent",
                message="Stopping agent process"
            )
            self.agent_process.terminate()
            try:
                self.agent_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.agent_process.kill()
                self.agent_process.wait()


def main():
    """Main entry point."""
    # Configure signal handlers for graceful shutdown
    watcher = AgentWatcher()
    
    def signal_handler(signum, frame):
        logger.info(
            "agent_watcher_signal",
            service="agent",
            signal=signum,
            message="Received shutdown signal"
        )
        watcher.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start watching
    watcher.start_watching()


if __name__ == "__main__":
    main()

