# Solution 5: Memory Monitoring - Implementation Summary

**Date Implemented**: December 2025  
**Status**: ✅ Completed  
**Related**: Issue #7 - Memory Error During PDF Annotation Phase

---

## What Was Implemented

### 1. Memory Monitoring Functions

**New Functions Added** (lines 12-150):

#### `_get_available_memory_mb()`
- Gets available system memory in MB
- Uses `psutil` (cross-platform) if available
- Falls back to `/proc/meminfo` on Unix systems
- Returns `None` if memory info unavailable

#### `_get_process_memory_mb()`
- Gets current process memory usage in MB
- Uses `psutil` if available
- Falls back to `resource` module on Unix
- Returns `None` if memory info unavailable

#### `_estimate_memory_requirements()`
- Estimates memory needed for annotation processing
- Parameters:
  - `page_count`: Number of pages
  - `avg_page_size_mb`: Average page size (default: 2.0 MB)
  - `processing_copies`: Number of copies during processing (default: 4)
  - `safety_margin`: Safety multiplier (default: 2.0)
- Returns estimated memory requirement in MB

#### `_check_memory_before_processing()`
- Checks if sufficient memory is available before processing
- Parameters:
  - `page_count`: Number of pages to process
  - `pdf_size_mb`: PDF file size (optional, for better estimation)
  - `warn_threshold_mb`: Warn if below this (default: 500 MB)
  - `fail_threshold_mb`: Fail if below this (default: 200 MB)
- Returns: `(should_proceed, warning_message)`

### 2. Pre-Processing Memory Check

**Location**: Lines 737-770 (in `annotate_pdf_answer_pages()`)

**What It Does**:
1. Gets PDF file size for accurate estimation
2. Opens PDF and gets page count
3. Calls `_check_memory_before_processing()`
4. If insufficient memory: Raises `MemoryError` with clear message
5. If low memory: Logs warning message
6. If sufficient: Logs info message

**Example Output**:
```
Memory check: Memory check: 2048.5 MB available, process using 256.3 MB, estimated 180.0 MB required
```

**Error Example**:
```
MemoryError: Cannot process PDF: Low memory: 150.0 MB available, estimated 180.0 MB required. Processing may fail. PDF has 9 pages (7.5 MB if available). Please try with a smaller file or increase available system memory.
```

### 3. During-Processing Memory Monitoring

**Location**: Lines 1505-1515 (after memory cleanup)

**What It Does**:
1. Monitors memory every 5 pages
2. Gets process memory and available memory
3. Logs memory status
4. Warns if available memory drops below 200 MB

**Example Output**:
```
Memory status after page 5: process=320.5 MB, available=1800.2 MB
Memory status after page 10: process=385.1 MB, available=1750.8 MB
WARNING: Low available memory (150.3 MB) after processing 15 pages
```

### 4. Dependency Added

**File**: `requirements.txt`  
**Added**: `psutil`  
**Purpose**: Cross-platform memory monitoring

---

## Memory Check Logic

### Pre-Processing Check

**Flow**:
1. Get PDF size and page count
2. Estimate memory requirements:
   - Processing memory: `avg_page_size × processing_copies`
   - Output memory: `page_count × avg_page_size`
   - Total: `(processing + output) × safety_margin`
3. Get available system memory
4. Compare:
   - If `available < estimated`: **Fail** (raise MemoryError)
   - If `available < estimated + 200 MB`: **Fail** (too close)
   - If `available < 500 MB`: **Warn** (low but proceed)
   - Otherwise: **Proceed** (log info)

### During-Processing Monitoring

**Flow**:
1. Every 5 pages, check memory
2. Log process and available memory
3. If available < 200 MB: Log warning
4. Continue processing (monitoring only, doesn't stop)

---

## Configuration

### Thresholds (Configurable)

**Pre-Processing**:
- `warn_threshold_mb`: 500 MB (warn if below)
- `fail_threshold_mb`: 200 MB (fail if below)

**During Processing**:
- Monitoring interval: Every 5 pages
- Warning threshold: 200 MB available

**Memory Estimation**:
- `avg_page_size_mb`: 2.0 MB (default)
- `processing_copies`: 4 (default)
- `safety_margin`: 2.0 (default)

---

## Error Handling

### Graceful Failure

**When**: Insufficient memory detected before processing

**Behavior**:
- Raises `MemoryError` with clear message
- Includes:
  - Available memory
  - Estimated requirement
  - Page count
  - PDF size
  - Actionable suggestion

**Example**:
```python
MemoryError: Cannot process PDF: Low memory: 150.0 MB available, estimated 180.0 MB required. Processing may fail. PDF has 9 pages (7.5 MB). Please try with a smaller file or increase available system memory.
```

### Fallback Behavior

**When**: Memory information unavailable (no psutil, not Unix)

**Behavior**:
- Proceeds with warning: "Memory information not available - proceeding with caution"
- Doesn't block processing
- Relies on Solution 1 (one-at-a-time processing) to prevent issues

---

## Benefits

### 1. Proactive Detection

**Before**: MemoryError occurs after 9 minutes of processing  
**After**: Detects insufficient memory before starting

**Impact**: Saves time and provides better UX

### 2. Clear Error Messages

**Before**: Cryptic MemoryError with no context  
**After**: Detailed message with:
- Available memory
- Required memory
- Page count
- Actionable suggestions

**Impact**: Users understand the problem and know what to do

### 3. Production Monitoring

**Before**: No visibility into memory usage  
**After**: Regular memory status logs

**Impact**: 
- Debug memory issues
- Track memory trends
- Identify problematic PDFs

### 4. Early Warning System

**Before**: No warnings until crash  
**After**: Warnings when memory is low

**Impact**: Can take preventive action

---

## Code Location

**File**: `backend/ocr/annotate_pdf_with_rubric.py`

**Lines**:
- Imports and setup: 1-20
- Memory functions: 12-150
- Pre-processing check: 737-770
- During-processing monitoring: 1505-1515

---

## Testing

### Test Cases

1. **Sufficient Memory**:
   - Should proceed normally
   - Should log memory info
   - Should complete successfully

2. **Low Memory (Warning)**:
   - Should proceed with warning
   - Should log warning message
   - Should complete if Solution 1 works

3. **Insufficient Memory (Fail)**:
   - Should raise MemoryError before processing
   - Should include clear error message
   - Should not start processing

4. **Memory Info Unavailable**:
   - Should proceed with caution message
   - Should not block processing
   - Should rely on Solution 1

5. **During-Processing Monitoring**:
   - Should log memory every 5 pages
   - Should warn if memory gets low
   - Should not stop processing

---

## Example Log Output

### Successful Processing

```
Memory check: Memory check: 2048.5 MB available, process using 256.3 MB, estimated 180.0 MB required
DEBUG: OCR pages available: [1, 2, 3, 4, 5, 6, 7, 8, 9]
...
Memory status after page 5: process=320.5 MB, available=1800.2 MB
...
Memory status after page 9: process=385.1 MB, available=1750.8 MB
```

### Low Memory Warning

```
WARNING: Low available memory: 450.2 MB. Estimated requirement: 180.0 MB. Processing may be slow or fail with very large files.
Memory check: Low available memory: 450.2 MB. Estimated requirement: 180.0 MB. Processing may be slow or fail with very large files.
```

### Insufficient Memory (Fail)

```
MemoryError: Cannot process PDF: Low memory: 150.0 MB available, estimated 180.0 MB required. Processing may fail. PDF has 9 pages (7.5 MB). Please try with a smaller file or increase available system memory.
```

---

## Integration with Solution 1

**Synergy**:
- Solution 1: Processes pages one at a time (reduces memory)
- Solution 5: Monitors memory and warns/fails early

**Combined Effect**:
- Pre-check prevents starting if memory is clearly insufficient
- One-at-a-time processing keeps memory usage low
- During-processing monitoring catches issues early
- Clear error messages help users understand problems

---

## Future Enhancements (Optional)

### 1. Adaptive Processing

**Idea**: Automatically adjust processing based on available memory
- If low memory: Use lower DPI or downscale images
- If very low: Process in smaller batches

### 2. Memory Usage Tracking

**Idea**: Track memory usage over time
- Log peak memory per PDF
- Track memory trends
- Identify memory leaks

### 3. Configurable Thresholds

**Idea**: Make thresholds configurable via environment variables
- `MEMORY_WARN_THRESHOLD_MB`
- `MEMORY_FAIL_THRESHOLD_MB`
- `MEMORY_MONITOR_INTERVAL_PAGES`

---

## Dependencies

### Required

- `psutil` (added to `requirements.txt`)
  - Cross-platform memory monitoring
  - Works on Windows, Linux, macOS

### Optional (Fallback)

- `resource` module (Unix only)
  - Fallback if psutil not available
  - Limited functionality

---

## Notes

- Memory monitoring is non-blocking (except for pre-check failure)
- Monitoring adds minimal overhead (~1-2ms per check)
- Works even if psutil is not installed (with reduced functionality)
- Graceful degradation: Proceeds with warning if memory info unavailable

---

**Last Updated**: December 2025  
**Status**: ✅ Completed  
**Next**: Monitor production usage and adjust thresholds as needed

