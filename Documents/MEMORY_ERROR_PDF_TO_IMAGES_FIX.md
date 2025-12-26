# Memory Error Fix: PDF to Images Conversion

**Date**: December 2025  
**Status**: ✅ **FIXED**  
**Related**: Memory Error in `pdf_to_page_images_for_grok` function

---

## Problem

### Error Details

**Error**: `MemoryError` in `pdf_to_page_images_for_grok` function  
**Location**: `backend/ocr/grade_pdf_answer.py`, line 302  
**Error Message**: 
```
MemoryError
  File "grade_pdf_answer.py", line 302, in pdf_to_page_images_for_grok
    resized = img.copy()
```

**Error Log**: `insightLLM_backend/logs/errors_log.txt` (line 1-10)

### Root Cause

The `pdf_to_page_images_for_grok` function was accumulating **all page images in memory** before processing them:

1. **Lines 289-295**: Loaded ALL pages into a list `images = []`
2. **Lines 299-302**: Then processed them, but at line 302 tried to copy the image
3. **Result**: MemoryError when trying to copy large images that were all held in memory

**Problem Pattern**:
```python
images = []  # ❌ Accumulates all images
for page in doc:
    pil_img = Image.open(...)
    images.append(pil_img)  # ❌ All images in memory

for idx, img in enumerate(images):
    resized = img.copy()  # ❌ MemoryError - too many images in memory
```

---

## Solution

### Fix: Process Pages One at a Time

Changed the function to process pages **one at a time** instead of accumulating them:

1. **Removed** the `images = []` list that accumulated all images
2. **Process each page immediately** after loading it
3. **Explicit cleanup** after each page (delete variables, close images)
4. **Force garbage collection** after each page

**Fixed Pattern**:
```python
page_images: List[Dict[str, Any]] = []

for idx, page in enumerate(doc):  # ✅ Process one at a time
    if idx >= max_pages:
        break
    
    # Load and process immediately
    pix = page.get_pixmap(dpi=200)
    pil_img = Image.open(...)
    resized = pil_img.copy()  # ✅ Only one image in memory at a time
    # ... process and save ...
    
    # Cleanup after each page
    del resized, pil_img, pix
    gc.collect()  # ✅ Force garbage collection
```

---

## Changes Made

### File: `backend/ocr/grade_pdf_answer.py`

#### 1. Added `gc` Import

**Location**: Line 16

```python
import gc
```

#### 2. Refactored `pdf_to_page_images_for_grok` Function

**Location**: Lines 287-357

**Changes**:
- Removed `images = []` list accumulation
- Changed to process pages one at a time in a single loop
- Added explicit cleanup (`del` statements) after each page
- Added `gc.collect()` after each page
- Wrapped page processing in try/finally for cleanup

**Before**:
```python
images = []
for page in doc:
    pil_img = Image.open(...)
    images.append(pil_img)  # ❌ Accumulates all

for idx, img in enumerate(images):
    resized = img.copy()  # ❌ MemoryError
```

**After**:
```python
for idx, page in enumerate(doc):
    try:
        pix = page.get_pixmap(dpi=200)
        pil_img = Image.open(...)
        resized = pil_img.copy()  # ✅ Only one at a time
        # ... process ...
    finally:
        del resized, pil_img, pix
        gc.collect()  # ✅ Cleanup
```

---

## Memory Impact

### Before Fix

- **Peak Memory**: All page images in memory simultaneously
- **For 9-page PDF**: ~9 × image_size = Very high memory usage
- **Result**: MemoryError on large PDFs

### After Fix

- **Peak Memory**: Only one page image in memory at a time
- **For 9-page PDF**: ~1 × image_size = Much lower memory usage
- **Result**: No MemoryError, processes successfully

### Memory Reduction

- **Before**: O(n) where n = number of pages (all pages in memory)
- **After**: O(1) constant memory (only one page at a time)
- **Improvement**: ~90% reduction in peak memory for 9-page PDF

---

## Testing

### Test Case

**File**: `Current Affairs 1.pdf` (9 pages, 7.5 MB)  
**Error**: MemoryError at line 302  
**Status**: ✅ **FIXED** - No longer occurs

### Expected Behavior

1. Function processes pages one at a time
2. Each page is cleaned up immediately after processing
3. No memory accumulation
4. Large PDFs process successfully

---

## Related Issues

This fix is similar to the memory fixes implemented for:
- **Issue #7**: Memory Error During PDF Annotation Phase
- **Solution 1**: Process Pages One at a Time
- **Solution 5**: Memory Monitoring

**Consistency**: Both annotation and image conversion now use the same pattern (process one at a time, cleanup, gc.collect()).

---

## Files Modified

1. **`backend/ocr/grade_pdf_answer.py`**
   - Added `gc` import
   - Refactored `pdf_to_page_images_for_grok` function
   - Added explicit cleanup and garbage collection

---

## Error Logs Location

- **Main Log**: `insightLLM_backend/logs/log.txt`
- **Error Log**: `insightLLM_backend/logs/errors_log.txt`
- **Uvicorn Log**: `insightLLM_backend/logs/insightllm.log`

**Error Entry**:
```
2025-12-26T17:29:42.065673Z [ERROR] request=1f563678 error= traceback=...
MemoryError
```

---

## Prevention

### Code Review Checklist

When processing multiple items (pages, images, etc.):

- [ ] Avoid accumulating all items in a list before processing
- [ ] Process items one at a time when possible
- [ ] Add explicit cleanup (`del` statements) after processing each item
- [ ] Call `gc.collect()` after processing large items
- [ ] Use try/finally blocks to ensure cleanup even on errors

### Pattern to Follow

```python
# ✅ GOOD: Process one at a time
for item in items:
    try:
        # Process item
        result = process(item)
        results.append(result)
    finally:
        # Cleanup
        del item, result
        gc.collect()
```

```python
# ❌ BAD: Accumulate all first
all_items = []
for item in items:
    all_items.append(item)  # ❌ Memory accumulation

for item in all_items:
    process(item)  # ❌ May cause MemoryError
```

---

## Summary

**Problem**: MemoryError in `pdf_to_page_images_for_grok` due to accumulating all page images in memory.

**Solution**: Process pages one at a time with explicit cleanup and garbage collection.

**Result**: ✅ Fixed - No more MemoryError, processes large PDFs successfully.

**Memory Reduction**: ~90% reduction in peak memory usage.

---

**Last Updated**: December 2025  
**Status**: ✅ **FIXED**

