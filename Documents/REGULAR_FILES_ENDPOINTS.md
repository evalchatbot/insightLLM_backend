# Regular Files Endpoints - Testing Guide

**Date Created**: December 2025  
**Status**: ✅ Complete  
**Purpose**: Temporary endpoints for testing regular (non-backend) OCR files

---

## Overview

This document describes the temporary endpoints created to test the regular OCR files (`grade_pdf_answer.py` and `annotate_pdf_with_rubric.py`) instead of the backend versions.

**⚠️ Important**: These endpoints are for **testing purposes only**. For production, use the backend endpoints at `/api/ocr/*`.

---

## Endpoints

### Base URL
- **Development**: `http://localhost:8000`
- **Prefix**: `/api/ocr-regular`

---

### 1. `POST /api/ocr-regular/annotate`

**Purpose**: Annotate PDF using regular files (synchronous processing)

**Request**:
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body:
  - `file`: PDF file (required)
  - `user_id`: User ID (required)
  - `subject`: Subject name (required)

**Response**:
```json
{
  "pdf_base64": "base64_encoded_pdf_string",
  "pdf_url": "signed_url_to_pdf",
  "metadata": {
    "subject": "string",
    "total_marks_awarded": 0,
    "max_marks": 20,
    "criteria": [...],
    "token_usage": {...}
  },
  "filename": "annotated_filename.pdf",
  "request_id": "abc12345",
  "note": "This endpoint uses regular files (not backend files) for testing purposes."
}
```

**Features**:
- ✅ Uses regular `grade_pdf_answer.py`
- ✅ Uses regular `annotate_pdf_with_rubric.py`
- ✅ Synchronous processing (blocks until complete)
- ❌ No progress tracking
- ❌ No background job processing
- ❌ No advanced error recovery
- ❌ No memory management

**Example**:
```bash
curl -X POST "http://localhost:8000/api/ocr-regular/annotate" \
  -F "file=@answer.pdf" \
  -F "user_id=user_123" \
  -F "subject=Political Science"
```

---

### 2. `POST /api/ocr-regular/annotate/json`

**Purpose**: Get evaluation results as JSON only (no PDF)

**Request**: Same as `/api/ocr-regular/annotate`

**Response**:
```json
{
  "ok": true,
  "subject": "Political Science",
  "total_marks_awarded": 12,
  "max_marks": 20,
  "criteria": [...],
  "request_id": "abc12345",
  "note": "This endpoint uses regular files (not backend files) for testing purposes."
}
```

**Example**:
```bash
curl -X POST "http://localhost:8000/api/ocr-regular/annotate/json" \
  -F "file=@answer.pdf" \
  -F "subject=Political Science" \
  -F "user_id=user_123"
```

---

### 3. `GET /api/ocr-regular/subjects`

**Purpose**: Get available subjects from rubric directory

**Response**:
```json
{
  "subjects": [
    {
      "id": "political-science",
      "name": "Political Science"
    },
    ...
  ],
  "count": 25,
  "latency_ms": 45,
  "note": "This endpoint uses regular files (not backend files) for testing purposes."
}
```

**Example**:
```bash
curl "http://localhost:8000/api/ocr-regular/subjects"
```

---

## Files Required

### Core Files (Required)

1. **`grade_pdf_answer.py`** ✅
   - Location: `insightLLM_backend/grade_pdf_answer.py`
   - Main grading function
   - Contains OCR, Grok calls, report rendering

2. **`annotate_pdf_with_rubric.py`** ✅
   - Location: `insightLLM_backend/annotate_pdf_with_rubric.py`
   - Annotation rendering function
   - Creates annotated PDF pages

### Supporting Files/Directories (Required)

3. **`20marks_Rubrics/` directory** ✅
   - Location: `insightLLM_backend/20marks_Rubrics/` OR `insightLLM_backend/backend/20marks_Rubrics/`
   - Contains subject-specific rubric DOCX files
   - Required for subject-wise grading

4. **`REFINED RUBRIC.docx`** ✅
   - Location: `insightLLM_backend/REFINED RUBRIC.docx`
   - Generic refined rubric for annotations
   - Required for refined rubric annotations

### Service Files (Created)

5. **`service_regular.py`** ✅
   - Location: `insightLLM_backend/backend/ocr/service_regular.py`
   - Service wrapper for regular files
   - Handles file I/O and error handling

6. **`ocr_regular.py`** ✅
   - Location: `insightLLM_backend/backend/api/routes/ocr_regular.py`
   - FastAPI endpoints
   - Registered in `main.py`

---

## File Dependencies

### What `grade_pdf_answer.py` Needs:

1. **OCR Processing**:
   - Google Vision API client
   - PDF to image conversion (PyMuPDF/fitz)
   - Image processing (PIL/Pillow)

2. **Grok API Calls**:
   - Section detection
   - Subject-wise grading
   - Refined rubric annotations
   - Page-wise suggestions

3. **Rubric Files**:
   - Subject rubrics from `20marks_Rubrics/`
   - `REFINED RUBRIC.docx` for generic annotations

4. **Report Rendering**:
   - PIL/Pillow for image rendering
   - Font files (optional, has fallbacks)

5. **Annotation Function**:
   - `annotate_pdf_with_rubric.py` (imported)

### What `annotate_pdf_with_rubric.py` Needs:

1. **OCR Data**:
   - From `grade_pdf_answer.py` output
   - Page-by-page OCR with bounding boxes

2. **Sections Data**:
   - From Grok section detection
   - Headings and page numbers

3. **Annotations**:
   - From Grok refined rubric call
   - Introduction, headings, factual errors, grammar, repetition

4. **Page Suggestions**:
   - From Grok page-wise suggestions call

5. **Refined Summary**:
   - From Grok refined rubric call
   - 4 rubric points summary

---

## Complete Pipeline

### Step-by-Step Flow:

1. **PDF Upload** → Endpoint receives PDF bytes
2. **Save to Temp File** → Write PDF to temporary file
3. **Call `grade_pdf_answer()`**:
   - Step 1: Convert PDF to images (for Grok)
   - Step 2: Run OCR (Google Vision)
   - Step 3: Detect sections (Grok)
   - Step 4: Load subject rubric
   - Step 5: Subject-wise grading (Grok)
   - Step 6: Render subject report pages
   - Step 7: Load refined rubric
   - Step 8: Refined rubric annotations (Grok)
   - Step 9: Page-wise suggestions (Grok)
   - Step 10: Annotate pages (`annotate_pdf_with_rubric.py`)
   - Step 11: Merge all pages into final PDF
4. **Read Results** → Read output PDF and JSON
5. **Return Response** → Base64 PDF + metadata

---

## Differences from Backend Endpoints

| Feature | Regular Endpoints | Backend Endpoints |
|---------|------------------|-------------------|
| **Processing** | Synchronous | Asynchronous (background jobs) |
| **Progress Tracking** | ❌ None | ✅ Real-time progress |
| **Error Recovery** | Basic | Advanced retry logic |
| **Memory Management** | ❌ None | ✅ Pre-checks and monitoring |
| **Timeout Handling** | ❌ None | ✅ Per-page and overall |
| **Parallel OCR** | ❌ Sequential | ✅ Parallel (2-4 pages) |
| **Image Optimization** | ❌ None | ✅ Automatic downscaling |
| **Logging** | Basic print | Structured logging |
| **Job Management** | ❌ None | ✅ Job queue and status |

---

## Testing Checklist

### ✅ Required Files Check

- [ ] `grade_pdf_answer.py` exists in `insightLLM_backend/`
- [ ] `annotate_pdf_with_rubric.py` exists in `insightLLM_backend/`
- [ ] `20marks_Rubrics/` directory exists (in root or `backend/`)
- [ ] `REFINED RUBRIC.docx` exists in `insightLLM_backend/`
- [ ] At least one subject rubric DOCX file exists

### ✅ Environment Variables

- [ ] `Grok_API` is set in `.env`
- [ ] `Google_cloud_key` is set in `.env`

### ✅ Dependencies

- [ ] All packages in `requirements.txt` installed
- [ ] Google Vision API credentials configured
- [ ] Grok API key valid

### ✅ Endpoint Testing

1. **Test Subjects Endpoint**:
   ```bash
   curl http://localhost:8000/api/ocr-regular/subjects
   ```
   - Should return list of subjects
   - Should complete in < 1 second

2. **Test Annotate Endpoint**:
   ```bash
   curl -X POST "http://localhost:8000/api/ocr-regular/annotate" \
     -F "file=@test.pdf" \
     -F "user_id=test_user" \
     -F "subject=Political Science"
   ```
   - Should return PDF base64 and metadata
   - Processing time: ~5-10 minutes for small PDFs

3. **Test JSON Endpoint**:
   ```bash
   curl -X POST "http://localhost:8000/api/ocr-regular/annotate/json" \
     -F "file=@test.pdf" \
     -F "subject=Political Science"
   ```
   - Should return JSON metadata only
   - Faster than full annotate (no PDF encoding)

---

## Limitations

### What Regular Files DON'T Have:

1. **No Progress Tracking**:
   - Cannot poll for progress
   - Must wait for complete response
   - No step-by-step updates

2. **No Background Processing**:
   - Blocks until complete
   - Cannot cancel mid-processing
   - No job queue

3. **No Advanced Error Recovery**:
   - Fails immediately on errors
   - No retry logic
   - No timeout handling

4. **No Memory Management**:
   - May crash on large PDFs
   - No pre-processing checks
   - No automatic downscaling

5. **No Parallel Processing**:
   - Sequential OCR (slower)
   - No batch processing
   - No adaptive concurrency

---

## Migration Path

### When to Use Regular Endpoints:

✅ **Use Regular Endpoints When**:
- Testing annotation format
- Testing section detection
- Testing heading creation
- Comparing output with backend
- Debugging specific issues
- Small PDFs (<5 pages)

❌ **Don't Use Regular Endpoints For**:
- Production workloads
- Large PDFs (10+ pages)
- User-facing features
- Background processing
- Progress tracking needed

### Switching Back to Backend:

Simply use the regular endpoints:
- `/api/ocr/annotate` (instead of `/api/ocr-regular/annotate`)
- `/api/ocr/submit` (for background jobs)
- `/api/ocr/progress/{request_id}` (for progress)

---

## Troubleshooting

### Issue: "No subject rubric DOCX found"

**Solution**: 
- Check that `20marks_Rubrics/` directory exists
- Verify subject name matches directory/filename
- Check file permissions

### Issue: "REFINED RUBRIC.docx not found"

**Solution**:
- Ensure `REFINED RUBRIC.docx` exists in `insightLLM_backend/`
- Check file name (case-sensitive)
- Verify file is not corrupted

### Issue: Import errors

**Solution**:
- Ensure `grade_pdf_answer.py` and `annotate_pdf_with_rubric.py` are in `insightLLM_backend/`
- Check Python path includes project root
- Verify all dependencies installed

### Issue: Memory errors on large PDFs

**Solution**:
- Use backend endpoints instead (have memory management)
- Process smaller PDFs
- Increase system memory

---

## Code Locations

### Service File
- **Path**: `insightLLM_backend/backend/ocr/service_regular.py`
- **Class**: `OCRAnnotatorRegular`
- **Method**: `annotate_pdf()`

### Endpoints File
- **Path**: `insightLLM_backend/backend/api/routes/ocr_regular.py`
- **Router**: `/api/ocr-regular`
- **Endpoints**: 3 endpoints (annotate, annotate/json, subjects)

### Registration
- **File**: `insightLLM_backend/backend/main.py`
- **Line**: `app.include_router(ocr_regular.router)`

---

## Summary

**Answer to "Are only these 2 files needed?"**

**No, you need 4 things**:

1. ✅ **`grade_pdf_answer.py`** - Main grading function
2. ✅ **`annotate_pdf_with_rubric.py`** - Annotation rendering
3. ✅ **`20marks_Rubrics/` directory** - Subject rubrics (required for grading)
4. ✅ **`REFINED RUBRIC.docx`** - Generic rubric (required for annotations)

**Plus**:
- Environment variables (API keys)
- Python dependencies (installed packages)
- Service and endpoint files (created above)

The regular files are **self-contained** for the core logic, but they **depend on** the rubric files to function correctly. Without the rubric files, grading will work but will be weaker (warnings will be printed).

---

**Last Updated**: December 2025  
**Status**: Ready for Testing

