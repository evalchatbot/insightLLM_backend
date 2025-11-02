# OCR Cost Reduction Changes

## Date
2025-11-01

## Problem Identified
- 6-page document was being billed as **12 pages** in Azure Dashboard
- Costs were **$6-7 per 1000 pages** instead of expected **$1.50 per 1000 pages**

## Root Cause
Azure Document Intelligence `OCR_HIGH_RESOLUTION` feature was enabled, which:
- Bills **per page PER feature** (doubling the page count)
- May have premium pricing above base OCR rates
- Previous setup: 6 pages × 2 (base + feature) = **12 billed pages**

## Changes Made

### File: `backend/utils/ocr.py`

#### 1. Removed Premium OCR Feature (Line 152-163)
**Before:**
```python
features = [DocumentAnalysisFeature.OCR_HIGH_RESOLUTION]
poller = client.begin_analyze_document(model_id="prebuilt-read", body=f, features=features, pages=pages)
```

**After:**
```python
# REMOVED OCR_HIGH_RESOLUTION to reduce costs from 2x page billing to 1x page billing
# Previous cost: 6 pages × 2 (base + feature) = 12 billed pages
# New cost: 6 pages × 1 (base only) = 6 billed pages (50% savings)
poller = client.begin_analyze_document(model_id="prebuilt-read", body=f, pages=pages)
```

#### 2. Removed Unused Import (Line 29)
**Removed:** `from azure.ai.documentintelligence.models import DocumentAnalysisFeature`

#### 3. Added Debug Text Extraction (Line 147-180)
**Added function:** `_save_extracted_text_debug(pdf_path, page_texts)`
- Saves extracted OCR text to `ocr_debug_output/` folder
- Creates timestamped file with page-by-page extraction
- Allows verification of OCR quality without premium features

## Expected Results

### Cost Savings
- **50% reduction** in Azure page billing
- 6-page document: ~~12 billed pages~~ → **6 billed pages**
- Per 1000 pages: ~~$6-7~~ → **$1.50-$3**

### Quality Verification
- When you run OCR, check the generated text files in `ocr_debug_output/` folder
- Compare quality between base OCR vs premium features
- If quality is acceptable, keep changes; if not, we can re-enable features selectively

## Testing Instructions

1. Upload a PDF through the OCR module
2. Check Azure Dashboard - page count should match actual pages (not 2x)
3. Review extracted text in `backend/ocr_debug_output/{filename}_extracted_text.txt`
4. Verify text accuracy is acceptable for your use case

## Rollback Instructions (If Needed)

If OCR quality is insufficient without premium features:

```python
# Re-enable in run_ocr_with_retries():
from azure.ai.documentintelligence.models import DocumentAnalysisFeature

features = [DocumentAnalysisFeature.OCR_HIGH_RESOLUTION]
poller = client.begin_analyze_document(model_id="prebuilt-read", body=f, features=features, pages=pages)
```

## Notes
- Debug text extraction is temporary and can be removed after testing
- Azure's base "Read" API handles printed text very well
- OCR_HIGH_RESOLUTION is mainly beneficial for:
  - Low-quality scans
  - Handwritten text
  - Small font sizes
  - Complex layouts
