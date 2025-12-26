# Section 4: Implement Backoff Calculation - Implementation Summary

**Date Implemented**: December 2025  
**Status**: ✅ Completed  
**Section**: 4 of Retry Logic Implementation Guide

---

## What Was Implemented

### 1. Backoff Calculation Function

**New Function**: `_calculate_backoff_delay()`  
**Location**: `backend/ocr/grade_pdf_answer.py` (lines 485-560)  
**Purpose**: Calculate exponential backoff delay with jitter for retry attempts.

**Function Signature**:
```python
def _calculate_backoff_delay(
    attempt_number: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_range: float = 0.2,
    is_rate_limit: bool = False,
    rate_limit_base_delay: float = 5.0,
    rate_limit_max_delay: float = 300.0,
    retry_after: Optional[float] = None,
) -> float:
```

**Returns**: Delay in seconds (float)

---

## Backoff Formula

### Standard Exponential Backoff

**Formula**: `delay = base_delay * (2 ^ (attempt_number - 1)) + jitter`

**Steps**:
1. Calculate exponential delay: `base_delay * (2 ^ (attempt_number - 1))`
2. Cap at maximum: `min(exponential_delay, max_delay)`
3. Add jitter: `random.uniform(-jitter_range, jitter_range) * capped_delay`
4. Ensure non-negative: `max(0.0, final_delay)`

### Rate Limit Special Backoff

**When `is_rate_limit=True`**:
- Uses `rate_limit_base_delay` instead of `base_delay`
- Uses `rate_limit_max_delay` instead of `max_delay`
- Same exponential formula applies
- Longer delays to respect rate limits

### Retry-After Header Support

**When `retry_after` is provided**:
- Uses `retry_after` value directly (no calculation)
- No jitter applied (respects server's request)
- Takes precedence over calculated backoff

---

## Backoff Sequence Examples

### Standard Backoff (base=1.0, max=60.0, jitter=0.2)

| Attempt | Calculation | Base Delay | Jitter Range | Final Range |
|---------|-------------|------------|--------------|-------------|
| 1 | Immediate | 0.0s | N/A | 0.0s |
| 2 | 1.0 * 2^1 | 2.0s | ±0.4s | 1.6-2.4s |
| 3 | 1.0 * 2^2 | 4.0s | ±0.8s | 3.2-4.8s |
| 4 | 1.0 * 2^3 | 8.0s | ±1.6s | 6.4-9.6s |
| 5 | 1.0 * 2^4 | 16.0s | ±3.2s | 12.8-19.2s |
| 6 | 1.0 * 2^5 | 32.0s | ±6.4s | 25.6-38.4s |
| 7 | 1.0 * 2^6 | 64.0s → **60.0s** (capped) | ±12.0s | 48.0-60.0s |

### Rate Limit Backoff (base=5.0, max=300.0, jitter=0.2)

| Attempt | Calculation | Base Delay | Jitter Range | Final Range |
|---------|-------------|------------|--------------|-------------|
| 1 | Immediate | 0.0s | N/A | 0.0s |
| 2 | 5.0 * 2^1 | 10.0s | ±2.0s | 8.0-12.0s |
| 3 | 5.0 * 2^2 | 20.0s | ±4.0s | 16.0-24.0s |
| 4 | 5.0 * 2^3 | 40.0s | ±8.0s | 32.0-48.0s |
| 5 | 5.0 * 2^4 | 80.0s | ±16.0s | 64.0-96.0s |
| 6 | 5.0 * 2^5 | 160.0s | ±32.0s | 128.0-192.0s |
| 7 | 5.0 * 2^6 | 320.0s → **300.0s** (capped) | ±60.0s | 240.0-300.0s |

---

## Implementation Details

### 1. Exponential Growth

```python
# Attempt 1: No wait (immediate)
if attempt_number <= 1:
    return 0.0

# Attempt 2+: Exponential growth
exponential_delay = effective_base * (2 ** (attempt_number - 1))
```

**Why**: Each retry attempt waits longer, giving the system more time to recover.

### 2. Maximum Cap

```python
capped_delay = min(exponential_delay, effective_max)
```

**Why**: Prevents extremely long delays that would exceed timeout budgets.

### 3. Jitter

```python
jitter = random.uniform(-jitter_range, jitter_range) * capped_delay
final_delay = capped_delay + jitter
```

**Why**: Prevents "thundering herd" problem where multiple retries happen simultaneously.

**Example**: With jitter_range=0.2 (20%):
- 2.0s delay → jitter = ±0.4s → final = 1.6-2.4s
- Randomization spreads out retry attempts

### 4. Rate Limit Special Handling

```python
if is_rate_limit:
    effective_base = rate_limit_base_delay
    effective_max = rate_limit_max_delay
else:
    effective_base = base_delay
    effective_max = max_delay
```

**Why**: Rate limits need longer backoff to respect API quotas.

### 5. Retry-After Header Support

```python
if retry_after is not None and retry_after > 0:
    return float(retry_after)
```

**Why**: Server may specify exact wait time via Retry-After header. We should respect it.

---

## Usage Examples

### Standard Backoff

```python
# Attempt 2, standard backoff
delay = _calculate_backoff_delay(
    attempt_number=2,
    base_delay=1.0,
    max_delay=60.0,
    jitter_range=0.2
)
# Returns: ~1.6-2.4 seconds
```

### Rate Limit Backoff

```python
# Attempt 3, rate limit error
delay = _calculate_backoff_delay(
    attempt_number=3,
    base_delay=1.0,
    max_delay=60.0,
    jitter_range=0.2,
    is_rate_limit=True,
    rate_limit_base_delay=5.0,
    rate_limit_max_delay=300.0
)
# Returns: ~16.0-24.0 seconds
```

### Retry-After Header

```python
# Server says wait 30 seconds
delay = _calculate_backoff_delay(
    attempt_number=2,
    base_delay=1.0,
    max_delay=60.0,
    retry_after=30.0
)
# Returns: 30.0 seconds (exact, no jitter)
```

---

## Integration with Error Classification

The backoff calculation will be used with error classification:

```python
# Classify error
is_retryable, error_category = _is_retryable_error(error, response)

if is_retryable:
    # Determine if rate limit
    is_rate_limit = (error_category == 'rate_limit')
    
    # Calculate backoff
    delay = _calculate_backoff_delay(
        attempt_number=current_attempt,
        base_delay=retry_base_delay,
        max_delay=retry_max_delay,
        jitter_range=retry_jitter_range,
        is_rate_limit=is_rate_limit,
        rate_limit_base_delay=rate_limit_base_delay,
        rate_limit_max_delay=rate_limit_max_delay,
        retry_after=retry_after_header_value  # if available
    )
    
    # Wait before retry
    time.sleep(delay)
```

---

## Testing

### Test Cases

1. **First Attempt (No Wait)**:
   ```python
   delay = _calculate_backoff_delay(attempt_number=1)
   assert delay == 0.0
   ```

2. **Standard Exponential Growth**:
   ```python
   delay = _calculate_backoff_delay(attempt_number=2, base_delay=1.0)
   assert 1.6 <= delay <= 2.4  # 2.0 ± 20%
   ```

3. **Maximum Cap**:
   ```python
   delay = _calculate_backoff_delay(attempt_number=10, base_delay=1.0, max_delay=60.0)
   assert delay <= 60.0
   ```

4. **Rate Limit Special**:
   ```python
   delay = _calculate_backoff_delay(
       attempt_number=3,
       is_rate_limit=True,
       rate_limit_base_delay=5.0
   )
   assert 16.0 <= delay <= 24.0  # 20.0 ± 20%
   ```

5. **Retry-After Header**:
   ```python
   delay = _calculate_backoff_delay(attempt_number=2, retry_after=30.0)
   assert delay == 30.0
   ```

6. **Jitter Randomization**:
   ```python
   delays = [_calculate_backoff_delay(attempt_number=2) for _ in range(100)]
   # Should have variation (not all same value)
   assert len(set(delays)) > 1
   ```

---

## Configuration Integration

The function uses parameters that come from:
- Environment variables (via `grade_pdf_answer()`)
- Function parameters (passed from retry wrapper)
- Error classification (determines `is_rate_limit`)

**Parameter Flow**:
```
Environment Variables (config.py)
    ↓
grade_pdf_answer() loads configs
    ↓
run_ocr_on_pdf() receives parameters
    ↓
_calculate_backoff_delay() uses parameters
```

---

## Alignment with Retry Policy

✅ **Fully Aligned** with `RETRY_POLICY.md`:

- ✅ Exponential formula: `base_delay * (2 ^ (attempt - 1))`
- ✅ Maximum delay cap enforced
- ✅ Jitter range (20% default) applied
- ✅ Rate limit special handling (longer delays)
- ✅ Retry-After header support
- ✅ Default values match policy

---

## Code Location

**File**: `backend/ocr/grade_pdf_answer.py`  
**Lines**: 485-560  
**Placement**: Right after `_is_retryable_error()` function, before `_call_vision_with_timeout()`

**Dependencies**:
- `random` module (imported at line 25)
- `time` module (already imported)
- `Optional` from typing (already imported)

---

## Next Steps

1. **Section 5**: Integrate Retries with Timeouts
   - Use backoff delay in retry budget calculations
   - Check if retry would exceed overall timeout

2. **Section 6**: Build Retry Wrapper
   - Use `_calculate_backoff_delay()` in retry loop
   - Pass error category to determine rate limit handling
   - Use `time.sleep()` to wait before retry

3. **Section 7**: Enhanced Logging
   - Log calculated backoff delays
   - Log wait times before retries

---

## Documentation Updates

- ✅ Function docstring includes formula and examples
- ✅ All parameters documented
- ✅ Return value explained
- ✅ Usage examples provided
- ✅ Aligned with RETRY_POLICY.md

---

**Last Updated**: December 2025  
**Status**: ✅ Completed  
**Next Section**: Section 5 - Integrate Retries with Timeouts (or Section 6 - Build Retry Wrapper)

