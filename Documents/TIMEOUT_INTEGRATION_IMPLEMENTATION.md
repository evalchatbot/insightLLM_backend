# Section 5: Integrate Retries with Timeouts - Implementation Summary

**Date Implemented**: December 2025  
**Status**: ✅ Completed  
**Section**: 5 of Retry Logic Implementation Guide

---

## What Was Implemented

### 1. Retry Budget Checking Function

**New Function**: `_check_retry_budget()`  
**Location**: `backend/ocr/grade_pdf_answer.py` (lines 563-603)  
**Purpose**: Check if retry budget allows another retry attempt before exceeding overall timeout.

**Function Signature**:
```python
def _check_retry_budget(
    elapsed_time: float,
    overall_timeout: Optional[float],
    backoff_delay: float,
    estimated_attempt_time: float,
    safety_margin: float = 5.0,
) -> bool:
```

**Returns**: `True` if retry is allowed, `False` if it would exceed budget

### 2. Attempt Time Estimation Function

**New Function**: `_estimate_attempt_time()`  
**Location**: `backend/ocr/grade_pdf_answer.py` (lines 606-629)  
**Purpose**: Estimate time for a retry attempt to calculate retry cost.

**Function Signature**:
```python
def _estimate_attempt_time(
    per_page_timeout: float,
    previous_attempt_duration: Optional[float] = None,
) -> float:
```

**Returns**: Estimated attempt time in seconds

---

## Retry Budget Management

### Budget Calculation

**Formula**: `retry_cost = backoff_delay + estimated_attempt_time + safety_margin`

**Check**: `retry_cost <= remaining_budget`

Where:
- `remaining_budget = overall_timeout - elapsed_time`
- `safety_margin = 5.0` seconds (default, configurable)

### Budget Checking Logic

```python
# Before each retry:
remaining_budget = overall_timeout - elapsed_time
retry_cost = backoff_delay + estimated_attempt_time + safety_margin

if retry_cost > remaining_budget:
    # Stop retrying, mark page failed
    return False
else:
    # Proceed with retry
    return True
```

### Examples

**Example 1: Budget Allows Retry**
- Overall timeout: 600s
- Elapsed time: 580s
- Remaining: 20s
- Backoff delay: 2s
- Estimated attempt: 10s
- Safety margin: 5s
- **Retry cost**: 2 + 10 + 5 = 17s
- **Result**: ✅ 17s <= 20s → **Allow retry**

**Example 2: Budget Exceeded**
- Overall timeout: 600s
- Elapsed time: 590s
- Remaining: 10s
- Backoff delay: 5s
- Estimated attempt: 10s
- Safety margin: 5s
- **Retry cost**: 5 + 10 + 5 = 20s
- **Result**: ❌ 20s > 10s → **Stop retrying**

**Example 3: No Overall Timeout**
- Overall timeout: `None` (no limit)
- **Result**: ✅ **Always allow retry**

---

## Attempt Time Estimation

### Strategy: Conservative Estimation

**Option 1: Use Previous Attempt Duration** (if available)
- Formula: `previous_duration * 1.1` (10% buffer)
- More accurate if we have historical data
- Example: Previous attempt took 15s → Estimate 16.5s

**Option 2: Use Per-Page Timeout** (fallback)
- Formula: `per_page_timeout` (worst-case estimate)
- Conservative: Assumes attempt takes full timeout
- Example: Per-page timeout = 120s → Estimate 120s

### Why Conservative?

- Better to underestimate time and stop early
- Prevents exceeding overall timeout
- Safety margin provides additional buffer

---

## Per-Attempt Timeout Strategy

### Chosen Strategy: **Option A - Fixed Per-Attempt Timeout**

**Implementation**:
- Each retry attempt uses the same `per_page_timeout` as the original attempt
- No division or splitting of timeout budget
- Overall timeout budget enforced separately

**Why This Strategy**:
- ✅ Simpler to implement
- ✅ Easier to reason about
- ✅ Less risk of timeout calculation errors
- ✅ Overall timeout still enforced via budget checking

**Alternative (Not Chosen)**: Option B - Split Timeout
- Would divide per-page timeout across attempts
- More complex, higher risk of errors
- Not needed if overall timeout is properly enforced

---

## Integration Points

### Current Integration

The functions are ready to be used in:
- `_call_vision_with_retry()` (Section 6 - to be implemented)
- Retry wrapper function (Section 6 - to be implemented)

### Future Integration Flow

```python
# In retry wrapper (Section 6):
for attempt in range(1, max_retries + 1):
    try:
        # Make attempt
        response = _call_vision_with_timeout(...)
        return response  # Success
    except Exception as e:
        # Classify error
        is_retryable, category = _is_retryable_error(e, response)
        
        if not is_retryable:
            raise  # Fail fast
        
        if attempt >= max_retries:
            raise  # Exhausted retries
        
        # Calculate backoff
        backoff_delay = _calculate_backoff_delay(...)
        
        # Estimate attempt time
        estimated_time = _estimate_attempt_time(
            per_page_timeout=per_page_timeout,
            previous_attempt_duration=previous_duration
        )
        
        # Check retry budget
        if not _check_retry_budget(
            elapsed_time=elapsed_time,
            overall_timeout=overall_timeout,
            backoff_delay=backoff_delay,
            estimated_attempt_time=estimated_time
        ):
            # Budget exceeded, stop retrying
            raise TimeoutError("Retry budget exceeded")
        
        # Wait before retry
        time.sleep(backoff_delay)
```

---

## Timeout Budget Tracking

### What Gets Tracked

1. **Elapsed Time**: Total time spent on OCR processing
   - Tracked from start of `run_ocr_on_pdf()`
   - Updated after each page/attempt

2. **Overall Timeout**: Maximum time for entire OCR process
   - From environment variable: `OCR_OVERALL_TIMEOUT`
   - Default: 600s (10 minutes), configurable to 1200s (20 minutes)

3. **Per-Page Timeout**: Maximum time per page attempt
   - From environment variable: `OCR_PER_PAGE_TIMEOUT`
   - Default: 120s (2 minutes)
   - Used for each retry attempt (Option A strategy)

4. **Retry Costs**: Backoff delay + estimated attempt time + safety margin

### Budget Enforcement

**Before Each Retry**:
1. Calculate remaining budget: `overall_timeout - elapsed_time`
2. Calculate retry cost: `backoff_delay + estimated_attempt_time + safety_margin`
3. Check: `retry_cost <= remaining_budget`
4. If exceeded: Stop retrying, mark page failed, continue to next page

**Result**: Retries never exceed overall timeout budget

---

## Safety Margin

### Purpose

The `safety_margin` (default: 5.0 seconds) provides:
- Buffer for timing variations
- Prevents cutting it too close to timeout
- Accounts for function call overhead
- Reduces risk of timeout during retry

### Tuning

**Increase Safety Margin If**:
- Frequently cutting close to timeout
- Need more conservative retry behavior
- Processing is unpredictable

**Decrease Safety Margin If**:
- Want to maximize retry attempts
- Processing is very predictable
- Need to squeeze more retries in

**Default**: 5.0 seconds (good balance)

---

## Examples

### Example 1: Budget Allows Multiple Retries

**Scenario**:
- Overall timeout: 600s
- Per-page timeout: 120s
- Elapsed: 200s (after 2 pages)
- Remaining: 400s

**Retry Attempt 1**:
- Backoff: 2s
- Estimated attempt: 120s
- Cost: 2 + 120 + 5 = 127s
- ✅ 127s <= 400s → **Allow retry**

**Retry Attempt 2** (if first retry fails):
- Elapsed: 327s (200 + 127)
- Remaining: 273s
- Backoff: 4s
- Estimated attempt: 120s
- Cost: 4 + 120 + 5 = 129s
- ✅ 129s <= 273s → **Allow retry**

### Example 2: Budget Exceeded

**Scenario**:
- Overall timeout: 600s
- Elapsed: 590s
- Remaining: 10s
- Backoff: 2s
- Estimated attempt: 120s
- Cost: 2 + 120 + 5 = 127s
- ❌ 127s > 10s → **Stop retrying**

**Result**: Page marked as failed with "timeout_budget_exceeded" error

---

## Integration with Existing Timeout System

### Current Timeout Tracking

**In `run_ocr_on_pdf()`**:
- Line 468: `overall_start_time = time.perf_counter()`
- Line 475-480: Overall timeout check before each page
- Line 523: Per-page attempt timing

### Retry Budget Integration

**Will be added in retry wrapper** (Section 6):
- Track elapsed time from overall start
- Check budget before each retry
- Update elapsed time after each attempt
- Stop retrying if budget exceeded

**No Changes Needed** to existing timeout checks:
- Overall timeout check remains (line 475-480)
- Per-page timeout remains (passed to `_call_vision_with_timeout()`)
- Retry budget is **additional** protection layer

---

## Testing

### Test Cases

1. **Budget Allows Retry**:
   ```python
   assert _check_retry_budget(
       elapsed_time=100.0,
       overall_timeout=600.0,
       backoff_delay=2.0,
       estimated_attempt_time=120.0
   ) == True
   ```

2. **Budget Exceeded**:
   ```python
   assert _check_retry_budget(
       elapsed_time=590.0,
       overall_timeout=600.0,
       backoff_delay=5.0,
       estimated_attempt_time=120.0
   ) == False
   ```

3. **No Overall Timeout**:
   ```python
   assert _check_retry_budget(
       elapsed_time=1000.0,
       overall_timeout=None,
       backoff_delay=10.0,
       estimated_attempt_time=120.0
   ) == True
   ```

4. **Attempt Time Estimation**:
   ```python
   # With previous duration
   assert _estimate_attempt_time(120.0, previous_attempt_duration=15.0) == 16.5
   
   # Without previous duration
   assert _estimate_attempt_time(120.0) == 120.0
   ```

---

## Code Location

**File**: `backend/ocr/grade_pdf_answer.py`  
**Lines**: 
- `_check_retry_budget()`: 563-603
- `_estimate_attempt_time()`: 606-629

**Placement**: Right after `_calculate_backoff_delay()`, before `_call_vision_with_timeout()`

---

## Next Steps

1. **Section 6**: Build Retry Wrapper
   - Use `_check_retry_budget()` before each retry
   - Use `_estimate_attempt_time()` to calculate retry cost
   - Track elapsed time and update after each attempt
   - Stop retrying if budget exceeded

2. **Section 7**: Enhanced Logging
   - Log budget checks (allowed/denied)
   - Log retry costs and remaining budget
   - Log when retries stop due to budget

---

## Alignment with Retry Policy

✅ **Fully Aligned** with `RETRY_POLICY.md`:

- ✅ Retry budget management implemented
- ✅ Per-attempt timeout strategy: Option A (Fixed timeout)
- ✅ Overall timeout budget enforced
- ✅ Safety margin included
- ✅ Conservative time estimation

---

## Documentation Updates

- ✅ Function docstrings include examples
- ✅ Budget calculation logic explained
- ✅ Integration points documented
- ✅ Aligned with RETRY_POLICY.md

---

**Last Updated**: December 2025  
**Status**: ✅ Completed  
**Next Section**: Section 6 - Build Retry Wrapper

