#!/usr/bin/env python3
"""
Job manager for async OCR processing.
Manages job submission, status tracking, cancellation, and result storage.
"""

import json
import os
import time
import threading
import uuid
from enum import Enum
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime


class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OCRJob:
    """OCR job data structure."""
    job_id: str
    request_id: str
    user_id: Optional[str]
    filename: str
    subject: str
    status: JobStatus
    created_at: float
    started_at: Optional[float]
    completed_at: Optional[float]
    error: Optional[str]
    result_pdf_path: Optional[str]
    result_json_path: Optional[str]
    cancelled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


class OCRJobManager:
    """
    Manages OCR background jobs.
    Stores job status and results in files for persistence.
    """
    
    def __init__(self, jobs_dir: Optional[str] = None, results_dir: Optional[str] = None):
        """
        Initialize job manager.
        
        Args:
            jobs_dir: Directory to store job status files (default: logs/jobs)
            results_dir: Directory to store job results (default: logs/results)
        """
        if jobs_dir is None:
            # Default to logs/jobs directory
            logs_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            )
            jobs_dir = os.path.join(logs_dir, "jobs")
        if results_dir is None:
            logs_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            )
            results_dir = os.path.join(logs_dir, "results")
        
        self.jobs_dir = Path(jobs_dir)
        self.results_dir = Path(results_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory job tracking (for cancellation)
        self._active_jobs: Dict[str, threading.Thread] = {}
        self._job_cancellation_flags: Dict[str, bool] = {}
        self._lock = threading.Lock()
    
    def _get_job_file_path(self, job_id: str) -> Path:
        """Get path to job status file."""
        return self.jobs_dir / f"job_{job_id}.json"
    
    def _get_result_pdf_path(self, job_id: str) -> Path:
        """Get path to result PDF file."""
        return self.results_dir / f"result_{job_id}.pdf"
    
    def _get_result_json_path(self, job_id: str) -> Path:
        """Get path to result JSON file."""
        return self.results_dir / f"result_{job_id}.json"
    
    def _save_job(self, job: OCRJob) -> None:
        """Save job status to file."""
        try:
            job_file = self._get_job_file_path(job.job_id)
            with open(job_file, "w", encoding="utf-8") as f:
                json.dump(job.to_dict(), f, indent=2)
        except Exception:
            # Never fail due to file operations
            pass
    
    def _load_job(self, job_id: str) -> Optional[OCRJob]:
        """Load job from file."""
        job_file = self._get_job_file_path(job_id)
        if not job_file.exists():
            return None
        
        try:
            with open(job_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Convert status string back to enum
            data["status"] = JobStatus(data["status"])
            return OCRJob(**data)
        except Exception:
            return None
    
    def create_job(
        self,
        request_id: str,
        user_id: Optional[str],
        filename: str,
        subject: str,
    ) -> OCRJob:
        """
        Create a new OCR job.
        
        Args:
            request_id: Unique request identifier
            user_id: User ID (optional)
            filename: Original filename
            subject: Subject name
        
        Returns:
            Created OCRJob
        """
        job_id = uuid.uuid4().hex[:16]  # 16-character job ID
        
        job = OCRJob(
            job_id=job_id,
            request_id=request_id,
            user_id=user_id,
            filename=filename,
            subject=subject,
            status=JobStatus.PENDING,
            created_at=time.time(),
            started_at=None,
            completed_at=None,
            error=None,
            result_pdf_path=None,
            result_json_path=None,
            cancelled=False,
        )
        
        self._save_job(job)
        return job
    
    def submit_job(
        self,
        job: OCRJob,
        process_func: Callable[[OCRJob], None],
    ) -> None:
        """
        Submit a job for background processing.
        
        Args:
            job: OCR job to process
            process_func: Function to process the job
        """
        def job_worker():
            """Background worker thread."""
            with self._lock:
                self._active_jobs[job.job_id] = threading.current_thread()
                self._job_cancellation_flags[job.job_id] = False
            
            try:
                # Update status to running
                job.status = JobStatus.RUNNING
                job.started_at = time.time()
                self._save_job(job)
                
                # Check if cancelled before starting
                if self._job_cancellation_flags.get(job.job_id, False):
                    job.status = JobStatus.CANCELLED
                    job.completed_at = time.time()
                    self._save_job(job)
                    return
                
                # Process the job
                process_func(job)
                
                # Check if cancelled after processing
                if self._job_cancellation_flags.get(job.job_id, False):
                    job.status = JobStatus.CANCELLED
                    job.completed_at = time.time()
                    self._save_job(job)
                    return
                
                # Mark as completed
                job.status = JobStatus.COMPLETED
                job.completed_at = time.time()
                self._save_job(job)
                
            except Exception as e:
                # Mark as failed
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = time.time()
                self._save_job(job)
            finally:
                # Clean up
                with self._lock:
                    self._active_jobs.pop(job.job_id, None)
                    self._job_cancellation_flags.pop(job.job_id, None)
        
        # Start background thread
        thread = threading.Thread(target=job_worker, daemon=True)
        thread.start()
    
    def get_job(self, job_id: str) -> Optional[OCRJob]:
        """
        Get job by ID.
        
        Args:
            job_id: Job identifier
        
        Returns:
            OCRJob or None if not found
        """
        return self._load_job(job_id)
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job.
        
        Args:
            job_id: Job identifier
        
        Returns:
            True if job was cancelled, False if not found or already completed
        """
        job = self._load_job(job_id)
        if not job:
            return False
        
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        
        # Set cancellation flag
        with self._lock:
            self._job_cancellation_flags[job_id] = True
        
        # Update job status
        job.status = JobStatus.CANCELLED
        job.cancelled = True
        job.completed_at = time.time()
        self._save_job(job)
        
        return True
    
    def is_job_cancelled(self, job_id: str) -> bool:
        """
        Check if a job is cancelled.
        
        Args:
            job_id: Job identifier
        
        Returns:
            True if job is cancelled, False otherwise
        """
        return self._job_cancellation_flags.get(job_id, False)
    
    def cleanup_old_jobs(self, max_age_seconds: int = 86400) -> None:
        """
        Clean up old job files (older than max_age_seconds).
        
        Args:
            max_age_seconds: Maximum age of job files in seconds (default: 24 hours)
        """
        current_time = time.time()
        try:
            for job_file in self.jobs_dir.glob("job_*.json"):
                try:
                    job = self._load_job(job_file.stem.replace("job_", ""))
                    if job and job.completed_at:
                        file_age = current_time - job.completed_at
                        if file_age > max_age_seconds:
                            # Delete job file and results
                            job_file.unlink()
                            if job.result_pdf_path and os.path.exists(job.result_pdf_path):
                                os.remove(job.result_pdf_path)
                            if job.result_json_path and os.path.exists(job.result_json_path):
                                os.remove(job.result_json_path)
                except Exception:
                    # Skip files that can't be processed
                    continue
        except Exception:
            # Never fail due to cleanup issues
            pass

