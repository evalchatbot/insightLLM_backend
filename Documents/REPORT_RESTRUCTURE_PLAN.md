# Report Structure Restructure Plan

## Current vs New Structure Comparison

### **Current Report Structure** (3 pages)

**Page 1: Summary**
- Score breakdown table (criteria + scores)
- Executive summary
- Key requirements
- Strengths (list)
- Areas for improvement (list)

**Page 2: Issues**
- Key Problems & How to Fix Them (detailed issues)
- Missing key points

**Page 3: Roadmap**
- Improvement roadmap
- Suggested outline

---

### **New Required Structure** (Single comprehensive report)

1. ✅ **Question Statement** (Already have: `rep.question`)

2. ✅ **Question Breakdown and Key Requirements** (Have as `question_requirements`)
   - Define conceptual scope
   - Identify key themes/dimensions
   - Theoretical/analytical requirements
   - Multiple parts coverage
   - **NEED: More detailed "what ideal answer should cover"**

3. ✅ **Score Breakdown** (Have as `criterion_labels`)
   - **CHANGE FORMAT:** Need table with "Assessment Focus" and "Evaluator Comments" columns
   - **MAKE DYNAMIC:** Criteria vary by subject (already supported)
   - **Current columns:** Criterion | Score | Max | Notes
   - **New columns:** Criterion | Assessment Focus | Evaluator Comments | Marks (out of)

4. ✅ **Strengths of the Answer** (Have as `strengths`)
   - **NEED:** More detailed, numbered list with specific examples
   - **Current:** Generic statements
   - **New:** Specific citations from answer

5. ✅ **Areas for Improvement** (Have as `improvements`)
   - **NEED:** More detailed, numbered list with specific fixes
   - **Current:** Generic suggestions
   - **New:** Specific, actionable improvements

6. ✅ **Key Issues/Problems Identified** (Have as `issues`)
   - **CHANGE FORMAT:** Need table format
   - **Current columns:** Category | Span | Problem | Fix | Severity | Why | How to verify | Evidence | Impact | Location
   - **New columns:** Problem Identified | Explanation/Why It's a Problem | Suggested Fix/Improvement Strategy

7. ❌ **Suggested Model Answer Outline** - **NEW REQUIRED**
   - **Need to add:** Detailed high-scoring structure
   - Format:
     - I. Introduction (define terms, thesis)
     - II. Background/Context
     - III. Main Arguments (10-12 arguments with examples, counterpoints, insights)
     - IV. Critical Evaluation
     - V. Conclusion
   - **Current:** Basic outline with headings/bullets
   - **New:** Full detailed model with 10-12 specific arguments

8. ❌ **Evaluator's Final Comments** - **NEW REQUIRED**
   - Overall assessment paragraph
   - Key takeaway message

---

## Critical Changes Needed

### 1. **Strict Marking (Max 16/20)**
**Current:**
```python
# utils/ocr.py:766-782
content_cap = float(profile.get("content_cap", total_cap or 18))
# Can achieve full 20/20
```

**New:**
```python
# For 20-mark questions, cap at 16 for exceptional answers
achievable_max = 16.0  # Not 20.0
# Even perfect answers capped at 16
```

**Change locations:**
- Subject profiles: `achievable_max: 16.0` (not 20.0)
- Scoring calculation: Enforce cap
- System prompt: Instruct LLM "exceptional answers score 14-16/20, not 18-20"

---

### 2. **Specific Examples Required**

**Current LLM Prompt** (service.py:142-215):
```
"List 3-7 genuine strengths with SPECIFIC citations"
```

**New LLM Prompt:**
```
"For EACH strength/improvement/issue:
- Quote EXACT text (minimum 20-30 words)
- Reference specific paragraph/line
- Show HOW it should have been done
- Provide model example of correct approach
- NO generic feedback allowed"
```

---

### 3. **Line-by-Line, Paragraph-by-Paragraph Analysis**

**New LLM Instruction:**
```
"Conduct deep analysis:
1. Read entire answer line by line
2. Analyze each paragraph separately
3. Check each sentence for accuracy
4. Identify every conceptual gap
5. Mark every structural weakness
6. Note all missing elements
Minimum 15-25 specific issues per answer"
```

---

### 4. **Model Answer Outline (10-12 Arguments)**

**New JSON Schema Field:**
```json
"model_answer_outline": {
  "introduction": {
    "key_terms": ["...", "..."],
    "thesis_statement": "..."
  },
  "background": "...",
  "main_arguments": [
    {
      "argument_number": 1,
      "heading": "...",
      "explanation": "...",
      "example": "...",
      "counterpoint": "..."
    },
    // ... 10-12 arguments total
  ],
  "critical_evaluation": "...",
  "conclusion": "..."
}
```

---

### 5. **New Data Class Fields**

**Add to QAReportDetailed** (utils/ocr.py:91-118):
```python
@dataclass
class QAReportDetailed:
    # ... existing fields ...

    # NEW REQUIRED FIELDS:
    question_breakdown_detailed: str = ""  # What ideal answer should cover
    evaluator_final_comments: str = ""     # Overall assessment
    model_answer_outline: Dict[str, Any] = field(default_factory=dict)  # Detailed model
    criterion_evaluator_comments: List[str] = field(default_factory=list)  # Per-criterion feedback
```

---

## Implementation Plan

### Phase 1: Update Data Structures ✅
- [ ] Add new fields to QAReportDetailed
- [ ] Update JSON schema for LLM responses
- [ ] Add model_answer_outline structure

### Phase 2: Update System Prompts ✅
- [ ] Add strict marking instructions (max 16/20)
- [ ] Require specific examples for all feedback
- [ ] Demand line-by-line analysis
- [ ] Request 10-12 argument model answer

### Phase 3: Update Subject Profiles ✅
- [ ] Change achievable_max from 20 to 16
- [ ] Add detailed scoring guidance
- [ ] Define per-subject criteria with "Assessment Focus"

### Phase 4: Restructure HTML Report ✅
- [ ] Section 1: Question Statement
- [ ] Section 2: Question Breakdown
- [ ] Section 3: Score Breakdown (new table format)
- [ ] Section 4: Strengths (detailed, numbered)
- [ ] Section 5: Areas for Improvement (detailed, numbered)
- [ ] Section 6: Key Issues (table format)
- [ ] Section 7: Model Answer Outline (10-12 arguments)
- [ ] Section 8: Final Comments

### Phase 5: Testing ✅
- [ ] Test with Political Science sample
- [ ] Verify all sections render correctly
- [ ] Check scoring caps at 16/20
- [ ] Validate specific examples present

---

## Code Files to Modify

### 1. **utils/ocr.py**
- Lines 91-118: Add new fields to QAReportDetailed
- Lines 382-470: Update JSON_SCHEMA_CSS_DETAILED
- Lines 650-851: Update evaluate_qa_detailed()
- Lines 859-1142: Completely rewrite build_report_html_pages()

### 2. **ocr/service.py**
- Lines 142-215: Rewrite POLI_SCI_SYSTEM_PROMPT (strict marking)
- Lines 385-438: Update POLITICAL_SCIENCE_PROFILE (achievable_max: 16)
- Similar updates for other subjects

### 3. **New Constants Needed**
```python
# Strict marking enforcement
STRICT_MAX_20_MARKS = 16.0  # Exceptional answers max
STRICT_MAX_100_MARKS = 35.0  # For English essays

# Report structure config
REQUIRED_MODEL_ARGUMENTS = 10  # Minimum arguments in model answer
REQUIRED_ISSUES_MIN = 15       # Minimum issues to identify
REQUIRED_EXAMPLE_WORDS = 20     # Minimum words in quoted examples
```

---

## Subject-Specific Considerations

Each subject will have different:

1. **Criteria** (already supported)
   - Political Science: 6 criteria (Understanding, Knowledge, Analysis, Structure, Examples, Language)
   - Can define per subject

2. **Assessment Focus** (new - need to add)
   - What each criterion evaluates specifically
   - Added to subject profile

3. **Achievable Maximum** (need to change)
   - 20-mark questions: Max 16
   - 100-mark essays: Max 35-40

4. **Model Answer Arguments** (new)
   - Some subjects may need 10-12 arguments
   - Others may need different structure

---

## Next Steps

1. Start with **Political Science** subject
2. Implement all changes for one subject first
3. Test thoroughly
4. Then replicate for other subjects

Would you like me to proceed with implementing Phase 1 (Data Structures)?
