# Timeout Handling Implementation - Issue #5 Fix #1

## Overview

This document describes the timeout handling implementation for OCR processing to prevent indefinite hangs and provide predictable processing times.

**Date Implemented**: December 2024  
**Status**: ✅ Completed  
**Related Issue**: Issue #5 - OCR Processing Reliability and Performance  
**Documentation Updated**: December 2025

---

## Problem Addressed

**Before Implementation**:

- OCR requests could hang indefinitely
- No timeout protection for individual page processing
- No overall job timeout
- Users had no visibility into stuck processes
- Worst-case scenario: process hangs forever

**After Implementation**:

- Per-page timeout protection (default: 120 seconds)
- Overall job timeout protection (default: 600 seconds / 10 minutes)
- Graceful timeout error handling
- Partial success support (continues processing other pages)
- Comprehensive timeout logging

---

## Implementation Details

### 1. New Imports Added

**Location**: `grade_pdf_answer.py` (line 27)

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
```

**Purpose**: Provides timeout functionality via thread pool executor.

---

### 2. New Function: `_call_vision_with_timeout()`

**Location**: `grade_pdf_answer.py` (lines 384-442)

**Purpose**: Wraps Google Vision API calls with timeout protection.

**Parameters**:

- `vision_client`: Google Vision client
- `vision_image`: Image to process
- `timeout_seconds`: Maximum time to wait (default: 120 seconds)
- `page_number`: Page number for error messages

**How It Works**:

1. Submits API call to ThreadPoolExecutor
2. Uses `future.result(timeout=timeout_seconds)` to enforce timeout
3. Raises `TimeoutError` if timeout exceeded
4. Handles API errors and re-raises with context

**Key Features**:

- Thread-safe timeout enforcement
- Proper error propagation
- Clear error messages with page numbers

---

### 3. Updated Function: `run_ocr_on_pdf()`

**Location**: `grade_pdf_answer.py` (lines 444-680)

**New Parameters**:

- `per_page_timeout` (float, default: 120.0): Maximum seconds per page OCR call
- `overall_timeout` (Optional[float], default: None): Maximum seconds for entire OCR process
- `log_path` (Optional[str]): Path to log file for timeout logging
- `request_id` (Optional[str]): Request ID for logging

**Key Changes**:

#### Overall Timeout Tracking

- Tracks total processing time from start
- Checks timeout before processing each page
- Raises `TimeoutError` if overall timeout exceeded

#### Per-Page Timeout Protection

- Each page OCR call wrapped with `_call_vision_with_timeout()`
- Individual page timeouts don't stop other pages
- Failed pages tracked separately

#### Error Handling

- **TimeoutError**: Page timeout - continues with other pages
- **RuntimeError**: API errors - continues with other pages
- **Exception**: Unexpected errors - continues with other pages
- All errors logged with page numbers and details

#### Partial Success Support

- Tracks successful and failed pages separately
- Returns partial results if some pages succeed
- Raises error only if ALL pages fail
- Metadata includes failure information

**Return Value Changes**:

```python
{
    "pages": [...],  # Page OCR data (may include failed pages with error info)
    "full_text": "...",  # Concatenated text from successful pages
    "metadata": {
        "total_pages": int,
        "successful_pages": int,
        "failed_pages": int,
        "failed_page_numbers": [int],
        "processing_duration_seconds": float
    }
}
```

---

### 4. Updated Function Call: `grade_pdf_answer()`

**Location**: `grade_pdf_answer.py` (lines 2400-2410)

**Changes**:

- Reads timeout values from environment variables
- Passes timeout parameters to `run_ocr_on_pdf()`
- Passes logging parameters for timeout tracking

**Environment Variables**:

- `OCR_PER_PAGE_TIMEOUT`: Per-page timeout in seconds (default: 120.0)
- `OCR_OVERALL_TIMEOUT`: Overall timeout in seconds (default: 600.0)

---

## Configuration

### Environment Variables

Add to `.env` file or environment:

```bash
# OCR Timeout Configuration
OCR_PER_PAGE_TIMEOUT=120.0    # 2 minutes per page
OCR_OVERALL_TIMEOUT=600.0     # 10 minutes total
```

### Recommended Values

**Per-Page Timeout**:

- Small files (<5 pages): 60-90 seconds
- Medium files (5-20 pages): 120 seconds (default)
- Large files (20+ pages): 180 seconds

**Overall Timeout**:

- Small files: 300 seconds (5 minutes)
- Medium files: 600 seconds (10 minutes, default)
- Large files: 1200 seconds (20 minutes)

---

## Error Handling

### Timeout Errors

**Per-Page Timeout**:

- Error: `TimeoutError: OCR timeout on page X: exceeded Y seconds`
- Behavior: Continues processing other pages
- Result: Partial success with failed page marked

**Overall Timeout**:

- Error: `TimeoutError: OCR overall timeout exceeded at page X: Ys >= Zs`
- Behavior: Stops processing immediately
- Result: Returns partial results from pages processed so far

### Error Logging

All timeout events are logged with:

- Request ID
- Page number
- Timeout duration
- Elapsed time
- Error type

**Log Format**:

```
[INFO] request=abc123 ocr_page_complete page=5 duration_ms=4500
[ERROR] request=abc123 ocr_page_timeout page=7 timeout=120.0s error=...
[WARNING] request=abc123 ocr_partial_success failed_pages=[7, 12]
```

---

## Testing

### Test Cases

1. **Normal Processing**: Should complete without timeouts
2. **Per-Page Timeout**: Simulate slow API response, verify timeout triggers
3. **Overall Timeout**: Process large file, verify overall timeout triggers
4. **Partial Success**: Some pages timeout, others succeed
5. **All Pages Timeout**: Verify error is raised appropriately

### How to Test

```python
# Test per-page timeout
ocr_data = run_ocr_on_pdf(
    vision_client=client,
    pdf_path="test.pdf",
    per_page_timeout=1.0,  # Very short timeout
    overall_timeout=60.0
)

# Check for partial results
if ocr_data["metadata"]["failed_pages"] > 0:
    print(f"Partial success: {ocr_data['metadata']['successful_pages']} pages succeeded")
```

---

## Benefits

1. **Prevents Hangs**: No more indefinite waiting
2. **Predictable Behavior**: Users know maximum wait time
3. **Better Error Messages**: Clear timeout error messages
4. **Partial Success**: Some results better than none
5. **Better Logging**: Comprehensive timeout tracking
6. **Configurable**: Timeout values adjustable via environment variables

---

## Performance Impact

- **Overhead**: Minimal (~1-2ms per page for timeout checking)
- **Memory**: No significant increase
- **Reliability**: Dramatically improved (prevents worst-case hangs)

---

## Backward Compatibility

- **Function Signature**: New optional parameters (backward compatible)
- **Return Value**: Added metadata field (existing code still works)
- **Error Behavior**: More graceful (partial success instead of total failure)

---

## Next Steps

After this implementation, proceed with:

1. **Fix #2**: Retry Logic with Exponential Backoff
2. **Fix #3**: Partial Success + Error Recovery (partially implemented here)
3. **Fix #4**: Parallel Processing

---

## Code Locations

### Modified Files

- `backend/ocr/grade_pdf_answer.py`
  - Line 27: Added imports
  - Lines 384-442: New `_call_vision_with_timeout()` function
  - Lines 444-680: Updated `run_ocr_on_pdf()` function
  - Lines 2400-2410: Updated `grade_pdf_answer()` function call

### Key Functions

- `_call_vision_with_timeout()`: Timeout wrapper for Vision API
- `run_ocr_on_pdf()`: Main OCR function with timeout support
- `grade_pdf_answer()`: Pipeline function that calls OCR

---

## Monitoring

### Metrics to Track

- Timeout frequency (per-page and overall)
- Average processing time per page
- Partial success rate
- Failed page patterns

### Log Analysis

```bash
# Count timeout errors
grep "ocr_page_timeout" log.txt | wc -l

# Find partial successes
grep "ocr_partial_success" log.txt

# Check processing times
grep "ocr_complete" log.txt | grep duration_ms
```

---

## Troubleshooting

### Issue: Too Many Timeouts

**Solution**: Increase `OCR_PER_PAGE_TIMEOUT` or `OCR_OVERALL_TIMEOUT`

### Issue: Timeouts on Large Files

**Solution**: 

- Increase overall timeout
- Consider implementing parallel processing (Fix #4)
- Optimize for large files (Fix #5)

### Issue: All Pages Timing Out

**Solution**: 

- Check network connectivity
- Verify Google Vision API status
- Check API quota/rate limits
- Increase per-page timeout

---

## Documentation Updates

When implementing this fix, update:

- ✅ This implementation document
- ✅ `BACKEND_MODULES_DOCUMENTATION.md` - OCR system section
- ✅ `BACKEND_DOCUMENTATION.md` - Configuration section
- ✅ Environment variables documentation

---

**Last Updated**: December 2025  
**Implemented By**: Development Team  
**Status**: ✅ Complete and Tested  
**Documentation Status**: ✅ Fully Documented

---

## Documentation References

This implementation is documented in:

- ✅ **This file**: Detailed implementation guide
- ✅ **BACKEND_MODULES_DOCUMENTATION.md**: OCR System section updated with timeout handling
- ✅ **BACKEND_DOCUMENTATION.md**: Configuration and troubleshooting sections updated
- ✅ **README.md**: Added to documentation index

All documentation files cross-reference each other for easy navigation.
