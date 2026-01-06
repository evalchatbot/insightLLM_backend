# Graceful Cancellation Implementation Plan

**Date Created**: December 2025  
**Status**: 📋 Pending Implementation  
**Purpose**: Implement graceful cancellation for OCR analysis jobs with proper risk mitigation

---

## Overview

This document outlines a step-by-step plan to implement graceful cancellation for PDF analysis jobs. The implementation ensures:
- Safe cancellation at appropriate points
- Minimal wasted API credits
- Proper cleanup of resources
- Clear user feedback
- No data corruption

---

## Phase 1: Risk Analysis and Cancellation Strategy

### Safe Cancellation Points (Low Risk) ✅

1. **Between Pipeline Steps**: After Step 1, 2, 3, etc. completes
   - Risk: None
   - Action: Check cancellation flag, cleanup if needed

2. **Between OCR Batches**: Between page batches during OCR processing
   - Risk: None
   - Action: Check before starting next batch

3. **Before API Calls**: Before sending Grok/OCR requests
   - Risk: None
   - Action: Check cancellation flag before `requests.post()`

4. **During File Operations**: PDF rendering, image processing
   - Risk: Low (partial files can be cleaned up)
   - Action: Check between operations, cleanup temp files

### Risky Cancellation Points (Handle Carefully) ⚠️

1. **During Grok API Calls**:
   - **Risk**: Wasted API credits (request already sent)
   - **Mitigation**: Check BEFORE sending request, allow request to complete if already sent
   - **Impact**: Financial cost only, no data corruption
   - **Strategy**: Check cancellation flag before each API call, don't interrupt in-flight requests

2. **During OCR API Calls**:
   - **Risk**: Wasted Google Vision credits
   - **Mitigation**: Check before each page/batch, allow in-flight requests to complete
   - **Impact**: Financial cost only, no data corruption
   - **Strategy**: Check cancellation flag before each batch, complete current batch if already started

3. **During File Writes**:
   - **Risk**: Partial/corrupted files
   - **Mitigation**: Use temp files, cleanup on cancellation, atomic writes
   - **Impact**: Low (temp files can be deleted)
   - **Strategy**: Always write to temp files first, cleanup on cancellation

4. **During Thread Pool Operations**:
   - **Risk**: Threads may continue running
   - **Mitigation**: Check cancellation flag before each task, graceful shutdown
   - **Impact**: Medium (may waste resources)
   - **Strategy**: Check flag before submitting tasks, don't start new tasks if cancelled

---

## Phase 2: Implementation Steps

### Step 1: Add Cancellation Check Function to `service.py`

**File**: `backend/ocr/service.py`  
**Function**: `process_ocr_job`

**Changes**:
```python
def process_ocr_job(job: OCRJob, job_manager: OCRJobManager) -> None:
    """
    Process an OCR job in the background.
    """
    # ... existing code ...
    
    # Create cancellation check function
    def check_cancelled() -> bool:
        """Check if job has been cancelled."""
        return job_manager.is_job_cancelled(job.job_id)
    
    try:
        # Check cancellation before processing
        if check_cancelled():
            _append_log(log_path, "INFO", f"request={job.request_id} cancelled_before_start")
            progress_tracker.update_progress(
                request_id=job.request_id,
                step="Cancelled",
                step_number=0,
                total_steps=11,
                progress_percent=0.0,
                message="Job cancelled before processing started",
            )
            return
        
        # Call grading function with cancellation check
        grade_pdf_answer(
            pdf_path=input_pdf_path,
            subject=job.subject,
            output_json_path=output_json_path,
            output_pdf_path=output_pdf_path,
            user_id=job.user_id,
            log_path=log_path,
            request_id=job.request_id,
            progress_tracker=progress_tracker,
            cancellation_check=check_cancelled,  # ADD THIS
        )
        
        # Check cancellation after processing
        if check_cancelled():
            _append_log(log_path, "INFO", f"request={job.request_id} cancelled_after_processing")
            # Cleanup partial results
            for path in [output_pdf_path, output_json_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            return
        
        # ... rest of existing code ...
```

---

### Step 2: Modify `grade_pdf_answer` Signature

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `grade_pdf_answer`

**Changes**:
```python
from typing import Callable

def grade_pdf_answer(
    pdf_path: str,
    subject: str,
    output_json_path: str,
    output_pdf_path: str,
    user_id: Optional[str] = None,
    log_path: Optional[str] = None,
    request_id: Optional[str] = None,
    progress_tracker: Optional[Any] = None,
    cancellation_check: Optional[Callable[[], bool]] = None,  # ADD THIS
) -> None:
```

---

### Step 3: Add Cancellation Check Helper Function

**File**: `backend/ocr/grade_pdf_answer.py`  
**Location**: After imports, before main functions

**Changes**:
```python
class CancellationError(RuntimeError):
    """Raised when job is cancelled."""
    pass

def _check_cancellation(
    cancellation_check: Optional[Callable[[], bool]],
    request_id: Optional[str],
    log_path: Optional[str],
    step_name: str,
) -> None:
    """
    Check if job has been cancelled and raise CancellationError if so.
    
    Args:
        cancellation_check: Function that returns True if cancelled
        request_id: Request ID for logging
        log_path: Log file path
        step_name: Name of current step for logging
    """
    if cancellation_check and cancellation_check():
        _append_log(
            log_path,
            "INFO",
            f"request={request_id} cancelled_at_step={step_name}",
        )
        raise CancellationError(f"Job cancelled during {step_name}")
```

---

### Step 4: Add Cancellation Checks After Each Major Step

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `grade_pdf_answer`

**Changes**: Add cancellation checks after each step:

```python
# Step 1: Converting PDF pages to images
page_images = pdf_to_page_images_for_grok(pdf_path, output_dir=output_dir)
_check_cancellation(cancellation_check, request_id, log_path, "PDF to images conversion")

# After Step 2 (OCR):
ocr_data = run_ocr_on_pdf(...)
_check_cancellation(cancellation_check, request_id, log_path, "OCR processing")

# After Step 3 (Section detection):
sections, section_token_usage = call_grok_for_section_detection(...)
_check_cancellation(cancellation_check, request_id, log_path, "Section detection")

# After Step 4 (Subject grading):
grading_result, grading_token_usage = call_grok_for_grading(...)
_check_cancellation(cancellation_check, request_id, log_path, "Subject grading")

# After Step 5 (Refined rubric):
refined_result, refined_token_usage = call_grok_for_refined_rubric_annotations(...)
_check_cancellation(cancellation_check, request_id, log_path, "Refined rubric")

# Continue for all remaining steps...
```

**Steps to add checks after**:
- Step 1: PDF to images conversion
- Step 2: OCR processing
- Step 3: Section detection
- Step 4: Subject grading
- Step 5: Refined rubric annotations
- Step 6: Report rendering
- Step 7: PDF annotation
- Step 8: PDF merging

---

### Step 5: Add Cancellation Checks in OCR Batch Processing

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `run_ocr_on_pdf`

**Changes**: Modify batch processing loop:

```python
# BATCH ORCHESTRATION PHASE
for batch_start in range(1, len(images), batch_size):
    # CHECK CANCELLATION BEFORE EACH BATCH
    if cancellation_check and cancellation_check():
        _append_log(
            log_path,
            "INFO",
            f"request={request_id} ocr_cancelled_batch_start={batch_start}",
        )
        # Update progress to show cancellation
        if progress_tracker:
            progress_tracker.update_progress(
                request_id=request_id,
                step="OCR Processing",
                step_number=2,
                total_steps=11,
                progress_percent=15.0 + (batch_start / len(images)) * 30.0,
                message="OCR processing cancelled",
            )
        raise CancellationError("OCR processing cancelled by user")
    
    # Process batch...
    # ... existing batch processing code ...
    
    # CHECK CANCELLATION AFTER BATCH COMPLETES (before next batch)
    if cancellation_check and cancellation_check():
        _append_log(
            log_path,
            "INFO",
            f"request={request_id} ocr_cancelled_batch_end={batch_start + batch_size}",
        )
        raise CancellationError("OCR processing cancelled by user")
```

**Note**: Also need to pass `cancellation_check` parameter to `run_ocr_on_pdf` function.

---

### Step 6: Add Cancellation Checks in Grok API Calls (Before Sending)

**File**: `backend/ocr/grade_pdf_answer.py`  
**Functions**: 
- `call_grok_for_section_detection`
- `call_grok_for_grading`
- `call_grok_for_refined_rubric_annotations`
- `call_grok_for_page_wise_suggestions`

**Changes**: Add cancellation check parameter and check before API calls:

```python
def call_grok_for_section_detection(
    grok_api_key: str,
    ocr_data: Dict[str, Any],
    page_images: List[Dict[str, Any]],
    cancellation_check: Optional[Callable[[], bool]] = None,  # ADD THIS
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    
    # CHECK BEFORE SENDING API REQUEST
    if cancellation_check and cancellation_check():
        raise CancellationError("Job cancelled before Grok API call")
    
    # ... prepare payload ...
    
    for attempt in range(max_retries):
        # CHECK BEFORE EACH RETRY ATTEMPT
        if cancellation_check and cancellation_check():
            raise CancellationError("Job cancelled during Grok API retry")
        
        resp = requests.post(...)
        # ... rest of code ...
```

**Important**: Check cancellation BEFORE sending the request, not during. Once request is sent, allow it to complete to avoid wasting credits.

---

### Step 7: Handle Cancellation in Try-Except Blocks

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `grade_pdf_answer`

**Changes**: Wrap main processing in try-except:

```python
try:
    # ... all pipeline steps ...
except CancellationError as e:
    # Handle cancellation gracefully
    _append_log(log_path, "INFO", f"request={request_id} cancellation_handled error={str(e)}")
    
    # Update progress
    if progress_tracker:
        progress_tracker.update_progress(
            request_id=request_id,
            step="Cancelled",
            step_number=0,
            total_steps=11,
            progress_percent=0.0,
            message="Job cancelled by user",
        )
    
    # Cleanup temp files
    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
        except Exception:
            pass
    
    # Cleanup partial output files
    for path in [output_json_path, output_pdf_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    
    # Re-raise to let job_manager handle it
    raise
except Exception as e:
    # ... existing error handling ...
```

---

### Step 8: Update Job Manager to Handle CancellationError

**File**: `backend/ocr/job_manager.py`  
**Function**: `submit_job` → `job_worker`

**Changes**: Handle CancellationError in worker thread:

```python
def job_worker():
    """Background worker thread."""
    # ... existing code ...
    
    try:
        # ... process job ...
        process_func(job)
        
        # Check cancellation after processing
        if self._job_cancellation_flags.get(job.job_id, False):
            job.status = JobStatus.CANCELLED
            job.completed_at = time.time()
            self._save_job(job)
            return
        
        # Mark as completed
        job.status = JobStatus.COMPLETED
        # ... rest of code ...
        
    except CancellationError:
        # Handle cancellation gracefully
        job.status = JobStatus.CANCELLED
        job.completed_at = time.time()
        job.error = "Cancelled by user"
        self._save_job(job)
        return
    except Exception as e:
        # ... existing error handling ...
```

**Note**: Need to import `CancellationError` from `grade_pdf_answer.py` or create a shared exception module.

---

### Step 9: Update Frontend Cancel Button Visibility

**File**: `insightLLM_frontend_2.0/src/components/OCRUpload.tsx`

**Changes**: Ensure cancel button is visible during processing:

```tsx
{loading && jobId && (
  <div className="flex items-center justify-between mb-4">
    <div className="flex-1">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium">{loadingStage}</span>
        <span className="text-sm text-muted-foreground">{progress}%</span>
      </div>
      <Progress value={progress} className="h-2" />
    </div>
    <Button
      variant="outline"
      size="sm"
      onClick={handleCancel}
      className="ml-4 text-red-600 border-red-300 hover:bg-red-50 hover:border-red-400"
      disabled={!jobId}
    >
      <X className="h-4 w-4 mr-1" />
      Cancel
    </Button>
  </div>
)}
```

**Location**: In the progress indicator section, make it prominent and always visible when `loading && jobId` is true.

---

### Step 10: Update Frontend to Handle Cancellation Response

**File**: `insightLLM_frontend_2.0/src/components/OCRUpload.tsx`  
**Function**: `handleCancel`

**Changes**: Improve cancellation handling:

```tsx
const handleCancel = async () => {
  if (!jobId) return
  
  try {
    await cancelJob(jobId)
    stopPolling()
    setLoading(false)
    setLoadingStage("Cancelling...")
    setProgress(0)
    
    // Wait a moment for backend to process cancellation
    setTimeout(() => {
      setError("Job cancelled by user")
      setLoadingStage("")
      setJobId(null)
      setRequestId(null)
      setJobStatus(null)
      setProgressData(null)
    }, 1000)
  } catch (err) {
    console.error("Failed to cancel job:", err)
    const errorMessage = err instanceof Error ? err.message : "Failed to cancel job"
    setError(errorMessage)
    setToast(errorMessage)
  }
}
```

**Also update**: `pollStatus` function to handle cancelled status:

```tsx
const pollStatus = async () => {
  if (!jobId) return
  
  try {
    const status = await getJobStatus(jobId)
    setJobStatus(status.status)
    
    if (status.status === "completed") {
      // ... existing completion handling ...
    } else if (status.status === "failed") {
      // ... existing failure handling ...
    } else if (status.status === "cancelled") {
      stopPolling()
      setLoading(false)
      setLoadingStage("")
      setError("Job was cancelled")
      setJobId(null)
      setRequestId(null)
      setJobStatus(null)
    }
  } catch (err) {
    // ... existing error handling ...
  }
}
```

---

## Phase 3: Testing Checklist

### Test Scenarios

1. ✅ **Cancel Before OCR Starts**
   - Action: Submit job, cancel immediately
   - Expected: Job cancelled, no OCR processing, cleanup successful

2. ✅ **Cancel During OCR (Between Batches)**
   - Action: Submit job, cancel during OCR processing
   - Expected: Current batch completes, next batch doesn't start, cleanup successful

3. ✅ **Cancel After OCR, Before Grok Calls**
   - Action: Submit job, cancel after OCR completes
   - Expected: No Grok API calls made, cleanup successful

4. ✅ **Cancel During Grok Section Detection (Before API Call)**
   - Action: Submit job, cancel right before section detection
   - Expected: No API call sent, cleanup successful

5. ✅ **Cancel During Grok Grading (Before API Call)**
   - Action: Submit job, cancel right before grading
   - Expected: No API call sent, cleanup successful

6. ✅ **Cancel During File Rendering**
   - Action: Submit job, cancel during PDF rendering
   - Expected: Partial files cleaned up, no corrupted output

7. ✅ **Verify Cleanup**
   - Check: Temp files removed
   - Check: Output files removed if cancelled
   - Check: Progress file shows cancelled status

8. ✅ **Verify Progress Updates**
   - Check: Progress shows "Cancelled" status
   - Check: Progress percentage stops updating
   - Check: Message shows cancellation

9. ✅ **Verify Frontend UI**
   - Check: Cancel button visible during processing
   - Check: Button disabled when no job running
   - Check: UI updates to show cancelled state
   - Check: Error message displayed

10. ✅ **Verify API Credits**
    - Check: No wasted credits if cancelled before API calls
    - Check: Minimal wasted credits if cancelled during API calls (only in-flight requests)

---

## Phase 4: Risk Mitigation Summary

| Operation | Cancellation Risk | Mitigation Strategy | Impact if Cancelled |
|-----------|------------------|---------------------|---------------------|
| PDF to images | Low | Check before/after, cleanup temp files | None - temp files cleaned up |
| OCR batch processing | Medium | Check between batches, allow in-flight requests | Low - current batch completes |
| OCR API calls | Medium | Check before sending, allow request to complete | Medium - wasted credits for in-flight requests |
| Grok API calls | High (cost) | Check before sending, don't interrupt in-flight | High - wasted credits if request already sent |
| File rendering | Low | Check between steps, cleanup partial files | Low - partial files cleaned up |
| Thread operations | Medium | Check before each task, graceful shutdown | Medium - may waste resources |

---

## Implementation Order

1. ✅ **Step 1**: Add cancellation check function (`service.py`)
2. ✅ **Step 2**: Modify function signatures (`grade_pdf_answer.py`)
3. ✅ **Step 3**: Add cancellation helper function (`grade_pdf_answer.py`)
4. ✅ **Step 4**: Add checks after major steps (`grade_pdf_answer.py`)
5. ✅ **Step 5**: Add checks in OCR batches (`grade_pdf_answer.py`)
6. ✅ **Step 6**: Add checks in Grok calls (`grade_pdf_answer.py`)
7. ✅ **Step 7**: Handle CancellationError (`grade_pdf_answer.py`)
8. ✅ **Step 8**: Update job_manager (`job_manager.py`)
9. ✅ **Step 9**: Update frontend UI (`OCRUpload.tsx`)
10. ✅ **Step 10**: Test all scenarios

---

## Additional Considerations

### Exception Handling

Create a shared exception module or import `CancellationError` consistently:

```python
# Option 1: Create shared exception module
# backend/ocr/exceptions.py
class CancellationError(RuntimeError):
    """Raised when job is cancelled."""
    pass

# Option 2: Import from grade_pdf_answer.py
# In job_manager.py:
from backend.ocr.grade_pdf_answer import CancellationError
```

### Progress Tracking

Ensure progress tracker shows cancellation status:

```python
progress_tracker.update_progress(
    request_id=request_id,
    step="Cancelled",
    step_number=0,
    total_steps=11,
    progress_percent=0.0,
    message="Job cancelled by user",
)
```

### Cleanup Strategy

Always cleanup:
- Temp directories (`output_dir`)
- Partial output files (`output_json_path`, `output_pdf_path`)
- Progress files (optional - can keep for debugging)

### Logging

Log all cancellation events:
- Before processing starts
- After each step
- During batch processing
- Before API calls
- After cancellation handled

---

## Notes

- **API Credits**: Once a Grok/OCR API request is sent, it will consume credits even if cancelled. Check cancellation BEFORE sending requests.
- **Thread Safety**: Cancellation flags are thread-safe via `threading.Lock` in `job_manager`.
- **User Experience**: Frontend should show clear cancellation status and allow user to start new job immediately.
- **Error Recovery**: Cancelled jobs should not leave system in inconsistent state.

---

## Future Enhancements

1. **Partial Results**: Allow user to download partial results if cancelled mid-processing
2. **Resume Capability**: Save progress and allow resuming from last checkpoint
3. **Cancellation Timeout**: Auto-cancel jobs that exceed time limit
4. **Cancellation Analytics**: Track cancellation reasons and patterns

---

**Status**: Ready for implementation  
**Priority**: Medium  
**Estimated Time**: 4-6 hours  
**Dependencies**: None

