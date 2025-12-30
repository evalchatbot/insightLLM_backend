# Regular Files Requirements - Quick Answer

**Question**: Are only these 2 files needed to correctly check the report?

**Answer**: **No, you need 4 things minimum**:

---

## Required Files/Directories

### 1. ✅ `grade_pdf_answer.py` (Required)
- **Location**: `insightLLM_backend/grade_pdf_answer.py`
- **Purpose**: Main grading pipeline
- **Contains**: OCR, Grok calls, report rendering

### 2. ✅ `annotate_pdf_with_rubric.py` (Required)
- **Location**: `insightLLM_backend/annotate_pdf_with_rubric.py`
- **Purpose**: Annotation rendering
- **Contains**: PDF annotation logic

### 3. ✅ `20marks_Rubrics/` Directory (Required)
- **Location**: `insightLLM_backend/20marks_Rubrics/` OR `insightLLM_backend/backend/20marks_Rubrics/`
- **Purpose**: Subject-specific rubric DOCX files
- **Why Required**: Without this, subject-wise grading will be weak (warnings printed, but grading continues)

### 4. ✅ `REFINED RUBRIC.docx` (Required)
- **Location**: `insightLLM_backend/REFINED RUBRIC.docx`
- **Purpose**: Generic refined rubric for annotations
- **Why Required**: Without this, refined rubric annotations will be weak (warnings printed, but annotations continue)

---

## What Happens Without Rubric Files?

### Without `20marks_Rubrics/`:
- ⚠️ Warning printed: `"WARNING: No subject rubric DOCX found for '{subject}'."`
- ⚠️ Grading continues but will be weaker
- ✅ Report still generated
- ✅ Annotations still created

### Without `REFINED RUBRIC.docx`:
- ⚠️ Warning printed: `"WARNING: Refined rubric DOCX not found."`
- ⚠️ Annotations continue but will be weaker
- ✅ Report still generated
- ✅ Basic annotations still created

---

## Complete File Checklist

### Core Python Files (2 files) ✅
- [ ] `grade_pdf_answer.py`
- [ ] `annotate_pdf_with_rubric.py`

### Rubric Files (2 things) ✅
- [ ] `20marks_Rubrics/` directory (with at least one subject folder)
- [ ] `REFINED RUBRIC.docx` file

### Service Files (Created for you) ✅
- [ ] `backend/ocr/service_regular.py` (created)
- [ ] `backend/api/routes/ocr_regular.py` (created)
- [ ] `backend/main.py` (updated to register router)

### Environment Variables ✅
- [ ] `Grok_API` in `.env`
- [ ] `Google_cloud_key` in `.env`

### Dependencies ✅
- [ ] All packages from `requirements.txt` installed

---

## Summary

**Minimum Required**: 4 things
1. `grade_pdf_answer.py` ✅
2. `annotate_pdf_with_rubric.py` ✅
3. `20marks_Rubrics/` directory ✅
4. `REFINED RUBRIC.docx` ✅

**For Full Functionality**: All 4 are needed. Without rubrics, the system will work but produce weaker results.

---

## Endpoints Created

Three new endpoints are available at `/api/ocr-regular/`:

1. `POST /api/ocr-regular/annotate` - Full annotation with PDF
2. `POST /api/ocr-regular/annotate/json` - JSON only
3. `GET /api/ocr-regular/subjects` - List subjects

See `REGULAR_FILES_ENDPOINTS.md` for full documentation.

