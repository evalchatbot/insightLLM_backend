from fastapi import APIRouter, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
import logging
import os
import shutil
import stat
import uuid
import json
import time
import glob

from backend.outline.grade_pdf_outline import run_outline_grading
from backend.ocr.job_manager import OCRJobManager, JobStatus
from backend.ocr.progress_tracker import OCRProgressTracker

router = APIRouter(prefix="/api/outline", tags=["outline"])
logger = logging.getLogger(__name__)

# Use a separate job directory for outline jobs
_job_manager = OCRJobManager(
    jobs_dir=os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")),
        "outline_jobs",
    ),
    results_dir=os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")),
        "outline_results",
    ),
)


def _get_logs_dir() -> str:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
    return os.path.join(project_root, "logs")


def _get_outline_dir() -> str:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(current_file_dir, "..", "outline"))


def _cleanup_temp_folders():
    """Clean up old timestamped temp folders from outline processing."""
    try:
        outline_dir = _get_outline_dir()
        patterns_to_clean = [
            os.path.join(outline_dir, "debug_*"),
            os.path.join(outline_dir, "grok_images_outline*"),
            os.path.join(outline_dir, "__pycache__"),
        ]
        folders_to_clean = []
        for pattern in patterns_to_clean:
            if "*" in pattern:
                folders_to_clean.extend(glob.glob(pattern))
            elif os.path.exists(pattern):
                folders_to_clean.append(pattern)

        for folder in folders_to_clean:
            if os.path.exists(folder):
                try:
                    def remove_readonly(func, path, _):
                        os.chmod(path, stat.S_IWRITE)
                        func(path)

                    shutil.rmtree(folder, onerror=remove_readonly)
                    logger.info(f"Cleaned up old temp folder: {folder}")
                except Exception as e:
                    logger.error(f"Failed to clean {folder}: {e}")
    except Exception as e:
        logger.warning(f"Failed to clean up temp folders: {e}")


def _cleanup_old_results(max_age_hours: int = 24):
    """Delete result files older than max_age_hours."""
    try:
        results_dir = os.path.join(_get_logs_dir(), "outline_results")
        if not os.path.exists(results_dir):
            return
        cutoff_time = time.time() - (max_age_hours * 3600)
        deleted_count = 0
        for filename in os.listdir(results_dir):
            filepath = os.path.join(results_dir, filename)
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff_time:
                os.remove(filepath)
                deleted_count += 1
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old outline result file(s)")
    except Exception as e:
        logger.warning(f"Failed to clean up old outline results: {e}")


def _process_outline_job(
    job_id: str,
    request_id: str,
    temp_dir: str,
    file_path: str,
    user_id: str,
    original_filename: str,
):
    """Background task for outline grading."""
    tracker = OCRProgressTracker(logs_dir=_get_logs_dir())

    _cleanup_old_results()
    _cleanup_temp_folders()

    def progress_callback(pct: float, msg: str):
        step_num = max(1, min(9, int(pct / 100 * 9) + 1))
        tracker.update_progress(
            request_id=request_id,
            step="OutlineGrading",
            step_number=step_num,
            total_steps=9,
            progress_percent=float(pct),
            message=msg,
        )
        logger.info(f"Outline job {job_id} progress: {pct:.1f}% - {msg}")

    try:
        logger.info(f"Starting outline job {job_id} for user {user_id}, file: {original_filename}")
        _job_manager.update_job_status(job_id, JobStatus.RUNNING, started_at=time.time())
        progress_callback(0, "Starting Outline Grading...")

        output_json_path = _job_manager._get_result_json_path(job_id)
        output_pdf_path = _job_manager._get_result_pdf_path(job_id)

        # Clean up existing results
        if output_json_path.exists():
            os.remove(output_json_path)
        if output_pdf_path.exists():
            os.remove(output_pdf_path)

        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)

        progress_callback(5, "Running OCR on outline pages...")

        result_data = run_outline_grading(
            pdf_path=file_path,
            output_json_path=str(output_json_path),
            output_pdf_path=str(output_pdf_path),
            input_type="outline",
        )

        # Verify outputs
        if not os.path.exists(output_json_path):
            raise FileNotFoundError(f"JSON output not created: {output_json_path}")
        if not os.path.exists(output_pdf_path):
            raise FileNotFoundError(f"PDF output not created: {output_pdf_path}")

        # Re-save result if it's a dict (ensure proper format)
        if isinstance(result_data, dict):
            with open(str(output_json_path), "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)

        progress_callback(100, "Outline Evaluation Complete!")
        _job_manager.complete_job(job_id)
        logger.info(f"Outline job {job_id} completed successfully")

    except Exception as e:
        logger.error(f"Outline job {job_id} failed: {e}", exc_info=True)
        error_msg = f"Failed: {str(e)}"
        tracker.update_progress(
            request_id=request_id,
            step="OutlineGrading",
            step_number=9,
            total_steps=9,
            progress_percent=100.0,
            message=error_msg,
        )
        _job_manager.fail_job(job_id, str(e))
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Outline job {job_id} - Cleaned up temp dir: {temp_dir}")


@router.post("/submit")
async def submit_outline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    pipeline: str = Form(""),
):
    if (pipeline or "").strip().lower() != "outline":
        raise HTTPException(
            status_code=400,
            detail="Invalid pipeline token for outline endpoint. Expected pipeline='outline'.",
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    job_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    temp_dir = f"temp_outline_job_{job_id}"
    os.makedirs(temp_dir, exist_ok=True)
    input_pdf_path = os.path.join(temp_dir, file.filename)

    with open(input_pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job = _job_manager.create_job(request_id, user_id, file.filename, "English Essay Outline")
    job_id = job.job_id

    background_tasks.add_task(
        _process_outline_job,
        job_id,
        request_id,
        temp_dir,
        input_pdf_path,
        user_id,
        file.filename,
    )

    return {"jobId": job_id, "requestId": request_id}


@router.get("/status/{job_id}")
async def get_outline_status(job_id: str):
    job = _job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/download/{job_id}", response_class=FileResponse)
async def download_outline_pdf(job_id: str):
    """Download the annotated PDF for an outline job."""
    job = _job_manager.get_job(job_id)
    if not job or job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Result not found or job not completed")

    pdf_path = _job_manager._get_result_pdf_path(job_id)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(
        path=pdf_path,
        filename=f"annotated_outline_{job_id}.pdf",
        media_type="application/pdf",
    )


@router.get("/result/{job_id}")
async def get_outline_result(job_id: str):
    job = _job_manager.get_job(job_id)
    if not job or job.status != JobStatus.COMPLETED:
        if job and job.status == JobStatus.FAILED:
            raise HTTPException(status_code=400, detail=job.error or "Job failed")
        raise HTTPException(status_code=400, detail="Job not completed")

    json_path = _job_manager._get_result_json_path(job_id)
    if not json_path.exists():
        raise HTTPException(status_code=500, detail="Result files missing")

    download_url = f"/api/outline/download/{job_id}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {"result": data, "annotated_pdf_url": download_url}
