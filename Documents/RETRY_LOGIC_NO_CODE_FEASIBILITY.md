# Retry Logic No-Code Guide - Feasibility Assessment

## Executive Summary

**Overall Feasibility**: ✅ **HIGHLY FEASIBLE**

The no-code guide is **perfectly aligned** with your current codebase structure and can be implemented step-by-step without major refactoring. It builds naturally on your existing timeout handling implementation.

**Recommended Approach**: Follow the guide sequentially, implementing each section as described.

---

## Current State vs Guide Requirements

### ✅ Preconditions (Section 0) - **FULLY MET**

| Requirement | Status | Notes |
|------------|--------|-------|
| Per-page timeout | ✅ Complete | `per_page_timeout` parameter (120s default) |
| Overall timeout | ✅ Complete | `overall_timeout` parameter (600s default, configurable to 1200s) |
| Partial success support | ✅ Complete | `failed_pages` tracking, continues on failure |
| Primary location identified | ✅ Complete | `_call_vision_with_timeout()` function exists |

**Verdict**: ✅ **All preconditions met** - Ready to proceed

---

## Section-by-Section Feasibility

### Section 1: Define Retry Policy - ✅ **VERY EASY**

**Feasibility**: Very High  
**Complexity**: Low  
**Time Estimate**: 30 minutes (documentation only)

**Current State**:
- ✅ Error handling exists but basic
- ❌ No error classification
- ❌ No retry policy defined

**What's Needed**:
- Document retryable vs non-retryable errors
- Define default retry parameters
- Document outcome behavior

**Feasibility**: ✅ **Very Easy** - Just documentation/planning

**Alignment with Code**:
- Your `RETRY_LOGIC_IMPLEMENTATION.md` already has this defined
- Guide's classification matches your plan
- Default parameters align with your recommendations

---

### Section 2: Add Configuration Knobs - ✅ **EASY**

**Feasibility**: Very High  
**Complexity**: Low  
**Time Estimate**: 1-2 hours

**Current State**:
- ✅ Environment variable pattern exists (`OCR_PER_PAGE_TIMEOUT`, `OCR_OVERALL_TIMEOUT`)
- ✅ Configuration loaded in `grade_pdf_answer()` (lines 2607-2609)

**What's Needed**:
- Add 6 new environment variables:
  - `OCR_MAX_RETRIES`
  - `OCR_RETRY_BASE_DELAY`
  - `OCR_RETRY_MAX_DELAY`
  - `OCR_RETRY_JITTER_RANGE`
  - `OCR_RATE_LIMIT_BASE_DELAY`
  - `OCR_RATE_LIMIT_MAX_DELAY`
- Load in same location as timeout configs

**Feasibility**: ✅ **Easy** - Follow existing pattern

**Code Location**: `grade_pdf_answer.py` lines 2607-2609 (where timeout configs are loaded)

---

### Section 3: Implement Error Classification - ✅ **MODERATE**

**Feasibility**: High  
**Complexity**: Moderate  
**Time Estimate**: 3-4 hours

**Current State**:
- ✅ Basic error handling in `_call_vision_with_timeout()` (lines 424-437)
- ✅ Error types caught: `FutureTimeoutError`, `RuntimeError`, generic `Exception`
- ✅ Response error checking: `response.error.message` (line 417)
- ❌ No error classification logic
- ❌ No retryable/non-retryable determination

**What's Needed**:
- New function: `_is_retryable_error()`
- Parse error types and messages
- Check Google Vision API error codes
- Classify as retryable/non-retryable

**Feasibility**: ✅ **Moderate** - Straightforward logic, needs testing

**Code Location**: Add new function in `grade_pdf_answer.py` near `_call_vision_with_timeout()`

**Error Sources to Check**:
1. Exception types (already caught)
2. `response.error.message` (already checked)
3. Google Vision error codes (need to parse)
4. HTTP status codes (if available from client)

**Challenges**:
- Google Vision API error format may need investigation
- Some errors may not have clear HTTP status codes
- **Mitigation**: Start with exception types, add API error parsing incrementally

---

### Section 4: Implement Backoff Calculation - ✅ **EASY**

**Feasibility**: Very High  
**Complexity**: Low  
**Time Estimate**: 1-2 hours

**Current State**:
- ❌ No backoff calculation
- ✅ Python `time` module available (already imported)
- ✅ Python `random` module available (for jitter)

**What's Needed**:
- New function: `_calculate_backoff_delay()`
- Exponential formula: `base_delay * (2 ^ (attempt - 1))`
- Cap at max_delay
- Add jitter (±jitter_range)
- Special handling for rate limits

**Feasibility**: ✅ **Easy** - Simple math, well-defined formula

**Code Location**: Add new function in `grade_pdf_answer.py`

**Formula Implementation**:
```python
# Pseudocode (not actual code)
delay = base_delay * (2 ** (attempt - 1))
delay = min(delay, max_delay)
jitter = random.uniform(-jitter_range, jitter_range) * delay
final_delay = delay + jitter
```

---

### Section 5: Integrate Retries with Timeouts - ✅ **MODERATE**

**Feasibility**: High  
**Complexity**: Moderate  
**Time Estimate**: 4-6 hours

**Current State**:
- ✅ Per-page timeout exists (`per_page_timeout`)
- ✅ Overall timeout exists (`overall_timeout`)
- ✅ Timeout tracking in `run_ocr_on_pdf()` (line 468)
- ✅ Overall timeout checking before each page (lines 475-480)

**What's Needed**:
- Choose per-attempt timeout strategy (Option A or B from guide)
- Track retry budget against overall timeout
- Check budget before each retry
- Adjust timeout per attempt if using Option B

**Feasibility**: ✅ **Moderate** - Requires careful integration

**Recommended Approach**: **Option A (Fixed per-attempt timeout)**
- Simpler to implement
- Easier to reason about
- Less risk of timeout calculation errors
- Still respects overall timeout via budget checking

**Code Changes**:
- Track `total_retry_time` in retry loop
- Check `remaining_budget = overall_timeout - elapsed_time`
- Before retry: `if backoff_delay + estimated_attempt_time > remaining_budget: fail`

---

### Section 6: Build Retry Wrapper Flow - ✅ **MODERATE**

**Feasibility**: High  
**Complexity**: Moderate  
**Time Estimate**: 6-8 hours

**Current State**:
- ✅ `_call_vision_with_timeout()` exists (lines 384-437)
- ✅ Called from `run_ocr_on_pdf()` (line 517)
- ✅ Error handling in place
- ❌ No retry loop

**What's Needed**:
- New function: `_call_vision_with_retry()`
- Wraps `_call_vision_with_timeout()`
- Implements retry loop (attempt 1..N)
- Error classification
- Backoff calculation
- Budget checking

**Feasibility**: ✅ **Moderate** - Well-defined flow, clear integration point

**Code Structure**:
```
_call_vision_with_retry()  # New wrapper
  └─> For attempt in 1..max_retries:
      └─> _call_vision_with_timeout()  # Existing function
          └─> Success? Return
          └─> Failure? Classify error
              └─> Retryable? Wait + retry
              └─> Non-retryable? Fail fast
```

**Integration Point**: Replace `_call_vision_with_timeout()` call in `run_ocr_on_pdf()` line 517 with `_call_vision_with_retry()`

---

### Section 7: Logging and Metrics - ✅ **EASY**

**Feasibility**: Very High  
**Complexity**: Low  
**Time Estimate**: 2-3 hours

**Current State**:
- ✅ Logging infrastructure exists (`_append_log()` function)
- ✅ Request ID tracking
- ✅ Page number logging
- ✅ Duration logging
- ✅ Error logging
- ❌ No retry attempt logging
- ❌ No retry-specific metrics

**What's Needed**:
- Add retry attempt logs (INFO)
- Add retry success logs (INFO)
- Add retry exhausted logs (ERROR)
- Add rate limit detection logs (WARNING)
- Add non-retryable error logs (ERROR)

**Feasibility**: ✅ **Easy** - Enhance existing logging

**Log Format** (aligns with existing):
```
[INFO] request=abc123 ocr_retry_attempt page=5 attempt=2/3 error=TimeoutError wait_s=2.1
[INFO] request=abc123 ocr_retry_success page=5 attempt=2/3 total_attempts=2 duration_ms=4500
[ERROR] request=abc123 ocr_retry_exhausted page=5 attempts=3 error=TimeoutError
[WARNING] request=abc123 ocr_rate_limit page=5 retry_after_s=30 wait_s=30.0
[ERROR] request=abc123 ocr_non_retryable page=5 error=PermissionDenied
```

**Code Location**: Add logs in `_call_vision_with_retry()` function

---

### Section 8: Testing Plan - ✅ **MODERATE**

**Feasibility**: High  
**Complexity**: Moderate  
**Time Estimate**: 4-6 hours

**Current State**:
- ✅ Test files exist (`tests/` directory)
- ✅ Error scenarios can be simulated
- ❌ No retry-specific tests

**What's Needed**:
- Mock Google Vision API calls
- Simulate different error types
- Test retry behavior
- Test timeout integration
- Test budget management

**Feasibility**: ✅ **Moderate** - Requires mocking, but straightforward

**Test Scenarios** (from guide):
1. Transient network error → succeeds on retry
2. Rate limit 429 → respects Retry-After or long backoff
3. Temporary 503 → succeeds after backoff
4. Timeout then retry → succeeds or exhausts cleanly
5. Non-retryable 401/403 → no retry, fail fast
6. Max retries exhausted → page fails, job continues
7. Retry budget exceeded → early stop, partial results

**Testing Tools**:
- `unittest.mock` for mocking API calls
- `time.sleep` mocking for backoff testing
- Error injection for different error types

---

### Section 9: Rollout Strategy - ✅ **EASY**

**Feasibility**: Very High  
**Complexity**: Low  
**Time Estimate**: 1 hour (planning)

**Current State**:
- ✅ Environment variable configuration (allows easy tuning)
- ✅ Logging for monitoring
- ❌ No feature flags (but not required)

**What's Needed**:
- Start with conservative retries (max_retries=2-3)
- Monitor logs and metrics
- Tune parameters based on results

**Feasibility**: ✅ **Easy** - Configuration-driven, easy to adjust

**Rollout Plan**:
1. Deploy with `OCR_MAX_RETRIES=2` (conservative)
2. Monitor retry success rate
3. Monitor overall duration impact
4. Gradually increase if successful
5. Tune backoff delays based on rate limit frequency

---

### Section 10: Recommended Best Choices - ✅ **ALIGNED**

**Feasibility**: Very High  
**Complexity**: N/A (guidance only)

**Guide's Recommendations**:
1. Solution 2 (Error Classification) + Solution 3 (Backoff) - ✅ Aligned
2. Solution 1 (Retry Wrapper) - ✅ Aligned
3. Solution 4 (Rate-limit handling) - ✅ Aligned
4. Solution 5 (Retry budget) - ✅ Aligned
5. Solution 6 + 7 (Config + logging) - ✅ Aligned
6. Solution 8 (Timeout integration) - ✅ Aligned

**Verdict**: ✅ **All recommendations align with your architecture**

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1) - 8-12 hours

1. **Section 1**: Define retry policy (30 min) - Documentation
2. **Section 2**: Add configuration (1-2 hours) - Code
3. **Section 4**: Backoff calculation (1-2 hours) - Code
4. **Section 3**: Error classification (3-4 hours) - Code
5. **Section 7**: Logging enhancements (2-3 hours) - Code

### Phase 2: Core Implementation (Week 2) - 10-14 hours

6. **Section 5**: Timeout integration (4-6 hours) - Code
7. **Section 6**: Retry wrapper (6-8 hours) - Code

### Phase 3: Testing & Rollout (Week 3) - 5-7 hours

8. **Section 8**: Testing (4-6 hours) - Tests
9. **Section 9**: Rollout planning (1 hour) - Planning

**Total Estimated Time**: 23-33 hours (3-4 weeks part-time)

---

## Key Advantages of This Guide

### ✅ Perfect Alignment

1. **Matches Your Architecture**:
   - Uses existing `_call_vision_with_timeout()` function
   - Integrates with existing timeout system
   - Follows existing logging patterns
   - Uses existing configuration approach

2. **Builds on Fix #1**:
   - Doesn't replace timeout handling
   - Enhances it with retries
   - Respects timeout budgets
   - Maintains partial success support

3. **Incremental Implementation**:
   - Can implement section by section
   - Test each section independently
   - Low risk of breaking existing code

4. **Clear Integration Points**:
   - Exact function locations identified
   - Clear call chain
   - Minimal refactoring needed

---

## Potential Challenges & Mitigations

### Challenge 1: Google Vision API Error Format
**Issue**: May need to parse error messages to detect rate limits  
**Mitigation**: Start with exception types, add error parsing incrementally  
**Risk**: Low - Can enhance classification later

### Challenge 2: Retry Budget Calculation
**Issue**: Estimating attempt duration for budget checking  
**Mitigation**: Use conservative estimates, or use fixed per-attempt timeout (Option A)  
**Risk**: Low - Option A is simpler and safer

### Challenge 3: Testing Retry Scenarios
**Issue**: Hard to simulate real API errors  
**Mitigation**: Use mocking, inject errors in test harness  
**Risk**: Low - Standard testing practice

### Challenge 4: Rate Limit Detection
**Issue**: Google Vision may not return standard HTTP 429  
**Mitigation**: Check error messages for rate limit keywords, test with real rate limits  
**Risk**: Medium - May need iteration to get right

---

## Comparison with Your RETRY_LOGIC_IMPLEMENTATION.md

### Alignment Check

| Aspect | Your Doc | No-Code Guide | Match? |
|--------|----------|---------------|--------|
| Error Classification | ✅ Detailed | ✅ Detailed | ✅ Match |
| Backoff Formula | ✅ Exponential | ✅ Exponential | ✅ Match |
| Retry Wrapper | ✅ Described | ✅ Step-by-step | ✅ Match |
| Rate Limit Handling | ✅ Special case | ✅ Special case | ✅ Match |
| Timeout Integration | ✅ Detailed | ✅ Detailed | ✅ Match |
| Configuration | ✅ Env vars | ✅ Env vars | ✅ Match |
| Logging | ✅ Comprehensive | ✅ Comprehensive | ✅ Match |

**Verdict**: ✅ **Perfect alignment** - The no-code guide is a practical implementation of your planning document

---

## Definition of Done Checklist

From the guide, adapted for your project:

- [ ] Transient failures recover automatically (measured retry success rate)
- [ ] Permanent failures fail fast with correct classification
- [ ] 429 events back off appropriately (and respect Retry-After when present)
- [ ] Retries never violate the overall job timeout budget
- [ ] Logging + metrics show retry behavior per page and per job
- [ ] Partial success remains correct and user-facing messaging is clear
- [ ] Configuration allows tuning without code changes
- [ ] Tests cover all retry scenarios

---

## Final Verdict

### ✅ **HIGHLY FEASIBLE - RECOMMENDED**

**Reasons**:
1. ✅ Perfect alignment with existing code
2. ✅ Builds naturally on Fix #1 (timeouts)
3. ✅ Clear, step-by-step implementation guide
4. ✅ Incremental approach (low risk)
5. ✅ Well-defined integration points
6. ✅ Matches your planning document

**Recommendation**: **Follow this guide sequentially** - it's well-designed for your codebase structure.

**Estimated Effort**: 23-33 hours (3-4 weeks part-time)

**Expected Outcome**: 50-70% reduction in transient failures, improved reliability

---

**Last Updated**: December 2025  
**Assessment By**: Development Team  
**Status**: ✅ Approved for Implementation

