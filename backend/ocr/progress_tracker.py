#!/usr/bin/env python3
"""
Progress tracking for OCR processing.
Stores progress in JSON files for polling-based progress reporting.
"""

import json
import os
import time
from typing import Dict, Any, Optional
from pathlib import Path


class OCRProgressTracker:
    """
    Tracks OCR processing progress and stores it in JSON files.
    Progress can be polled via API endpoint.
    """
    
    def __init__(self, logs_dir: Optional[str] = None):
        """
        Initialize progress tracker.
        
        Args:
            logs_dir: Directory to store progress files (default: logs directory)
        """
        if logs_dir is None:
            # Default to logs directory relative to this file
            logs_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            )
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_progress_file_path(self, request_id: str) -> Path:
        """Get path to progress file for a request."""
        return self.logs_dir / f"progress_{request_id}.json"
    
    def update_progress(
        self,
        request_id: str,
        step: str,
        step_number: int,
        total_steps: int,
        progress_percent: float,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Update progress for a request.
        
        Args:
            request_id: Unique request identifier
            step: Current step name (e.g., "OCR Processing")
            step_number: Current step number (1-based)
            total_steps: Total number of steps
            progress_percent: Progress percentage (0-100)
            message: Optional progress message
            details: Optional additional details (e.g., pages_completed, total_pages)
        """
        progress_data = {
            "request_id": request_id,
            "step": step,
            "step_number": step_number,
            "total_steps": total_steps,
            "progress_percent": round(progress_percent, 2),
            "message": message,
            "details": details or {},
            "timestamp": time.time(),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        
        progress_file = self._get_progress_file_path(request_id)
        try:
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, indent=2)
                f.flush()  # Ensure data is written to buffer
                os.fsync(f.fileno())  # Force write to disk (Unix/Windows compatible)
        except Exception:
            # Never fail the pipeline due to progress tracking issues
            pass
    
    def get_progress(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current progress for a request.
        
        Args:
            request_id: Unique request identifier
        
        Returns:
            Progress data dictionary or None if not found
        """
        progress_file = self._get_progress_file_path(request_id)
        if not progress_file.exists():
            return None
        
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    
    def clear_progress(self, request_id: str) -> None:
        """
        Clear progress file for a request (cleanup after completion).
        
        Args:
            request_id: Unique request identifier
        """
        progress_file = self._get_progress_file_path(request_id)
        try:
            if progress_file.exists():
                progress_file.unlink()
        except Exception:
            # Never fail due to cleanup issues
            pass
    
    def cleanup_old_progress(self, max_age_seconds: int = 3600) -> None:
        """
        Clean up progress files older than max_age_seconds.
        
        Args:
            max_age_seconds: Maximum age of progress files in seconds (default: 1 hour)
        """
        current_time = time.time()
        try:
            for progress_file in self.logs_dir.glob("progress_*.json"):
                try:
                    file_age = current_time - progress_file.stat().st_mtime
                    if file_age > max_age_seconds:
                        progress_file.unlink()
                except Exception:
                    # Skip files that can't be processed
                    continue
        except Exception:
            # Never fail due to cleanup issues
            pass

