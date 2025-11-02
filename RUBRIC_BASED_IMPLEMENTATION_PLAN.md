# Rubric-Based Evaluation Implementation Plan

## Summary of Rubric Structure (Discovered from Word Docs)

### **All 24 Subjects Follow Same Structure:**

**Title:** "CSS [Subject] Evaluation Rubric (For Bot Assessment)"

**Total:** 100% = 20 Marks per question

**Components:**
1. **8 Tables** with dimension breakdowns
2. **6 Dimensions (Criteria)** with specific weights
3. **Each Dimension Contains:**
   - Name (e.g., "Understanding of Question and Relevance")
   - Weight (% and marks, e.g., "20% = 4 marks")
   - **Objective** - What this criterion assesses
   - **Indicators** - Specific checklist items to look for

4. **Special Section:** "For Bot Integration" with AI-specific instructions

---

## Example: Political Science Rubric Structure

### Dimension 1: Understanding of Question and Relevance (4 Marks / 20%)
**Objective:** Gauge how well the student identifies what the question demands

**Indicators:**
- Correctly identifies whether the question pertains to political theory, ideology, institutional comparison, or philosophical interpretation
- Addresses all parts of the question (causes, effects, evaluation)
- Subheadings correspond directly with question components
- Avoids irrelevant historical or ideological tangents

### Dimension 2: Conceptual Clarity and Theoretical Depth (5 Marks / 25%)
**Objective:** Assess depth of understanding of Western and Muslim political thought

**Indicators:**
- Clear definitions and distinctions between concepts (e.g., sovereignty vs. liberty)
- Correctly references key thinkers and theories (Plato, Locke, Marx, Iqbal)
- Demonstrates understanding of Islamic political concepts (Shura, Khilafah, Ummah)
- Integrates both classical and contemporary perspectives

### Dimension 3: Critical Analysis and Argumentation (4 Marks / 20%)
**Objective:** Measure ability to analyze, critique, and form independent arguments

**Indicators:**
- Evaluates strengths and weaknesses of political ideas
- Offers comparative insights between thinkers (Locke vs. Hobbes; Iqbal vs. Rida)
- Demonstrates critical engagement rather than rote reproduction
- Presents independent judgment supported by logical reasoning

### Dimension 4: Comparative Insight and Application (2 Marks / 10%)
**Objective:** Test student's ability to connect theory to practice

**Indicators:**
- Draws cross-contextual comparisons (e.g., UK parliamentary vs. U.S. presidential)
- Applies theoretical frameworks to modern contexts
- Demonstrates understanding of political systems of various countries
- Relates ideologies and theories to Pakistan's political evolution

### Dimension 5: Structure, Organization, and Coherence (3 Marks / 15%)
**Objective:** Evaluate flow, formatting, and logical structure

**Indicators:**
- Uses Introduction–Body–Conclusion format
- Each major heading derived from question keywords
- Headings convey cause–effect or analytical meaning
- Smooth transitions and paragraph coherence
- Balanced coverage of subtopics

### Dimension 6: Language, Expression, and Scholarly Tone (2 Marks / 10%)
**Objective:** Assess linguistic quality and academic tone

**Indicators:**
- Formal, neutral, and analytical language
- Uses political terminology correctly (legitimacy, sovereignty, hegemony)
- Avoids ideological bias or emotional tone
- Grammatically sound, coherent sentences

### Bot Integration Instructions (from Rubric)
The AI evaluator should:
- Detect thinker names and ideologies (Plato, Locke, Marx, Iqbal, etc.)
- Identify thematic keywords: "justice," "liberty," "social contract," "state"
- Recognize comparative markers: "in contrast," "whereas," "however"
- Track argument balance: check if opposing views represented
- Flag bias or descriptive-only responses
- Detect intro-body-conclusion and subheading presence

---

## Implementation Architecture

### Phase 1: Rubric Parser System ✅

**File:** `backend/utils/rubric_parser.py`

```python
class RubricParser:
    """Parse Word doc rubrics and extract structured data."""

    def parse_rubric(self, docx_path: Path) -> RubricStructure:
        """Extract all dimensions, indicators, and instructions."""
        return RubricStructure(
            subject="Political Science",
            total_marks=20,
            dimensions=[
                RubricDimension(
                    name="Understanding of Question and Relevance",
                    weight_percent=20,
                    max_marks=4,
                    objective="Gauge how well...",
                    indicators=[
                        "Correctly identifies...",
                        "Addresses all parts...",
                        # etc
                    ]
                ),
                # ... more dimensions
            ],
            bot_instructions="Detect thinker names..."
        )
```

**Data Classes:**
```python
@dataclass
class RubricIndicator:
    text: str
    dimension: str

@dataclass
class RubricDimension:
    name: str
    weight_percent: float
    max_marks: float
    objective: str
    indicators: List[str]
    assessment_focus: str  # For report table

@dataclass
class RubricStructure:
    subject: str
    total_marks: int
    dimensions: List[RubricDimension]
    bot_instructions: str
    all_indicators: List[RubricIndicator]  # Flattened for easy access
```

---

### Phase 2: Dynamic System Prompt Generator ✅

**File:** `backend/utils/prompt_generator.py`

```python
class PromptGenerator:
    """Generate LLM system prompts from rubric structure."""

    def generate_system_prompt(self, rubric: RubricStructure) -> str:
        """Create detailed system prompt from rubric."""
        prompt = f"""You are a strict CSS {rubric.subject} examiner.

CRITICAL INSTRUCTIONS:
1. Maximum achievable score: 16/20 (even for exceptional answers)
2. Conduct LINE-BY-LINE, PARAGRAPH-BY-PARAGRAPH deep analysis
3. Follow ALL indicators rigorously
4. Provide SPECIFIC examples with EXACT quotes (minimum 20-30 words)
5. Show HOW each issue should have been fixed
6. Identify minimum 15-25 specific issues per answer

EVALUATION CRITERIA (Total: {rubric.total_marks} marks):

"""
        # Add each dimension with indicators
        for dim in rubric.dimensions:
            prompt += f"""
{dim.name} ({dim.max_marks} marks / {dim.weight_percent}%)
Objective: {dim.objective}

INDICATORS TO CHECK:
"""
            for indicator in dim.indicators:
                prompt += f"  • {indicator}\n"

        prompt += f"""

BOT-SPECIFIC INSTRUCTIONS:
{rubric.bot_instructions}

REQUIRED OUTPUT:
Generate a comprehensive JSON response with:
1. Question breakdown (what ideal answer should cover)
2. Per-criterion scores with evaluator comments
3. Detailed strengths (with quotes and examples)
4. Detailed improvements (with specific fixes)
5. Key issues table (Problem | Explanation | Fix)
6. Model answer outline with 10-12 detailed arguments
7. Final evaluator comments (overall assessment)

Be EXCEPTIONALLY STRICT. Most answers score 10-14/20. Only truly outstanding work reaches 14-16/20.
"""
        return prompt
```

---

### Phase 3: Multi-Pass Indicator-Based Evaluation ✅

**File:** `backend/utils/indicator_evaluator.py`

```python
class IndicatorEvaluator:
    """Deep evaluation following rubric indicators."""

    def evaluate_answer(
        self,
        question: str,
        answer: str,
        rubric: RubricStructure,
        groq_client: Groq
    ) -> DetailedEvaluation:
        """
        Multi-pass evaluation:
        1. Overall assessment (single LLM call with full prompt)
        2. Per-dimension indicator checks (6 LLM calls, one per dimension)
        3. Model answer generation (separate LLM call)
        4. Final synthesis (combine all results)
        """

        # Pass 1: Overall assessment with full rubric
        overall = self._evaluate_overall(question, answer, rubric, groq_client)

        # Pass 2: Deep dive per dimension (optional, if strict mode)
        dimension_analyses = []
        for dim in rubric.dimensions:
            analysis = self._evaluate_dimension(
                question, answer, dim, groq_client
            )
            dimension_analyses.append(analysis)

        # Pass 3: Generate model answer with 10-12 arguments
        model_answer = self._generate_model_answer(
            question, rubric, groq_client
        )

        # Pass 4: Synthesize all results
        return self._synthesize_evaluation(
            overall, dimension_analyses, model_answer
        )
```

---

### Phase 4: Updated Report Structure ✅

**New 8-Section HTML Report:**

```html
<!-- Section 1: Question Statement -->
<div class="section">
  <h2>Question Statement</h2>
  <p class="question">{question_text}</p>
</div>

<!-- Section 2: Question Breakdown and Key Requirements -->
<div class="section">
  <h2>1. Question Breakdown and Key Requirements</h2>
  <h3>What the question demanded:</h3>
  <ul>
    <li>Define the conceptual scope...</li>
    <li>Identify key themes...</li>
    <!-- From LLM analysis -->
  </ul>
</div>

<!-- Section 3: Score Breakdown -->
<div class="section">
  <h2>2. Score Breakdown</h2>
  <table>
    <tr>
      <th>Criterion</th>
      <th>Assessment Focus</th>
      <th>Evaluator Comments</th>
      <th>Marks (out of)</th>
    </tr>
    <!-- Dynamic rows from rubric.dimensions -->
    <tr>
      <td>Understanding & Relevance</td>
      <td>How well the question was understood</td>
      <td>{specific_feedback_from_LLM}</td>
      <td>3 / 4</td>
    </tr>
    <!-- ... more rows -->
    <tr class="total-row">
      <td colspan="3"><strong>TOTAL MARKS</strong></td>
      <td><strong>14 / 20</strong></td>
    </tr>
  </table>
</div>

<!-- Section 4: Strengths of the Answer -->
<div class="section">
  <h2>3. Strengths of the Answer</h2>
  <ol>
    <li>
      <strong>Specific strength with quote:</strong>
      <blockquote>"Exact text from answer showing this strength..."</blockquote>
      <p>Why this is good: Explanation...</p>
    </li>
    <!-- More strengths -->
  </ol>
</div>

<!-- Section 5: Areas for Improvement -->
<div class="section">
  <h2>4. Areas for Improvement</h2>
  <ol>
    <li>
      <strong>Specific area needing work:</strong>
      <blockquote>"Quote showing the problem..."</blockquote>
      <p>How to fix: Detailed improvement strategy...</p>
    </li>
    <!-- More improvements -->
  </ol>
</div>

<!-- Section 6: Key Issues/Problems Identified -->
<div class="section">
  <h2>5. Key Issues / Problems Identified</h2>
  <table>
    <tr>
      <th>Problem Identified</th>
      <th>Explanation / Why It's a Problem</th>
      <th>Suggested Fix / Improvement Strategy</th>
    </tr>
    <!-- Dynamic rows from LLM -->
    <tr>
      <td>Missing definition of "sovereignty"</td>
      <td>Question explicitly asks to define key terms. Omission shows incomplete understanding.</td>
      <td>Add paragraph: "Sovereignty refers to... As Hobbes argues in Leviathan..."</td>
    </tr>
    <!-- More issues -->
  </table>
</div>

<!-- Section 7: Suggested Model Answer Outline -->
<div class="section">
  <h2>6. Suggested Model Answer Outline (High-Scoring Structure)</h2>

  <h3>I. Introduction</h3>
  <ul>
    <li>Define key terms: sovereignty, legitimacy, authority</li>
    <li>Present thesis: "This essay argues that..."</li>
  </ul>

  <h3>II. Background / Context</h3>
  <ul>
    <li>Brief historical evolution of the concept</li>
  </ul>

  <h3>III. Main Arguments</h3>

  <h4>Argument 1: Classical Foundations</h4>
  <ul>
    <li><strong>Explanation:</strong> Plato's conception in The Republic...</li>
    <li><strong>Example:</strong> The philosopher-king model demonstrates...</li>
    <li><strong>Counterpoint:</strong> Critics argue this approach is elitist...</li>
  </ul>

  <h4>Argument 2: Social Contract Theory</h4>
  <ul>
    <li><strong>Explanation:</strong> Hobbes, Locke, and Rousseau offer...</li>
    <li><strong>Example:</strong> Locke's Two Treatises specifically...</li>
    <li><strong>Critical Insight:</strong> Comparing Hobbes vs. Locke reveals...</li>
  </ul>

  <!-- Arguments 3-12 with same structure -->

  <h3>IV. Critical Evaluation</h3>
  <ul>
    <li>Discuss strengths: theoretical rigor, historical evidence</li>
    <li>Discuss weaknesses: applicability to modern contexts</li>
    <li>Multiple perspectives: Western vs. Islamic political thought</li>
  </ul>

  <h3>V. Conclusion</h3>
  <ul>
    <li>Summarize main arguments (1-2 sentences each)</li>
    <li>Reaffirm thesis with nuance</li>
    <li>Present evaluative closure: "While X provides..., ultimately..."</li>
  </ul>
</div>

<!-- Section 8: Evaluator's Final Comments -->
<div class="section">
  <h2>Evaluator's Final Comments</h2>
  <p>{comprehensive_overall_assessment_paragraph}</p>
</div>
```

---

## File Structure Changes

### New Files to Create:
```
backend/utils/
├── rubric_parser.py          # Parse Word doc rubrics
├── prompt_generator.py       # Generate LLM prompts from rubrics
├── indicator_evaluator.py    # Multi-pass evaluation
└── report_builder.py         # New 8-section HTML builder
```

### Files to Modify:
```
backend/ocr/service.py
├── Remove hardcoded POLI_SCI_SYSTEM_PROMPT
├── Remove hardcoded ENGLISH_ESSAY_*_PROMPTS
├── Remove SUBJECT_PROFILES dict
├── Add: load_rubric_for_subject(subject_name)
└── Use dynamic prompt generation

backend/utils/ocr.py
├── Add new fields to QAReportDetailed
├── Update JSON schema (make dynamic)
├── Replace build_report_html_pages() entirely
└── Add strict marking cap (max 16/20)
```

### Rubrics Directory (already exists):
```
backend/Rubrics/
├── Political Science Rubric/
│   └── Political Science.docx
├── IR/
│   └── International Relations.docx
├── Psychology/
│   └── Psychology.docx
└── ... (21 more subjects)
```

---

## Implementation Steps

### Step 1: Create Rubric Parser ✅
- Parse .docx files
- Extract dimensions, indicators, objectives
- Extract "For Bot Integration" instructions
- Cache parsed rubrics (don't parse every time)

### Step 2: Dynamic Prompt Generator ✅
- Generate system prompts from rubric structure
- Include all indicators as checklist
- Add strict marking instructions
- Add requirement for specific examples

### Step 3: Update Data Structures ✅
- Add fields to QAReportDetailed:
  - question_breakdown_detailed: str
  - evaluator_final_comments: str
  - model_answer_outline: Dict
  - criterion_evaluator_comments: List[str]

### Step 4: Multi-Pass Evaluation ✅
- Pass 1: Overall assessment
- Pass 2: Per-dimension deep dive (if needed)
- Pass 3: Model answer generation
- Pass 4: Synthesis

### Step 5: New Report Builder ✅
- 8-section HTML structure
- Dynamic tables from rubric dimensions
- Specific examples with quotes
- Model answer with 10-12 arguments

### Step 6: Remove Hardcoded Prompts ✅
- Delete POLI_SCI_SYSTEM_PROMPT
- Delete ENGLISH_ESSAY_*_PROMPTS
- Delete SUBJECT_PROFILES
- Use rubric-based approach

### Step 7: Testing ✅
- Test with Political Science rubric
- Verify all 6 dimensions evaluated
- Check all indicators followed
- Validate report structure

---

## Next Action

**Shall I start with Step 1: Create the Rubric Parser?**

This will:
1. Parse the Word doc structure
2. Extract all dimensions and indicators
3. Create structured Python objects
4. Cache results for performance

Then we'll move to Step 2 (Dynamic Prompt Generator).
