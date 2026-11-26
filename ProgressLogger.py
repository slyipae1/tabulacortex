import sys
import threading
from datetime import datetime
from typing import List, Callable, Optional
import re

class ProgressLogger:
    """Thread-safe progress logger that captures print statements and formats them for UI display"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._logs: List[str] = []
        self._callbacks: List[Callable[[str], None]] = []
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._is_capturing = False
    
    def add_callback(self, callback: Callable[[str], None]):
        """Add a callback function to be called when new logs are added"""
        with self._lock:
            self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[str], None]):
        """Remove a callback function"""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def start_capture(self):
        """Start capturing print statements"""
        if not self._is_capturing:
            sys.stdout = self
            self._is_capturing = True
    
    def stop_capture(self):
        """Stop capturing print statements"""
        if self._is_capturing:
            sys.stdout = self._original_stdout
            self._is_capturing = False
    
    def write(self, text: str):
        """Write method for stdout redirection"""
        # Write to original stdout as well
        self._original_stdout.write(text)
        self._original_stdout.flush()
        
        # Process and log the text
        if text.strip():  # Only log non-empty lines
            self._add_log(text.strip())
    
    def flush(self):
        """Flush method for stdout compatibility"""
        self._original_stdout.flush()
    
    def _add_log(self, message: str):
        """Add a log message and notify callbacks"""
        with self._lock:
            # timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_message = f"{message}"
            
            # Format message with appropriate emoji/styling
            formatted_message = self._format_message(formatted_message)
            
            self._logs.append(formatted_message)
            
            # Keep only last 100 logs to prevent memory issues
            if len(self._logs) > 100:
                self._logs = self._logs[-100:]
            
            # Notify all callbacks
            for callback in self._callbacks:
                try:
                    callback(self.get_logs_text())
                except Exception as e:
                    # Don't let callback errors break logging
                    self._original_stdout.write(f"Logger callback error: {e}\n")
    
    def _format_message(self, message: str) -> str:
        """Format log message with appropriate styling"""
        # return message # Basic formatting, can be extended with regex for more complex patterns
        # Add emoji and formatting based on content
        if "✓ Completed" in message:
            return f"✅ {message}"
        elif "✗ Failed" in message or "Error" in message:
            return f"❌ {message}"
        elif "Processing:" in message and not "🔄" in message:
            return f"🔄 {message}"
        elif "Starting" in message:
            return f"🚀 {message}"
        # elif "Found" in message and "groups" in message:
        #     return f"📊 {message}"
        # elif "Extracted style info" in message:
        #     return f"📋 {message}"
        # elif "Analyzing sheet" in message:
        #     return f"🔍 {message}"
        else:
            return message
    
    def get_logs_text(self) -> str:
        """Get all logs as formatted text"""
        with self._lock:
            return "\n".join(self._logs)
    
    def clear_logs(self):
        """Clear all logs"""
        with self._lock:
            self._logs.clear()
            # Notify callbacks of the clear
            for callback in self._callbacks:
                try:
                    callback("")
                except Exception:
                    pass
    
    def log_progress(self, message: str):
        """Manually log a progress message"""
        self._add_log(message)

# Global logger instance
progress_logger = ProgressLogger()