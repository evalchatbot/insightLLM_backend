# Section 2: Add Configuration Knobs - Implementation Summary

**Date Implemented**: December 2025  
**Status**: ✅ Completed  
**Section**: 2 of Retry Logic Implementation Guide

---

## What Was Implemented

### 1. Environment Variables Added

Added 6 new environment variables for retry configuration:

| Variable                    | Default | Description                                                                             |
| --------------------------- | ------- | --------------------------------------------------------------------------------------- |
| `OCR_MAX_RETRIES`           | `3`     | Maximum retry attempts per page                                                         |
| `OCR_RETRY_BASE_DELAY`      | `1.0`   | Base delay in seconds for exponential backoff                                           |
| `OCR_RETRY_MAX_DELAY`       | `60.0`  | Maximum delay in seconds between retries                                                |
| `OCR_RETRY_JITTER_RANGE`    | `0.2`   | Jitter range (0.0-1.0) for backoff randomization                                        |
| `OCR_RATE_LIMIT_BASE_DELAY` | `5.0`   | Base delay in seconds for rate limit backoff                                            |
| `OCR_RATE_LIMIT_MAX_DELAY`  | `300.0` | Maximum delay in seconds for rate limit backoff (5 minutes) |

### 2. Configuration Loading

**Location 1**: `backend/config.py` (lines 26-31)

- Added centralized configuration loading
- Follows same pattern as other config variables
- Available for import across the codebase

**Location 2**: `backend/ocr/grade_pdf_answer.py` (lines 2611-2616)

- Added configuration loading in `grade_pdf_answer()` function
- Loads from environment variables with defaults
- Passes to `run_ocr_on_pdf()` function

### 3. Function Signature Updates

**Updated Function**: `run_ocr_on_pdf()` in `grade_pdf_answer.py`

**Added Parameters**:

- `max_retries: int = 3`
- `retry_base_delay: float = 1.0`
- `retry_max_delay: float = 60.0`
- `retry_jitter_range: float = 0.2`
- `rate_limit_base_delay: float = 5.0`
- `rate_limit_max_delay: float = 300.0`

**Updated Documentation**: Function docstring now includes all retry parameters with descriptions.

---

## Code Changes

### File: `backend/config.py`

```python
# OCR Retry Configuration
OCR_MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "3"))
OCR_RETRY_BASE_DELAY = float(os.getenv("OCR_RETRY_BASE_DELAY", "1.0"))
OCR_RETRY_MAX_DELAY = float(os.getenv("OCR_RETRY_MAX_DELAY", "60.0"))
OCR_RETRY_JITTER_RANGE = float(os.getenv("OCR_RETRY_JITTER_RANGE", "0.2"))
OCR_RATE_LIMIT_BASE_DELAY = float(os.getenv("OCR_RATE_LIMIT_BASE_DELAY", "5.0"))
OCR_RATE_LIMIT_MAX_DELAY = float(os.getenv("OCR_RATE_LIMIT_MAX_DELAY", "300.0"))
```

### File: `backend/ocr/grade_pdf_answer.py`

**Configuration Loading** (lines 2611-2616):

```python
# Configure retry parameters (for retry logic implementation)
max_retries = int(os.getenv("OCR_MAX_RETRIES", "3"))
retry_base_delay = float(os.getenv("OCR_RETRY_BASE_DELAY", "1.0"))
retry_max_delay = float(os.getenv("OCR_RETRY_MAX_DELAY", "60.0"))
retry_jitter_range = float(os.getenv("OCR_RETRY_JITTER_RANGE", "0.2"))
rate_limit_base_delay = float(os.getenv("OCR_RATE_LIMIT_BASE_DELAY", "5.0"))
rate_limit_max_delay = float(os.getenv("OCR_RATE_LIMIT_MAX_DELAY", "300.0"))
```

**Function Call Update** (lines 2623-2632):

```python
ocr_data = run_ocr_on_pdf(
    vision_client=vision_client,
    pdf_path=pdf_path,
    per_page_timeout=per_page_timeout,
    overall_timeout=overall_timeout,
    log_path=log_path,
    request_id=request_id,
    max_retries=max_retries,
    retry_base_delay=retry_base_delay,
    retry_max_delay=retry_max_delay,
    retry_jitter_range=retry_jitter_range,
    rate_limit_base_delay=rate_limit_base_delay,
    rate_limit_max_delay=rate_limit_max_delay,
)
```

**Function Signature Update** (lines 440-450):

```python
def run_ocr_on_pdf(
    vision_client: vision.ImageAnnotatorClient,
    pdf_path: str,
    per_page_timeout: float = 120.0,
    overall_timeout: Optional[float] = None,
    log_path: Optional[str] = None,
    request_id: Optional[str] = None,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter_range: float = 0.2,
    rate_limit_base_delay: float = 5.0,
    rate_limit_max_delay: float = 300.0,
) -> Dict[str, Any]:
```

---

## Usage

### Setting Environment Variables

Add to `.env` file:

```bash
# OCR Retry Configuration
OCR_MAX_RETRIES=3
OCR_RETRY_BASE_DELAY=1.0
OCR_RETRY_MAX_DELAY=60.0
OCR_RETRY_JITTER_RANGE=0.2
OCR_RATE_LIMIT_BASE_DELAY=5.0
OCR_RATE_LIMIT_MAX_DELAY=300.0
```

### Using Configuration

**Option 1**: Import from `config.py`

```python
from backend.config import OCR_MAX_RETRIES, OCR_RETRY_BASE_DELAY
```

**Option 2**: Use in `grade_pdf_answer()` (already implemented)

- Configuration is loaded and passed to `run_ocr_on_pdf()`
- Parameters are available for retry logic implementation

---

## Next Steps

The configuration is now in place and ready for use. Next implementation steps:

1. **Section 3**: Implement Error Classification
   
   - Use `max_retries` parameter
   - Classify errors as retryable/non-retryable

2. **Section 4**: Implement Backoff Calculation
   
   - Use `retry_base_delay`, `retry_max_delay`, `retry_jitter_range`
   - Use `rate_limit_base_delay`, `rate_limit_max_delay` for rate limits

3. **Section 6**: Build Retry Wrapper
   
   - Use all retry parameters
   - Implement retry loop with backoff

---

## Testing

### Configuration Loading Test

To verify configuration is loaded correctly:

```python
# Test in Python console
import os
from dotenv import load_dotenv
load_dotenv()

print(f"OCR_MAX_RETRIES: {os.getenv('OCR_MAX_RETRIES', '3')}")
print(f"OCR_RETRY_BASE_DELAY: {os.getenv('OCR_RETRY_BASE_DELAY', '1.0')}")
# ... etc
```

### Function Parameter Test

The function signature accepts all parameters with defaults, so existing code continues to work without changes.

---

## Backward Compatibility

✅ **Fully Backward Compatible**

- All new parameters have default values
- Existing code calling `run_ocr_on_pdf()` continues to work
- No breaking changes
- Configuration is optional (uses defaults if not set)

---

## Documentation Updates

- ✅ Configuration variables documented in `RETRY_POLICY.md`
- ✅ Function signatures updated with docstrings
- ✅ Default values match policy document

---

**Last Updated**: December 2025  
**Status**: ✅ Completed  
**Next Section**: Section 3 - Implement Error Classification
