# Section 3: Implement Error Classification - Implementation Summary

**Date Implemented**: December 2025  
**Status**: ✅ Completed  
**Section**: 3 of Retry Logic Implementation Guide

---

## What Was Implemented

### 1. Error Classification Function

**New Function**: `_is_retryable_error()`  
**Location**: `backend/ocr/grade_pdf_answer.py` (lines 383-456)  
**Purpose**: Determine if an error should be retried based on error type, message patterns, and API response errors.

**Function Signature**:
```python
def _is_retryable_error(
    error: Exception,
    response: Optional[vision.AnnotateImageResponse] = None,
) -> Tuple[bool, str]:
```

**Returns**: 
- `Tuple[bool, str]` where:
  - `bool`: `True` if error is retryable, `False` if not
  - `str`: Error category label for logging and metrics

**Error Categories**:
- **Retryable**: `network_error`, `rate_limit`, `server_error`, `timeout`
- **Non-Retryable**: `auth_error`, `invalid_input`, `not_found`, `unknown`

---

## Classification Logic

### 1. Google Vision API Response Errors (Priority 1)

Checks `response.error.message` if response object is available:

**Retryable**:
- `resource_exhausted`, `rate limit`, `quota`, `429` → `rate_limit`
- `unavailable`, `deadline_exceeded`, `internal error`, `500`, `502`, `503`, `504` → `server_error`

**Non-Retryable**:
- `permission_denied`, `401`, `403` → `auth_error`
- `invalid_argument`, `invalid_image`, `400`, `422` → `invalid_input`
- `not_found`, `404` → `not_found`

### 2. Exception Type Classification (Priority 2)

**Retryable Exception Types**:
- `ConnectionError`, `ConnectionResetError`, `ConnectionAbortedError` → `network_error`
- `TimeoutError` → `timeout`

**Non-Retryable Exception Types**:
- `PermissionError` → `auth_error`
- `ValueError` → `invalid_input`

### 3. Error Message Pattern Matching (Priority 3)

**Retryable Patterns** (case-insensitive):
- Network: `connection`, `network`, `dns`, `socket`
- Timeout: `timeout`, `deadline`
- Rate Limit: `429`, `rate limit`, `quota`, `resource_exhausted`
- Server: `500`, `502`, `503`, `504`, `unavailable`, `internal error`, `gateway`

**Non-Retryable Patterns** (case-insensitive):
- Auth: `auth`, `permission`, `unauthorized`, `forbidden`, `401`, `403`
- Invalid: `invalid`, `bad request`, `400`, `422`, `invalid_argument`, `invalid_image`
- Not Found: `404`, `not found`
- Format: `format`, `corrupt`, `unsupported`, `too large`, `size limit`

### 4. Default Behavior

**Unknown Errors**: Default to **non-retryable** (`unknown` category)
- Conservative approach to avoid wasting retries on unpredictable errors
- Can be adjusted based on observed error patterns

---

## Implementation Details

### Code Structure

```python
def _is_retryable_error(
    error: Exception,
    response: Optional[vision.AnnotateImageResponse] = None,
) -> Tuple[bool, str]:
    """
    Determine if an error should be retried based on error type and message.
    
    Args:
        error: The exception that was raised
        response: Optional Vision API response object (for checking response.error)
    
    Returns:
        Tuple of (is_retryable: bool, error_category: str)
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()
    
    # 1. Check Google Vision API response errors first
    if response and hasattr(response, 'error') and response.error.message:
        # ... API error classification
    
    # 2. Check exception types
    if error_type in ['ConnectionError', ...]:
        # ... Exception type classification
    
    # 3. Check error message patterns
    if 'timeout' in error_msg or 'deadline' in error_msg:
        # ... Message pattern matching
    
    # 4. Default: non-retryable
    return False, 'unknown'
```

### Classification Priority

1. **API Response Errors** (highest priority)
   - Most specific and reliable
   - Directly from Google Vision API

2. **Exception Types**
   - Python exception hierarchy
   - Type-safe classification

3. **Error Message Patterns**
   - Fallback for unknown exception types
   - Handles wrapped errors

4. **Default**
   - Conservative: non-retryable
   - Prevents wasted retries

---

## Error Category Reference

### Retryable Categories

| Category | Description | Examples |
|----------|-------------|----------|
| `network_error` | Network/connection issues | ConnectionError, DNS failures, socket errors |
| `rate_limit` | Rate limit/quota exceeded | HTTP 429, RESOURCE_EXHAUSTED |
| `server_error` | Temporary server errors | HTTP 500-504, UNAVAILABLE |
| `timeout` | Request timeout | TimeoutError, DEADLINE_EXCEEDED |

### Non-Retryable Categories

| Category | Description | Examples |
|----------|-------------|----------|
| `auth_error` | Authentication/permission | HTTP 401/403, PERMISSION_DENIED |
| `invalid_input` | Invalid request/input | HTTP 400/422, INVALID_ARGUMENT, ValueError |
| `not_found` | Resource not found | HTTP 404, NOT_FOUND |
| `unknown` | Unknown/unclassified error | Default for unrecognized errors |

---

## Testing Strategy

### Test Cases

1. **Network Errors**:
   ```python
   error = ConnectionError("Connection reset")
   is_retryable, category = _is_retryable_error(error)
   assert is_retryable == True
   assert category == 'network_error'
   ```

2. **Rate Limit Errors**:
   ```python
   error = RuntimeError("OCR failed: RESOURCE_EXHAUSTED")
   is_retryable, category = _is_retryable_error(error)
   assert is_retryable == True
   assert category == 'rate_limit'
   ```

3. **Timeout Errors**:
   ```python
   error = TimeoutError("OCR timeout on page 1: exceeded 120.0 seconds")
   is_retryable, category = _is_retryable_error(error)
   assert is_retryable == True
   assert category == 'timeout'
   ```

4. **Auth Errors**:
   ```python
   error = RuntimeError("OCR failed: PERMISSION_DENIED")
   is_retryable, category = _is_retryable_error(error)
   assert is_retryable == False
   assert category == 'auth_error'
   ```

5. **Invalid Input Errors**:
   ```python
   error = ValueError("Invalid image format")
   is_retryable, category = _is_retryable_error(error)
   assert is_retryable == False
   assert category == 'invalid_input'
   ```

6. **API Response Errors**:
   ```python
   # Mock response with error
   response.error.message = "RESOURCE_EXHAUSTED"
   error = RuntimeError("API error")
   is_retryable, category = _is_retryable_error(error, response)
   assert is_retryable == True
   assert category == 'rate_limit'
   ```

---

## Integration Points

### Current Usage

The function is ready to be used in:
- `_call_vision_with_retry()` (Section 6 - to be implemented)
- Retry wrapper function (Section 6 - to be implemented)

### Future Integration

When implementing retry wrapper:
```python
try:
    response = _call_vision_with_timeout(...)
except Exception as e:
    is_retryable, category = _is_retryable_error(e, response)
    if is_retryable and attempts_remaining > 0:
        # Retry logic
    else:
        # Fail fast
```

---

## Alignment with Retry Policy

✅ **Fully Aligned** with `RETRY_POLICY.md`:

- ✅ Retryable errors match policy definition
- ✅ Non-retryable errors match policy definition
- ✅ Error categories match policy table
- ✅ Message patterns match policy patterns
- ✅ Default behavior is conservative (non-retryable)

---

## Known Limitations

1. **HTTP Status Codes**: 
   - Google Vision API may not expose HTTP status codes directly
   - Relies on error messages and exception types
   - **Mitigation**: Pattern matching on error messages

2. **Wrapped Errors**:
   - Errors may be wrapped in RuntimeError
   - **Mitigation**: Message pattern matching handles this

3. **Unknown Errors**:
   - Default to non-retryable (conservative)
   - **Mitigation**: Can be adjusted based on observed patterns

---

## Next Steps

1. **Section 4**: Implement Backoff Calculation
   - Will use error category to determine backoff strategy
   - Rate limit errors get special backoff

2. **Section 6**: Build Retry Wrapper
   - Will use `_is_retryable_error()` to decide retry behavior
   - Will use error category for logging

3. **Section 7**: Enhanced Logging
   - Will log error category for metrics
   - Will track retryable vs non-retryable error counts

---

## Code Location

**File**: `backend/ocr/grade_pdf_answer.py`  
**Lines**: 383-456  
**Placement**: Right before `_call_vision_with_timeout()` function

**Function**:
```python
def _is_retryable_error(
    error: Exception,
    response: Optional[vision.AnnotateImageResponse] = None,
) -> Tuple[bool, str]:
    # ... implementation
```

---

## Documentation Updates

- ✅ Function docstring includes all details
- ✅ Error categories documented
- ✅ Classification logic explained
- ✅ Aligned with RETRY_POLICY.md

---

**Last Updated**: December 2025  
**Status**: ✅ Completed  
**Next Section**: Section 4 - Implement Backoff Calculation

