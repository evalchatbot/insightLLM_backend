# OCR Retry Policy - Official Definition

**Date Created**: December 2025  
**Status**: ✅ Approved  
**Related**: Issue #5 Fix #2 - Retry Logic Implementation  
**Prerequisite**: Timeout Handling (Fix #1) - ✅ Completed

---

## Overview

This document defines the official retry policy for OCR processing. It specifies which errors should be retried, how many times, with what delays, and what happens when retries are exhausted.

**Goal**: Recover from transient Vision/OCR failures (rate limits, temporary 5xx, network hiccups, timeouts) while **avoiding** retries for permanent errors, and ensuring retries don't exceed the **overall job timeout**.

---

## 1. Retryable vs Non-Retryable Error Rules

### 1.1 Retryable Errors (Will Retry)

These errors are **transient** and likely to succeed on retry:

#### Network/Connection Errors
- ✅ **ConnectionError**: Network connection issues
- ✅ **ConnectionResetError**: Connection was reset
- ✅ **TimeoutError**: Request timeout (within retry budget)
- ✅ **DNS resolution failures**: Temporary DNS issues
- ✅ **Socket errors**: Temporary network problems

**Rationale**: Network issues are typically transient and recover quickly.

#### Rate Limit Errors
- ✅ **HTTP 429 (Too Many Requests)**: Rate limit exceeded
- ✅ **Google Vision API error code: RESOURCE_EXHAUSTED**: Quota/rate limit
- ✅ **Rate limit error messages**: Any error containing "rate limit", "quota", "429"

**Rationale**: Rate limits are temporary; waiting and retrying usually succeeds.

**Special Handling**: Use longer backoff delays (see Section 2.2)

#### Temporary Server Errors
- ✅ **HTTP 500 (Internal Server Error)**: Server-side error
- ✅ **HTTP 502 (Bad Gateway)**: Gateway error
- ✅ **HTTP 503 (Service Unavailable)**: Service temporarily unavailable
- ✅ **HTTP 504 (Gateway Timeout)**: Gateway timeout
- ✅ **Google Vision API error code: UNAVAILABLE**: Service unavailable
- ✅ **Google Vision API error code: DEADLINE_EXCEEDED**: Request deadline exceeded

**Rationale**: Server errors are often transient and resolve quickly.

#### Timeout Errors (Conditional)
- ✅ **TimeoutError**: If within retry budget and overall timeout allows
- ✅ **Deadline exceeded**: If retry budget permits

**Rationale**: Some timeouts are due to temporary slowness, not permanent issues.

**Condition**: Only retry if:
- Remaining retry budget > (backoff_delay + estimated_attempt_time)
- Overall timeout budget allows

---

### 1.2 Non-Retryable Errors (Fail Fast)

These errors are **permanent** and won't succeed on retry:

#### Authentication/Permission Errors
- ❌ **HTTP 401 (Unauthorized)**: Invalid or missing credentials
- ❌ **HTTP 403 (Forbidden)**: Permission denied
- ❌ **Google Vision API error code: PERMISSION_DENIED**: Access denied
- ❌ **Authentication error messages**: Any error containing "auth", "permission", "unauthorized", "forbidden"

**Rationale**: Authentication issues won't resolve without credential changes.

#### Invalid Request Errors
- ❌ **HTTP 400 (Bad Request)**: Invalid request format
- ❌ **HTTP 422 (Unprocessable Entity)**: Invalid input data
- ❌ **Google Vision API error code: INVALID_ARGUMENT**: Invalid request
- ❌ **Google Vision API error code: INVALID_IMAGE**: Invalid image format
- ❌ **ValueError**: Invalid input (deterministic failure)

**Rationale**: Invalid requests won't succeed without fixing the input.

#### Resource Not Found
- ❌ **HTTP 404 (Not Found)**: Resource doesn't exist
- ❌ **Google Vision API error code: NOT_FOUND**: Resource not found

**Rationale**: Missing resources won't appear on retry.

#### Deterministic Failures
- ❌ **Invalid image format errors**: Image format not supported
- ❌ **File corruption errors**: Corrupted PDF/image
- ❌ **Size limit errors**: File too large (permanent)
- ❌ **Format errors**: Unsupported format (permanent)

**Rationale**: These are permanent issues that require input changes.

---

## 2. Default Retry Parameters

### 2.1 Standard Retry Parameters

**Per-Page Retry Settings**:

| Parameter | Default Value | Description |
|-----------|--------------|-------------|
| `OCR_MAX_RETRIES` | `3` | Maximum retry attempts per page |
| `OCR_RETRY_BASE_DELAY` | `1.0` seconds | Initial backoff delay |
| `OCR_RETRY_MAX_DELAY` | `60.0` seconds | Maximum backoff delay |
| `OCR_RETRY_JITTER_RANGE` | `0.2` (20%) | Random jitter variation |

**Backoff Sequence** (with defaults):
- Attempt 1: Immediate (no wait)
- Attempt 2: Wait ~1-2 seconds (1.0s * 2^1 ± 20%)
- Attempt 3: Wait ~2-4 seconds (1.0s * 2^2 ± 20%)
- Attempt 4: Wait ~4-8 seconds (1.0s * 2^3 ± 20%, capped at 60s)

### 2.2 Rate Limit Special Parameters

**Rate Limit Retry Settings**:

| Parameter | Default Value | Description |
|-----------|--------------|-------------|
| `OCR_RATE_LIMIT_BASE_DELAY` | `5.0` seconds | Base delay for rate limits |
| `OCR_RATE_LIMIT_MAX_DELAY` | `300.0` seconds (5 min) | Maximum delay for rate limits |

**Rate Limit Backoff Sequence**:
- Attempt 1: Immediate (no wait)
- Attempt 2: Wait ~5-10 seconds (5.0s * 2^1 ± 20%)
- Attempt 3: Wait ~10-20 seconds (5.0s * 2^2 ± 20%)
- Attempt 4: Wait ~20-40 seconds (5.0s * 2^3 ± 20%)
- Attempt 5: Wait ~40-80 seconds (5.0s * 2^4 ± 20%, capped at 300s)

**Retry-After Header**: If Google Vision API returns `Retry-After` header, use that value instead of calculated backoff.

### 2.3 Environment-Specific Defaults

**Development Environment**:
- `OCR_MAX_RETRIES=2` (fewer retries for faster feedback)
- `OCR_RETRY_BASE_DELAY=0.5` seconds (shorter delays)
- `OCR_RETRY_MAX_DELAY=30.0` seconds

**Production Environment**:
- `OCR_MAX_RETRIES=3` (standard)
- `OCR_RETRY_BASE_DELAY=1.0` seconds (standard)
- `OCR_RETRY_MAX_DELAY=60.0` seconds (standard)

**Large File Mode** (optional, for 20+ page PDFs):
- `OCR_MAX_RETRIES=5` (more retries for large files)
- `OCR_RETRY_BASE_DELAY=2.0` seconds (slightly longer base delay)

---

## 3. Outcome Behavior

### 3.1 Per-Page Retry Outcomes

**Scenario 1: Retry Succeeds**
- Page processed successfully after retry
- Mark page as **successful**
- Continue to next page
- Log retry success with attempt count

**Scenario 2: Retries Exhausted (Page Fails)**
- All retry attempts failed
- Mark page as **failed** with error details
- Continue processing other pages (partial success)
- Log retry exhaustion with error type

**Scenario 3: Non-Retryable Error**
- Error classified as non-retryable
- **Fail fast** (no retries attempted)
- Mark page as **failed** with error category
- Continue processing other pages (partial success)
- Log non-retryable error

**Scenario 4: Retry Budget Exceeded**
- Retry would exceed overall timeout budget
- Stop retrying early
- Mark page as **failed** with "timeout_budget_exceeded"
- Continue processing other pages (partial success)
- Log budget exceeded warning

### 3.2 Overall Job Outcomes

**Scenario 1: All Pages Succeed**
- **Outcome**: `SUCCESS`
- All pages processed successfully
- Return complete OCR data
- No failed pages

**Scenario 2: Some Pages Fail (Partial Success)**
- **Outcome**: `PARTIAL_SUCCESS`
- Some pages succeeded, some failed
- Return partial OCR data with metadata
- Include `failed_page_numbers` in metadata
- Log partial success warning
- **User-facing**: Show success with warning about failed pages

**Scenario 3: All Pages Fail**
- **Outcome**: `FAILED`
- All pages failed (retries exhausted or non-retryable errors)
- Raise error with details
- Return error message with failure reasons
- **User-facing**: Show error with actionable message

### 3.3 Metadata Structure

**Return Value Enhancement**:
```python
{
    "pages": [...],  # Page OCR data
    "full_text": "...",  # Concatenated text
    "metadata": {
        "total_pages": int,
        "successful_pages": int,
        "failed_pages": int,
        "failed_page_numbers": [int],
        "processing_duration_seconds": float,
        "outcome": "SUCCESS" | "PARTIAL_SUCCESS" | "FAILED",
        "retry_stats": {
            "total_retry_attempts": int,
            "successful_retries": int,
            "exhausted_retries": int,
            "rate_limit_events": int,
            "non_retryable_errors": int
        }
    }
}
```

---

## 4. Retry Budget Management

### 4.1 Budget Rules

**Overall Timeout Budget**:
- Total time for OCR processing (default: 600s, configurable to 1200s)
- Includes: page processing + retries + backoff delays

**Per-Page Timeout Budget**:
- Time allocated per page (default: 120s)
- Each retry attempt uses portion of this budget

**Retry Budget Check**:
Before each retry:
1. Calculate remaining overall timeout: `remaining = overall_timeout - elapsed_time`
2. Estimate retry cost: `backoff_delay + estimated_attempt_time`
3. If `retry_cost > remaining`: Stop retrying, mark page failed
4. Otherwise: Proceed with retry

### 4.2 Per-Attempt Timeout Strategy

**Chosen Strategy**: **Option A - Fixed Per-Attempt Timeout**

- Each retry attempt gets the same timeout as the original attempt
- Simpler to implement and reason about
- Less risk of timeout calculation errors
- Overall timeout budget still enforced

**Alternative (Not Chosen)**: Option B - Split Timeout
- Would divide per-page timeout across attempts
- More complex, higher risk of errors
- Not needed if overall timeout is properly enforced

---

## 5. Error Classification Table

### 5.1 Quick Reference

| Error Type | Retryable? | Category | Max Retries | Special Handling |
|------------|-----------|----------|-------------|------------------|
| ConnectionError | ✅ Yes | `network_error` | 3 | Standard backoff |
| TimeoutError | ✅ Yes* | `timeout` | 3 | Check budget |
| HTTP 429 | ✅ Yes | `rate_limit` | 3 | Long backoff |
| HTTP 500-504 | ✅ Yes | `server_error` | 3 | Standard backoff |
| RESOURCE_EXHAUSTED | ✅ Yes | `rate_limit` | 3 | Long backoff |
| UNAVAILABLE | ✅ Yes | `server_error` | 3 | Standard backoff |
| DEADLINE_EXCEEDED | ✅ Yes* | `timeout` | 3 | Check budget |
| HTTP 401/403 | ❌ No | `auth_error` | 0 | Fail fast |
| HTTP 400/422 | ❌ No | `invalid_input` | 0 | Fail fast |
| HTTP 404 | ❌ No | `not_found` | 0 | Fail fast |
| INVALID_ARGUMENT | ❌ No | `invalid_input` | 0 | Fail fast |
| PERMISSION_DENIED | ❌ No | `auth_error` | 0 | Fail fast |

*Conditional: Only if retry budget allows

### 5.2 Error Message Patterns

**Retryable Patterns** (case-insensitive):
- "timeout", "deadline exceeded", "timed out"
- "rate limit", "quota", "429", "resource exhausted"
- "unavailable", "503", "502", "500", "504"
- "connection", "network", "dns", "socket"

**Non-Retryable Patterns** (case-insensitive):
- "auth", "permission", "unauthorized", "forbidden", "401", "403"
- "invalid", "400", "422", "bad request"
- "not found", "404"
- "format", "corrupt", "unsupported"

---

## 6. Configuration

### 6.1 Environment Variables

Add to `.env` file:

```bash
# OCR Retry Configuration
OCR_MAX_RETRIES=3                    # Maximum retry attempts per page
OCR_RETRY_BASE_DELAY=1.0             # Base delay in seconds
OCR_RETRY_MAX_DELAY=60.0             # Maximum delay in seconds
OCR_RETRY_JITTER_RANGE=0.2           # Jitter range (0.0-1.0)
OCR_RATE_LIMIT_BASE_DELAY=5.0       # Base delay for rate limits
OCR_RATE_LIMIT_MAX_DELAY=300.0      # Max delay for rate limits (5 minutes)
```

### 6.2 Tuning Guidelines

**Increase Retries If**:
- High rate of transient failures
- Network is unreliable
- Processing large files

**Decrease Retries If**:
- Most failures are permanent
- Need faster failure feedback
- Cost concerns (each retry uses API quota)

**Increase Backoff If**:
- Frequent rate limit errors
- Server errors persist
- Need to reduce API load

**Decrease Backoff If**:
- Fast recovery expected
- Low API load
- Need faster processing

---

## 7. Success Metrics

### 7.1 Target Metrics

**Retry Success Rate**: 
- Target: 50-70% of transient failures recovered
- Measure: `successful_retries / total_retry_attempts`

**Overall Page Success Rate**:
- Target: 95%+ pages succeed (up from ~80-85% without retries)
- Measure: `successful_pages / total_pages`

**Rate Limit Recovery**:
- Target: 80%+ of rate limit errors recover
- Measure: `rate_limit_recoveries / rate_limit_events`

**Average Retry Attempts**:
- Target: < 1.5 attempts per page (most succeed on first try)
- Measure: `total_retry_attempts / total_pages`

### 7.2 Monitoring

Track these metrics:
- Retry attempt frequency
- Retry success rate by error category
- Rate limit event frequency
- Non-retryable error frequency
- Overall timeout budget usage
- Average processing time (with/without retries)

---

## 8. Definition of Done

The retry policy is considered complete when:

- [x] ✅ Retryable vs non-retryable errors clearly defined
- [x] ✅ Default retry parameters specified
- [x] ✅ Outcome behavior documented
- [x] ✅ Error classification table created
- [x] ✅ Configuration variables defined
- [x] ✅ Success metrics established
- [x] ✅ Configuration loading implemented (Section 2 - Completed)
- [x] ✅ Error classification function implemented (Section 3 - Completed)
- [x] ✅ Backoff calculation function implemented (Section 4 - Completed)
- [x] ✅ Retry budget management implemented (Section 5 - Completed)
- [x] ✅ Retry wrapper function implemented (Section 6 - Completed)
- [x] ✅ Enhanced logging for retries implemented (Section 7 - Completed)
- [ ] ⏳ Comprehensive testing implemented (next step - Section 8)
- [ ] ⏳ Retry wrapper function implemented (Section 6)
- [ ] ⏳ Logging for retries implemented (Section 7)
- [ ] ⏳ Testing completed (Section 8)

---

## 9. References

- [Retry Logic Implementation Plan](./RETRY_LOGIC_IMPLEMENTATION.md)
- [Retry Logic No-Code Guide](./RETRY_LOGIC_IMPLEMENTATION_NO_CODE.md)
- [Timeout Handling Implementation](./TIMEOUT_HANDLING_IMPLEMENTATION.md)
- Google Cloud Vision API Error Codes: [Documentation](https://cloud.google.com/vision/docs/error-codes)

---

**Last Updated**: December 2025  
**Status**: ✅ Policy Defined - Ready for Implementation  
**Next Step**: Implement error classification (Section 3 of no-code guide)

