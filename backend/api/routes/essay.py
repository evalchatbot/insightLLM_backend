from fastapi import APIRouter, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
import logging
import os
import shutil
import stat
import uuid
import json
import time
import base64
from backend.eng_essay.grade_pdf_essay import run_essay_grading
# from backend.db.storage import StorageService # Disabled as per user request
from backend.ocr.job_manager import OCRJobManager, JobStatus
from backend.ocr.progress_tracker import OCRProgressTracker

router = APIRouter(prefix="/api/essay", tags=["essay"])
logger = logging.getLogger(__name__)

# Use a separate job directory for essays to avoid conflicts
_job_manager = OCRJobManager(
    jobs_dir=os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")), "essay_jobs"),
    results_dir=os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")), "essay_results")
)


def _get_logs_dir() -> str:
    """
    Get the logs directory path consistently.
    """
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
    logs_dir = os.path.join(project_root, "logs")
    return os.path.abspath(logs_dir)

def _get_eng_essay_dir() -> str:
    """
    Get the eng_essay directory path for temp folders.
    """
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    eng_essay_dir = os.path.abspath(os.path.join(current_file_dir, "..", "eng_essay"))
    return eng_essay_dir

def _cleanup_temp_folders():
    """
    Clean up ALL old timestamped temp folders (debug_llm_*, grok_images_essay_*).
    This prevents old files from previous jobs appearing and handles concurrent requests properly.
    """
    try:
        eng_essay_dir = _get_eng_essay_dir()
        
        # Clean up ALL timestamped debug and grok folders (not just one specific folder)
        import glob
        patterns_to_clean = [
            os.path.join(eng_essay_dir, "debug_llm_*"),
            os.path.join(eng_essay_dir, "grok_images_essay_*"),
            os.path.join(eng_essay_dir, "__pycache__"),
            # Also clean legacy folders without timestamp for backward compatibility
            os.path.join(eng_essay_dir, "debug_llm"),
            os.path.join(eng_essay_dir, "grok_images_essay"),
        ]
        
        folders_to_clean = []
        for pattern in patterns_to_clean:
            if "*" in pattern:
                folders_to_clean.extend(glob.glob(pattern))
            elif os.path.exists(pattern):
                folders_to_clean.append(pattern)
        
        logger.info(f"Found {len(folders_to_clean)} temp folder(s) to clean")
        
        for folder in folders_to_clean:
            if os.path.exists(folder):
                try:
                    # Force delete: remove read-only files first

                    def remove_readonly(func, path, _):
                        """Clear read-only bit and retry."""
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    
                    shutil.rmtree(folder, onerror=remove_readonly)
                    logger.info(f"Cleaned up old temp folder: {folder}")
                except Exception as e:
                    logger.error(f"Failed to clean {folder}: {e}")
                    # Try harder - delete files individually if folder delete fails
                    try:
                        for root, dirs, files in os.walk(folder, topdown=False):
                            for name in files:
                                try:
                                    file_path = os.path.join(root, name)
                                    os.chmod(file_path, stat.S_IWRITE)
                                    os.remove(file_path)
                                except:
                                    pass
                            for name in dirs:
                                try:
                                    os.rmdir(os.path.join(root, name))
                                except:
                                    pass
                        os.rmdir(folder)
                        logger.info(f"Force cleaned {folder}")
                    except Exception as e2:
                        logger.error(f"Force cleanup also failed for {folder}: {e2}")
    except Exception as e:
        logger.warning(f"Failed to clean up temp folders: {e}")

def _cleanup_old_results(max_age_hours: int = 24):
    """
    Delete result files (JSON/PDF) older than max_age_hours to free up disk space.
    """
    try:
        results_dir = os.path.join(_get_logs_dir(), "essay_results")
        if not os.path.exists(results_dir):
            return
        
        cutoff_time = time.time() - (max_age_hours * 3600)
        deleted_count = 0
        
        for filename in os.listdir(results_dir):
            filepath = os.path.join(results_dir, filename)
            if os.path.isfile(filepath):
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.info(f"Cleaned up old result file: {filename}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old result file(s)")
    except Exception as e:
        logger.warning(f"Failed to clean up old results: {e}")

def _process_essay_job(job_id: str, request_id: str, temp_dir: str, file_path: str, user_id: str, original_filename: str):
    """
    Background task wrapper for essay grading
    """
    # Use standard logs dir so /api/ocr/progress/{id} can find it
    tracker = OCRProgressTracker(logs_dir=_get_logs_dir())
    
    # Clean up old results (older than 24 hours) to save disk space
    _cleanup_old_results()
    
    # Clean up old temp folders (debug_llm, grok_images_essay) before starting new analysis
    _cleanup_temp_folders()
    
    # Progress callback for run_essay_grading
    def progress_callback(pct: float, msg: str):
        """Callback to update progress from essay grading pipeline"""
        # Map percentage to step numbers (6 total steps)
        step_num = max(1, min(6, int(pct / 100 * 6) + 1))
        tracker.update_progress(
            request_id=request_id,
            step="EssayGrading", 
            step_number=step_num, 
            total_steps=6,
            progress_percent=float(pct),
            message=msg
        )
        logger.info(f"Essay job {job_id} progress: {pct:.1f}% - {msg}")

    try:
        logger.info(f"Starting essay job {job_id} for user {user_id}, file: {original_filename}")
        _job_manager.update_job_status(job_id, JobStatus.RUNNING, started_at=time.time())
        progress_callback(0, "Starting Essay Grading...")

        output_json_path = _job_manager._get_result_json_path(job_id)
        output_pdf_path = _job_manager._get_result_pdf_path(job_id)
        
        # CRITICAL: Clean up any existing results for this job to prevent cache issues
        if output_json_path.exists():
            logger.info(f"Essay job {job_id} - Removing old cached JSON: {output_json_path}")
            os.remove(output_json_path)
        if output_pdf_path.exists():
            logger.info(f"Essay job {job_id} - Removing old cached PDF: {output_pdf_path}")
            os.remove(output_pdf_path)
        
        # Ensure paths exist
        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
        
        logger.info(f"Essay job {job_id} - Output paths: JSON={output_json_path}, PDF={output_pdf_path}")
        
        # Execute the pipeline with progress callback
        result_data = run_essay_grading(
             pdf_path=file_path,
             output_json_path=str(output_json_path),
             output_pdf_path=str(output_pdf_path),
             ocr_workers=5,  # Increased for better parallelization
             progress_callback=progress_callback,
             job_id=job_id,  # Pass job_id for unique folder naming
        )
        
        # Verify outputs exist
        if not os.path.exists(output_json_path):
            raise FileNotFoundError(f"JSON output not created: {output_json_path}")
        if not os.path.exists(output_pdf_path):
            raise FileNotFoundError(f"PDF output not created: {output_pdf_path}")
            
        logger.info(f"Essay job {job_id} - Outputs verified, JSON size: {os.path.getsize(output_json_path)} bytes, PDF size: {os.path.getsize(output_pdf_path)} bytes")
        
        # Result already saved by run_essay_grading, just ensure it's properly formatted
        if isinstance(result_data, dict):
            with open(str(output_json_path), "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
        
        progress_callback(100, "Essay Evaluation Complete!")
        _job_manager.complete_job(job_id)
        logger.info(f"Essay job {job_id} completed successfully")

    except Exception as e:
        logger.error(f"Essay job {job_id} failed: {e}", exc_info=True)
        error_msg = f"Failed: {str(e)}"
        tracker.update_progress(
            request_id=request_id,
            step="EssayGrading", 
            step_number=6, 
            total_steps=6,
            progress_percent=100.0,
            message=error_msg
        )
        _job_manager.fail_job(job_id, str(e))
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Essay job {job_id} - Cleaned up temp dir: {temp_dir}")



@router.post("/submit")
async def submit_essay(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
):
    if not file.filename.lower().endswith(".pdf"):
         raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    job_id = str(uuid.uuid4()) # Temporary job_id for temp dir creation, actual job_id comes from manager
    request_id = str(uuid.uuid4())
    
    temp_dir = f"temp_essay_job_{job_id}"
    os.makedirs(temp_dir, exist_ok=True)
    input_pdf_path = os.path.join(temp_dir, file.filename)

    
    with open(input_pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    # create_job generates its own job_id, so we need to use the one it returns
    # But wait, create_job implementation:
    # def create_job(self, request_id, user_id, filename, subject) -> OCRJob:
    #     job_id = uuid.uuid4().hex[:16]
    #
    # So we should pass request_id, user_id, filename, subject.
    # And then get the job_id from the returned job object.
    
    job = _job_manager.create_job(request_id, user_id, file.filename, "English Essay")
    # Reset job_id to the one controlled by the manager for consistency
    job_id = job.job_id
    
    
    # Run in background
    background_tasks.add_task(
        _process_essay_job,
        job_id,
        request_id,
        temp_dir,
        input_pdf_path,
        user_id,
        file.filename
    )
    
    return {"jobId": job_id, "requestId": request_id}


@router.get("/status/{job_id}")
async def get_essay_status(job_id: str):
    job = _job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/download/{job_id}", response_class=FileResponse)
async def download_essay_pdf(job_id: str):
    """
    Download the annotated PDF for a specific job.
    """
    job = _job_manager.get_job(job_id)
    if not job or job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Result not found or job not completed")
        
    pdf_path = _job_manager._get_result_pdf_path(job_id)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
        
    return FileResponse(
        path=pdf_path, 
        filename=f"annotated_essay_{job_id}.pdf",
        media_type="application/pdf"
    )

@router.get("/result/{job_id}")
async def get_essay_result(job_id: str):
    job = _job_manager.get_job(job_id)
    # Check finished
    if not job or job.status != JobStatus.COMPLETED:
         # If failed, return error
        if job and job.status == JobStatus.FAILED:
             raise HTTPException(status_code=400, detail=job.error or "Job failed")
        raise HTTPException(status_code=400, detail="Job not completed")
    
    json_path = _job_manager._get_result_json_path(job_id)
    
    if not json_path.exists():
        raise HTTPException(status_code=500, detail="Result files missing")
        
    # Backend URL for download
    # In production this should be the public URL, but here we construct a relative path to the API
    # The frontend is likely proxied or calling the same host.
    # We return a relative URL that the frontend can use.
    download_url = f"/api/essay/download/{job_id}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return {
        "result": data,
        "annotated_pdf_url": download_url
    }

