# Log Files Location

This document describes where log files are stored and what they contain.

---

## Log Files Location

All log files are stored in the **`logs`** directory at the project root:

```
insightLLM_backend/
└── logs/
    ├── log.txt              # Main log file (all log levels)
    ├── ocr_log.txt          # OCR-specific log file (OCR processing logs only)
    ├── errors_log.txt       # Error log file (ERROR level only)
    ├── jobs/                # Job status files
    │   └── job_*.json
    ├── results/            # Job results (PDFs and JSONs)
    │   ├── input_*.pdf      # Input PDFs for async jobs
    │   ├── result_*.pdf     # Output PDFs
    │   └── result_*.json    # Output metadata
    └── progress_*.json      # Progress tracking files
```

---

## Absolute Paths

### Windows
```
D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\log.txt
D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\ocr_log.txt
D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\errors_log.txt
```

### Linux/Mac
```
/path/to/insightLLM_backend/logs/log.txt
/path/to/insightLLM_backend/logs/ocr_log.txt
/path/to/insightLLM_backend/logs/errors_log.txt
```

---

## Log Files Description

### `log.txt`

**Location**: `insightLLM_backend/logs/log.txt`

**Purpose**: Main log file containing all log levels (INFO, WARNING, ERROR, etc.)

**Contents**:
- All application logs (including OCR logs)
- General application events
- Non-OCR specific logs
- Request IDs for tracking

**Note**: OCR-specific logs are also written to `ocr_log.txt` for easier filtering.

**Size**: Can grow large over time (consider log rotation)

---

### `ocr_log.txt`

**Location**: `insightLLM_backend/logs/ocr_log.txt`

**Purpose**: OCR-specific log file containing only OCR processing logs

**Contents**:
- Upload start events (`upload_start`)
- PDF start events (`start pdf=`)
- All step logs (`step=1`, `step=2`, etc. through `step=11`)
- Timing reports (`TIMING_REPORT_START`, `TIMING_REPORT_END`)
- Completion events (`completed`)
- Report generation (`report_generated`)
- All OCR-related logs (`ocr_parallel_start`, `ocr_page_complete`, `ocr_complete`, `ocr_retry_stats`, etc.)

**Example entries**:
```
2025-12-26T02:54:14.855846Z [INFO] request=192ebe95 upload_start filename=Current Affairs 1.pdf bytes=7509282 subject=current-affairs
2025-12-26T02:54:14.986490Z [INFO] request=192ebe95 start pdf=tmp8m841205.pdf subject=current-affairs
2025-12-26T02:55:19.015466Z [INFO] request=192ebe95 step=1 name=convert_pdf_images duration_ms=63881
2025-12-26T02:56:14.020127Z [INFO] request=192ebe95 ocr_parallel_start total_pages=9 concurrent_pages=2
2025-12-26T02:59:04.872421Z [INFO] request=192ebe95 ocr_page_complete page=1 duration_ms=163668
2025-12-26T03:09:31.293134Z [INFO] request=192ebe95 TIMING_REPORT_START
2025-12-26T03:09:31.298614Z [INFO] request=192ebe95 Step 1: Convert PDF to images duration=1 min 3 sec
2025-12-26T03:09:31.308792Z [INFO] request=192ebe95 TIMING_REPORT_END
2025-12-26T03:09:31.309923Z [INFO] request=192ebe95 completed total_duration_ms=916301
2025-12-26T03:09:31.866234Z [INFO] request=192ebe95 report_generated filename=Current Affairs 1.pdf total_duration_ms=917010
```

**OCR Log Patterns**:
- `upload_start` - File upload started
- `start pdf=` - PDF processing started
- `step=1` through `step=11` - Processing steps
- `ocr_*` - All OCR-related events (parallel start, page complete, retry stats, etc.)
- `TIMING_REPORT_START/END` - Timing report boundaries
- `completed` - Job completion
- `report_generated` - Report generation complete

**Size**: Typically smaller than `log.txt` (only OCR-related logs)

**Note**: This file is automatically created when the first OCR log is written.

---

### `errors_log.txt`

**Location**: `insightLLM_backend/logs/errors_log.txt`

**Purpose**: Error-only log file containing only ERROR level messages

**Contents**:
- All ERROR level log entries
- Duplicate of errors in `log.txt` (for easy filtering)
- Error messages with request IDs
- Stack traces (if logged)
- Failure reasons

**Example entries**:
```
2025-12-26T03:20:00.000000Z [ERROR] request=abc123 Input PDF not found for job e538e38092174e81
2025-12-26T03:21:00.000000Z [ERROR] request=def456 MemoryError: Unable to allocate array
```

**Size**: Typically smaller than `log.txt` (only errors)

**Note**: This file is automatically created when the first ERROR is logged.

---

## How Log Files Are Created

### Path Calculation

Both `log.txt` and `errors_log.txt` use the same directory path, calculated consistently:

**In `backend/ocr/service.py`**:
```python
def _get_logs_dir() -> str:
    """Get the logs directory path consistently."""
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up 2 levels: ocr -> backend -> project root
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", ".."))
    logs_dir = os.path.join(project_root, "logs")
    return os.path.abspath(logs_dir)
```

**In `backend/api/routes/ocr.py`**:
```python
def _get_logs_dir() -> str:
    """Get the logs directory path consistently."""
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up 3 levels: routes -> api -> backend -> project root
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
    logs_dir = os.path.join(project_root, "logs")
    return os.path.abspath(logs_dir)
```

Both functions resolve to the same path: `insightLLM_backend/logs/`

---

## Logging Functions

### `_append_log()` Function

Located in:
- `backend/ocr/service.py`
- `backend/ocr/grade_pdf_answer.py`

**Behavior**:
1. Writes to `log.txt` (all log levels)
2. If message is OCR-related, also writes to `ocr_log.txt`
3. If level is "ERROR", also writes to `errors_log.txt`

**OCR Log Detection**:
A log message is considered OCR-related if it contains:
- `upload_start` - File upload started
- `start pdf=` - PDF processing started
- `step=` - Processing step (step=1, step=2, etc.)
- `TIMING_REPORT` - Timing report boundaries
- `completed` - Job completion
- `report_generated` - Report generation
- `ocr_*` - Any OCR-related event (ocr_parallel_start, ocr_page_complete, etc.)

**Pattern**: Messages starting with `request=` and containing any of the above patterns are considered OCR logs.

**Example**:
```python
_append_log(log_path, "INFO", "Processing started")
_append_log(log_path, "ERROR", "Failed to process PDF")
```

---

## Directory Structure

```
insightLLM_backend/
├── backend/
│   ├── api/
│   │   └── routes/
│   │       └── ocr.py          # Uses _get_logs_dir() -> logs/
│   └── ocr/
│       ├── service.py          # Uses _get_logs_dir() -> logs/
│       └── grade_pdf_answer.py # Uses log_path parameter
└── logs/                       # ← Log files location
    ├── log.txt
    ├── errors_log.txt
    ├── jobs/
    ├── results/
    └── progress_*.json
```

---

## Accessing Log Files

### From Code

```python
from backend.ocr.service import _get_logs_dir

logs_dir = _get_logs_dir()
log_path = os.path.join(logs_dir, "log.txt")
ocr_log_path = os.path.join(logs_dir, "ocr_log.txt")
error_log_path = os.path.join(logs_dir, "errors_log.txt")
```

### From Command Line

**Windows**:
```cmd
type D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\log.txt
type D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\ocr_log.txt
type D:\Sova\Projects\RubrikAi\insightLLM_backend\logs\errors_log.txt
```

**Linux/Mac**:
```bash
cat /path/to/insightLLM_backend/logs/log.txt
cat /path/to/insightLLM_backend/logs/ocr_log.txt
cat /path/to/insightLLM_backend/logs/errors_log.txt
```

---

## Log File Management

### Automatic Creation

- Log files are created automatically when first log entry is written
- Directory is created if it doesn't exist (`os.makedirs(logs_dir, exist_ok=True)`)
- No manual setup required

### Log Rotation

**Current**: Logs append to files indefinitely (no rotation)

**Recommendation**: Implement log rotation for production:
- Rotate `log.txt` when it exceeds a certain size (e.g., 10MB)
- Keep last N rotated files (e.g., `log.txt.1`, `log.txt.2`, etc.)
- Same for `errors_log.txt`

### Cleanup

**Old Progress Files**: Automatically deleted 5 seconds after job completion

**Old Job Files**: Can be cleaned up using `OCRJobManager.cleanup_old_jobs()`

**Log Files**: Manual cleanup required (consider implementing automatic rotation)

---

## Troubleshooting

### Log Files Not Found

**Check**:
1. Verify `logs` directory exists at project root
2. Check file permissions (write access required)
3. Verify path calculation (use `_get_logs_dir()` function)

### Errors Not Appearing in `errors_log.txt`

**Check**:
1. Verify log level is "ERROR" (not "WARNING" or "INFO")
2. Check file permissions
3. Verify `_append_log()` function is being called with ERROR level

### Path Mismatch Issues

**Solution**: Both `routes/ocr.py` and `service.py` use `_get_logs_dir()` helper functions to ensure consistent path calculation.

---

## Summary

| File | Location | Contents | Size |
|------|----------|----------|------|
| `log.txt` | `insightLLM_backend/logs/log.txt` | All log levels | Can be large |
| `ocr_log.txt` | `insightLLM_backend/logs/ocr_log.txt` | OCR-related logs only | Typically smaller |
| `errors_log.txt` | `insightLLM_backend/logs/errors_log.txt` | ERROR level only | Typically smaller |

**Both files are in the same directory**: `insightLLM_backend/logs/`

---

**Last Updated**: December 2025

