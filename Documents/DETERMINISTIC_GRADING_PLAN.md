# Deterministic / Reproducible Grading (Same input ⇒ Same score)

## What this is called

- **Determinism**: Running the same request produces the same output (score + feedback).
- **Reproducibility**: You can reproduce a previous result reliably, even later.
- **Stability / Consistency**: Similar inputs yield similar outputs (not necessarily identical).
- **Grade freezing / Result locking**: Persist the first grade for an attempt and reuse it.
- **Caching**: Store and reuse expensive results (OCR, sections, grade result).

In practice, **LLM grading is inherently stochastic** unless you force determinism *and* stabilize all upstream inputs. The most reliable production approach is **grade freezing (hash-based result caching)**.

---

## Why you’re seeing different scores (e.g., 12 then 14)

Even if the PDF is identical, your pipeline has multiple sources of non-determinism:

1. **Model sampling**
   - If `temperature > 0` (or `top_p < 1`), the model is sampling. Scores can change run-to-run.

2. **Upstream variability (OCR + section detection)**
   - OCR can vary slightly across runs (spacing, punctuation, line breaks, tokenization).
   - Section detection can vary → grading sees different “sections” → different marks.

3. **Prompt drift**
   - Any prompt edits change grading behavior.
   - Even small changes to rubric text, ordering, or formatting can shift outcomes.

4. **Floating conversions / rounding / ordering**
   - Criterion ordering and text formatting can change the model’s reasoning path.

---

## Goals (what we want)

### A) “Same exact run input ⇒ same output”
This is **determinism** and can be approached with:
- deterministic decoding
- stabilized inputs

### B) “Same student submission ⇒ reuse the first grade forever”
This is **grade freezing** and is the most robust guarantee, even if the model is not fully deterministic.

You likely want **B** for production fairness and auditability.

---

## Strategy overview (recommended implementation later)

### Layer 1 — Deterministic decoding (reduces randomness)

When calling the model:
- Set **`temperature = 0`**
- Set **`top_p = 1`** (or disable nucleus sampling)
- Set **`frequency_penalty = 0`**, **`presence_penalty = 0`** (if supported)
- If the API supports it: pass a fixed **`seed`**

**Current state note**: Your grading payload uses `temperature: 0.15`, which is explicitly non-deterministic.

> Even with temperature = 0, many providers still have small nondeterminism due to infrastructure, but it’s usually far more stable.

### Layer 2 — Stabilize upstream inputs (fix the real cause)

To truly make “same submission” behave the same, we must ensure the model sees identical inputs:

1. **Cache OCR results**
   - Store Vision OCR output (full text + per-page data) and reuse it for re-grades.

2. **Cache section detection results**
   - Store the sections/headings JSON and reuse it.

3. **Canonicalize / normalize text**
   - Normalize whitespace, normalize line breaks, strip non-printing chars.
   - Sort objects consistently (e.g., criteria lists if derived dynamically).

Without caching, a minor OCR/sections difference can still flip the final mark.

### Layer 3 — Grade freezing (hash-based result caching) ✅ strongest guarantee

Implement a “grade lock”:

1. Compute a **stable fingerprint** (hash) for the submission + rubric + prompt version.
2. Check a storage layer (DB / file / object store) for an existing grade for that fingerprint.
3. If found, **return it** (no model call).
4. If not found, run the pipeline once, **store** the full result, and return it.

This ensures:
- If it gave **12 once**, it will always return **12** for the same fingerprint.
- You get auditability (store prompts, versions, token usage, timestamps).

---

## Proposed fingerprint design (do later)

### Inputs to include in the fingerprint

At minimum include:

- **submission content**
  - Prefer a stable identifier like:
    - PDF file bytes hash (SHA256 of bytes), OR
    - extracted OCR full text hash (after normalization), OR
    - both (more robust)
- **subject**
- **rubric file version**
  - Hash of the rubric text, or rubric file path + last modified timestamp
- **prompt version**
  - A constant string you bump when prompt changes (e.g., `GRADING_PROMPT_VERSION="2026-01-19-v1"`), or hash of the `instructions` string
- **model identity**
  - model name + provider (e.g., `"grok-4-fast-reasoning"`)

Optional:
- Your scoring rules version (if you change max marks, caps, etc.)

### Fingerprint pseudo-code

```python
import hashlib
import json

def stable_hash(obj) -> str:
    # canonical JSON
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

fingerprint_payload = {
    "pdf_sha256": pdf_bytes_sha256,
    "ocr_sha256": ocr_text_sha256,  # normalized
    "subject": subject,
    "rubric_sha256": rubric_text_sha256,
    "model": model_name,
    "prompt_version": GRADING_PROMPT_VERSION,
}

fingerprint = stable_hash(fingerprint_payload)
```

---

## Storage options for grade freezing

### Option 1: DB (recommended if you already have one)
Store:
- fingerprint (unique)
- grading JSON (full output)
- timestamps + user id + request id
- prompt version + rubric hash + model name

### Option 2: File cache (quick + simple)
Create a folder like:
- `Reports/grade_cache/<fingerprint>.json`

Pros: easy
Cons: concurrency, cleanup, deployment persistence

### Option 3: Object storage
S3-compatible storage (best for scaling)

---

## Where to implement in this project (later)

This repo has multiple “grade_pdf_answer” variants. For production you’ll implement this in the actual execution path you use.

Likely entry points to intercept:

1. Right before calling Grok for grading:
   - check fingerprint cache; return cached grade if present
2. After successful grading:
   - store grade under fingerprint

Also cache:
- OCR results right after Vision OCR completes
- section detection results right after Grok section detection completes

---

## Deterministic scoring vs “better reliability”

These are different:

- **Determinism**: same input ⇒ same output  
  Achieved by: decoding settings + caching/locking

- **Reliability**: score is “correct” and stable under noise  
  Achieved by: rubric alignment, validation, and sometimes:
  - **self-consistency** (run N times and take median/majority), or
  - “judge + verifier” pipelines

Self-consistency improves reliability but **does not** guarantee identical outputs unless you also freeze results.

---

## Acceptance criteria (for later implementation)

When implemented, we should be able to run:

1. Same PDF + same rubric + same prompt version ⇒ **same fingerprint**
2. First run writes `grade_cache[fingerprint]`
3. Next run returns exact same:
   - `total_marks_awarded`
   - per-criterion marks
   - remarks/comments
4. If rubric or prompt version changes ⇒ new fingerprint ⇒ new grade (expected)

---

## Action items (to implement later)

- **Add a constant** `GRADING_PROMPT_VERSION`
- **Set decoding** to deterministic:
  - `temperature=0` and (if supported) `top_p=1`, `seed=<constant>`
- **Normalize OCR text** before hashing
- **Compute fingerprint**
- **Check cache** before running grading
- **Persist grade result** after successful grading
- **Persist OCR + sections** (optional but recommended)

