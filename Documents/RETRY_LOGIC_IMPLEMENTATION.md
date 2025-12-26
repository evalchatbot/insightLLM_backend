# Retry Logic with Exponential Backoff - Issue #5 Fix #2

## Overview

This document describes the retry logic with exponential backoff implementation plan for OCR processing to handle transient failures gracefully and improve overall reliability.

**Date Planned**: December 2025  
**Status**: 📋 Planning  
**Related Issue**: Issue #5 - OCR Processing Reliability and Performance  
**Prerequisite**: Timeout Handling (Fix #1) - ✅ Completed

---

## Problem Addressed

### Current Situation

**After Timeout Handling Implementation**:
- ✅ Timeouts prevent indefinite hangs
- ✅ Partial success support exists
- ❌ **No retry mechanism for transient failures**
- ❌ **Immediate failure on first error**
- ❌ **No recovery from temporary network issues**
- ❌ **No handling of rate limit errors (429)**
- ❌ **No recovery from temporary API errors (5xx)**

### Problem Statement

**What Happens Now**:
1. Google Vision API call fails (network glitch, rate limit, temporary 5xx error)
2. Function immediately raises error
3. Page marked as failed
4. Processing continues to next page
5. **Result**: Unnecessary failures that could have been recovered

**Real-World Scenarios**:
- **Network hiccup**: 1-second network interruption → Page fails → Should retry
- **Rate limit (429)**: Too many requests → Immediate failure → Should wait and retry
- **Temporary API error (503)**: Service temporarily unavailable → Should retry
- **Timeout on slow response**: Legitimate slow response → Should retry with longer timeout
- **Connection reset**: Network connection dropped → Should retry

**Impact**:
- **High failure rate**: Many failures are transient and recoverable
- **Wasted API quota**: Failed requests still count against quota
- **Poor user experience**: Users see failures that could have succeeded
- **Unnecessary partial results**: Pages fail that could have been processed

---

## Where Retries Are Needed

### Primary Location: `_call_vision_with_timeout()`

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `_call_vision_with_timeout()` (lines 384-442)  
**Current Behavior**: Single attempt, immediate failure on error

**What Needs Retry**:
- Google Vision API call failures
- Network errors
- Rate limit responses (429)
- Temporary API errors (5xx)
- Connection timeouts

### Secondary Location: `run_ocr_on_pdf()`

**File**: `backend/ocr/grade_pdf_answer.py`  
**Function**: `run_ocr_on_pdf()` (lines 440-680)  
**Current Behavior**: Calls `_call_vision_with_timeout()` once per page

**What Needs Retry**:
- Failed page processing (after per-page retries exhausted)
- Overall job recovery (optional, for critical failures)

---

## Solution Overview

### Retry Strategy

**Core Principle**: Retry transient failures, fail fast on permanent errors

**Retryable Errors**:
- ✅ Network errors (connection reset, timeout, DNS failure)
- ✅ Rate limit errors (429 Too Many Requests)
- ✅ Temporary server errors (500, 502, 503, 504)
- ✅ Timeout errors (if within retry budget)
- ✅ Service unavailable (503)

**Non-Retryable Errors**:
- ❌ Authentication errors (401, 403)
- ❌ Invalid request errors (400, 422)
- ❌ Resource not found (404)
- ❌ Permanent API errors (deterministic failures)
- ❌ Invalid image format errors

### Exponential Backoff Strategy

**Backoff Formula**: `wait_time = base_delay * (2 ^ attempt_number) + jitter`

**Parameters**:
- **Base delay**: Initial wait time (e.g., 1 second)
- **Max delay**: Maximum wait time between retries (e.g., 60 seconds)
- **Max attempts**: Maximum number of retry attempts (e.g., 3-5)
- **Jitter**: Random variation to prevent thundering herd (e.g., ±20%)

**Example Backoff Sequence** (base=1s, max=60s, max_attempts=5):
- Attempt 1: Immediate (no wait)
- Attempt 2: Wait ~1-2 seconds (1s * 2^1 + jitter)
- Attempt 3: Wait ~2-4 seconds (1s * 2^2 + jitter)
- Attempt 4: Wait ~4-8 seconds (1s * 2^3 + jitter)
- Attempt 5: Wait ~8-16 seconds (1s * 2^4 + jitter, capped at 60s)

---

## Detailed Solutions

### Solution 1: Retry Wrapper Function

**Location**: `backend/ocr/grade_pdf_answer.py`  
**New Function**: `_call_vision_with_retry()`

**Purpose**: Wrap Vision API calls with retry logic and exponential backoff

**Function Signature**:
```
_call_vision_with_retry(
    vision_client: vision.ImageAnnotatorClient,
    vision_image: vision.Image,
    timeout_seconds: float,
    page_number: int,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    log_path: Optional[str] = None,
    request_id: Optional[str] = None
) -> vision.AnnotateImageResponse
```

**Behavior**:
1. Attempt Vision API call via `_call_vision_with_timeout()`
2. On failure, check if error is retryable
3. If retryable and attempts remaining:
   - Calculate backoff delay
   - Log retry attempt
   - Wait for backoff period
   - Retry the call
4. If non-retryable or max attempts reached:
   - Log final failure
   - Raise error with context

**Error Classification**:
- Parse error type from exception
- Check HTTP status codes (if available)
- Check error messages for patterns
- Classify as retryable or non-retryable

**Logging**:
- Log each retry attempt with:
  - Attempt number
  - Error type
  - Wait time
  - Page number
  - Request ID

---

### Solution 2: Error Classification System

**Location**: `backend/ocr/grade_pdf_answer.py`  
**New Function**: `_is_retryable_error()`

**Purpose**: Determine if an error should be retried

**Function Signature**:
```
_is_retryable_error(
    error: Exception,
    response: Optional[vision.AnnotateImageResponse] = None
) -> bool
```

**Classification Logic**:

**Retryable**:
- `TimeoutError`: Transient timeout (within retry budget)
- `ConnectionError`: Network connection issues
- `HTTPError` with status 429: Rate limit
- `HTTPError` with status 500-504: Server errors
- `ServiceUnavailable`: Service temporarily unavailable
- Generic `Exception` with timeout-related messages

**Non-Retryable**:
- `HTTPError` with status 400, 401, 403, 404, 422: Client errors
- `ValueError`: Invalid input (won't succeed on retry)
- `RuntimeError` with API error messages (check content)
- Authentication/permission errors

**Response Error Checking**:
- Check `response.error.message` for specific error codes
- Google Vision API error codes:
  - Retryable: `DEADLINE_EXCEEDED`, `UNAVAILABLE`, `RESOURCE_EXHAUSTED` (rate limit)
  - Non-retryable: `INVALID_ARGUMENT`, `PERMISSION_DENIED`, `NOT_FOUND`

---

### Solution 3: Exponential Backoff Calculator

**Location**: `backend/ocr/grade_pdf_answer.py`  
**New Function**: `_calculate_backoff_delay()`

**Purpose**: Calculate wait time with exponential backoff and jitter

**Function Signature**:
```
_calculate_backoff_delay(
    attempt_number: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_range: float = 0.2
) -> float
```

**Calculation**:
1. Calculate exponential delay: `base_delay * (2 ^ (attempt_number - 1))`
2. Cap at `max_delay`
3. Add jitter: Random variation of ±`jitter_range` (e.g., ±20%)
4. Return final delay in seconds

**Example**:
- Attempt 2: `1.0 * 2^1 = 2.0s` → With jitter: `1.6-2.4s`
- Attempt 3: `1.0 * 2^2 = 4.0s` → With jitter: `3.2-4.8s`
- Attempt 4: `1.0 * 2^3 = 8.0s` → With jitter: `6.4-9.6s`
- Attempt 5: `1.0 * 2^4 = 16.0s` → Capped at 60s → With jitter: `48-60s`

---

### Solution 4: Rate Limit Special Handling

**Location**: `backend/ocr/grade_pdf_answer.py`  
**Enhancement**: Special handling for 429 Rate Limit errors

**Purpose**: Handle rate limits with longer backoff and respect Retry-After headers

**Behavior**:
1. Detect 429 Rate Limit error
2. Check for `Retry-After` header in response
3. If `Retry-After` present:
   - Use header value as wait time (respect server's request)
   - Log rate limit with wait time
4. If no `Retry-After`:
   - Use longer exponential backoff (e.g., 2x normal)
   - Log rate limit without specific wait time
5. Wait and retry

**Configuration**:
- `RATE_LIMIT_BASE_DELAY`: Base delay for rate limits (default: 5.0 seconds)
- `RATE_LIMIT_MAX_DELAY`: Max delay for rate limits (default: 300 seconds / 5 minutes)

---

### Solution 5: Retry Budget Management

**Location**: `backend/ocr/grade_pdf_answer.py`  
**Enhancement**: Track retry time against overall timeout

**Purpose**: Ensure retries don't exceed overall timeout budget

**Behavior**:
1. Track total time spent on retries
2. Before each retry:
   - Check if retry would exceed overall timeout
   - If yes, fail immediately (don't waste time)
3. Adjust per-page timeout for retries:
   - Reduce timeout per attempt to account for retries
   - Example: 120s timeout, 3 retries → ~30s per attempt

**Calculation**:
- `timeout_per_attempt = per_page_timeout / (max_retries + 1)`
- Track: `total_retry_time = sum(backoff_delays) + sum(attempt_durations)`
- Check: `total_retry_time < (overall_timeout - elapsed_time)`

---

### Solution 6: Configuration via Environment Variables

**Location**: `backend/config.py` or `grade_pdf_answer.py`  
**Purpose**: Make retry behavior configurable

**New Environment Variables**:
```bash
# Retry Configuration
OCR_MAX_RETRIES=3                    # Maximum retry attempts per page
OCR_RETRY_BASE_DELAY=1.0             # Base delay in seconds
OCR_RETRY_MAX_DELAY=60.0              # Maximum delay in seconds
OCR_RETRY_JITTER_RANGE=0.2            # Jitter range (0.0-1.0)
OCR_RATE_LIMIT_BASE_DELAY=5.0        # Base delay for rate limits
OCR_RATE_LIMIT_MAX_DELAY=300.0       # Max delay for rate limits
```

**Default Values**:
- `OCR_MAX_RETRIES`: 3 (small files), 5 (large files)
- `OCR_RETRY_BASE_DELAY`: 1.0 seconds
- `OCR_RETRY_MAX_DELAY`: 60.0 seconds
- `OCR_RETRY_JITTER_RANGE`: 0.2 (20% variation)
- `OCR_RATE_LIMIT_BASE_DELAY`: 5.0 seconds
- `OCR_RATE_LIMIT_MAX_DELAY`: 300.0 seconds (5 minutes)

---

### Solution 7: Enhanced Logging

**Location**: `backend/ocr/grade_pdf_answer.py`  
**Enhancement**: Comprehensive retry logging

**Log Events**:
1. **Retry Attempt**:
   ```
   [INFO] request=abc123 ocr_retry_attempt page=5 attempt=2/3 error=TimeoutError wait_s=2.1
   ```

2. **Retry Success**:
   ```
   [INFO] request=abc123 ocr_retry_success page=5 attempt=2/3 total_attempts=2 duration_ms=4500
   ```

3. **Retry Exhausted**:
   ```
   [ERROR] request=abc123 ocr_retry_exhausted page=5 attempts=3 error=TimeoutError
   ```

4. **Rate Limit Detected**:
   ```
   [WARNING] request=abc123 ocr_rate_limit page=5 retry_after_s=30 wait_s=30.0
   ```

5. **Non-Retryable Error**:
   ```
   [ERROR] request=abc123 ocr_non_retryable page=5 error=PermissionDenied
   ```

**Logging Details**:
- Request ID for tracing
- Page number
- Attempt number (current/max)
- Error type and message
- Wait time before retry
- Total attempts made
- Success/failure outcome

---

### Solution 8: Integration with Existing Timeout System

**Location**: `backend/ocr/grade_pdf_answer.py`  
**Enhancement**: Integrate retries with timeout handling

**Integration Points**:
1. **Per-Page Timeout**: Each retry attempt respects per-page timeout
2. **Overall Timeout**: Retries don't exceed overall timeout budget
3. **Timeout Errors**: Timeout errors are retryable (transient)
4. **Timeout Calculation**: Adjust timeout per attempt to account for retries

**Flow**:
```
Page Processing Start
    ↓
Attempt 1 → Timeout (120s) → Retryable? Yes → Wait (backoff)
    ↓
Attempt 2 → Success → Continue to next page
```

**Timeout Adjustment**:
- If `max_retries=3` and `per_page_timeout=120s`:
  - Each attempt gets ~30s timeout
  - Total time budget: 120s + retry delays
  - Prevents single slow attempt from consuming all time

---

## Implementation Strategy

### Phase 1: Core Retry Logic
1. Create `_is_retryable_error()` function
2. Create `_calculate_backoff_delay()` function
3. Create `_call_vision_with_retry()` function
4. Add basic error classification

### Phase 2: Enhanced Features
1. Add rate limit special handling
2. Add retry budget management
3. Add comprehensive logging
4. Add configuration via environment variables

### Phase 3: Integration
1. Integrate with `_call_vision_with_timeout()`
2. Update `run_ocr_on_pdf()` to use retry wrapper
3. Test with various error scenarios
4. Update documentation

### Phase 4: Optimization
1. Fine-tune backoff parameters
2. Optimize timeout calculations
3. Add metrics tracking
4. Performance testing

---

## Expected Outcomes

### Before Retry Logic
- **Failure Rate**: ~15-20% of pages fail on first attempt
- **Recovery**: 0% (no retries)
- **User Experience**: Many unnecessary failures
- **API Efficiency**: Wasted quota on transient failures

### After Retry Logic
- **Failure Rate**: ~5-10% (only permanent failures)
- **Recovery**: ~50-70% of transient failures recovered
- **User Experience**: Fewer failures, better success rate
- **API Efficiency**: Better quota utilization

### Metrics to Track
- Retry success rate (attempts that succeed after retry)
- Average retry attempts per page
- Retry delay distribution
- Rate limit frequency
- Overall page success rate improvement

---

## Configuration Recommendations

### Small Files (<5 pages)
```bash
OCR_MAX_RETRIES=3
OCR_RETRY_BASE_DELAY=1.0
OCR_RETRY_MAX_DELAY=30.0
```

### Medium Files (5-20 pages)
```bash
OCR_MAX_RETRIES=3
OCR_RETRY_BASE_DELAY=1.0
OCR_RETRY_MAX_DELAY=60.0
```

### Large Files (20+ pages)
```bash
OCR_MAX_RETRIES=5
OCR_RETRY_BASE_DELAY=2.0
OCR_RETRY_MAX_DELAY=120.0
```

---

## Testing Strategy

### Test Cases

1. **Transient Network Error**:
   - Simulate connection reset
   - Verify retry succeeds on second attempt
   - Verify backoff delay applied

2. **Rate Limit (429)**:
   - Simulate rate limit response
   - Verify longer backoff delay
   - Verify Retry-After header respected

3. **Temporary API Error (503)**:
   - Simulate service unavailable
   - Verify retry succeeds
   - Verify exponential backoff

4. **Timeout with Retry**:
   - First attempt times out
   - Verify retry with same timeout
   - Verify success on retry

5. **Non-Retryable Error**:
   - Simulate authentication error (401)
   - Verify no retry attempted
   - Verify immediate failure

6. **Max Retries Exhausted**:
   - Simulate persistent failure
   - Verify all retries attempted
   - Verify final failure after max retries

7. **Retry Budget Exceeded**:
   - Simulate retries that would exceed overall timeout
   - Verify early failure
   - Verify partial results returned

---

## Dependencies

### Required
- ✅ Timeout Handling (Fix #1) - Already implemented
- Python `time` module (for sleep/delays)
- Python `random` module (for jitter)
- Python `logging` (for retry logging)

### Optional
- `tenacity` library (advanced retry library, if preferred over custom implementation)
- Metrics tracking system (for monitoring retry success rates)

---

## Risks and Considerations

### Risk 1: Increased Processing Time
**Mitigation**: 
- Cap max retries
- Respect overall timeout budget
- Use exponential backoff to limit total delay

### Risk 2: API Quota Consumption
**Mitigation**:
- Only retry transient failures
- Don't retry on permanent errors
- Track retry attempts for monitoring

### Risk 3: Thundering Herd
**Mitigation**:
- Use jitter in backoff delays
- Randomize retry timing
- Respect rate limit responses

### Risk 4: Infinite Retries
**Mitigation**:
- Hard limit on max retries
- Overall timeout enforcement
- Retry budget tracking

---

## Next Steps After Implementation

1. **Fix #3**: Partial Success + Error Recovery (enhance existing)
2. **Fix #4**: Parallel Processing (will need retry coordination)
3. **Fix #5**: Large File Optimizations (retries for chunked processing)

---

## Code Locations

### Files to Modify
- `backend/ocr/grade_pdf_answer.py`
  - Add retry functions
  - Update `_call_vision_with_timeout()` or create wrapper
  - Update `run_ocr_on_pdf()` to use retries

### New Functions
- `_is_retryable_error()`: Error classification
- `_calculate_backoff_delay()`: Backoff calculation
- `_call_vision_with_retry()`: Retry wrapper

### Configuration
- `backend/config.py`: Add retry configuration variables
- `.env`: Add retry environment variables

---

## Documentation Updates Needed

After implementation, update:
- ✅ This implementation document (mark as completed)
- `BACKEND_MODULES_DOCUMENTATION.md` - OCR System section
- `BACKEND_DOCUMENTATION.md` - Configuration section
- `TIMEOUT_HANDLING_IMPLEMENTATION.md` - Add retry integration notes

---

**Last Updated**: December 2025  
**Status**: 📋 Planning  
**Next Review**: After implementation begins

---

## References

- [Timeout Handling Implementation](./TIMEOUT_HANDLING_IMPLEMENTATION.md) - Prerequisite
- [Issue #5 Solutions](./OCR_RELIABILITY_STEP_BY_STEP.md) - Overall reliability plan
- Google Cloud Vision API Error Codes: [Documentation](https://cloud.google.com/vision/docs/error-codes)
- Exponential Backoff Best Practices: Industry standard for API retries

