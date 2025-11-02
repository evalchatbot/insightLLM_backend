#!/usr/bin/env python3
"""
Feedback report builder that renders the template shared by the reviewer.
Sections include: Question Statement, Question Breakdown, Score Table,
Strengths, Areas for Improvement, Key Issues, Model Outline, Final Comments.
"""

import html
from typing import List, TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:
    from typing import Any  # QAReportDetailed will be passed as Any at runtime


def html_escape(s: str) -> str:
    """Escape HTML special characters."""
    return html.escape((s or "").replace("\u00AD", ""))


def _fmt_num(value: float) -> str:
    """Format number for display."""
    try:
        num = float(value)
    except Exception:
        return str(value)
    if abs(num - round(num)) < 1e-6:
        return str(int(round(num)))
    return f"{num:.1f}"


BASE_PAGE_STYLE = """
@page { size: A4; margin: 18mm; }
body {
    font-family: 'Calibri','Helvetica Neue',Arial,sans-serif;
    font-size: 11.5pt;
    line-height: 1.6;
    color: #1f2933;
    background: #ffffff;
    margin: 0;
}
.page {
    display: flex;
    flex-direction: column;
    gap: 10pt;
}
.page-header {
    text-align: center;
    padding-bottom: 6pt;
}
.page-header h1 {
    margin: 0;
    font-size: 18pt;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.subtitle {
    font-size: 11.5pt;
    color: #64748b;
    margin-top: 2pt;
}
.divider {
    height: 2pt;
    background: #0f172a;
    margin: 6pt 0 4pt;
}
.section {
    margin-bottom: 12pt;
}
.section-title {
    font-size: 13pt;
    font-weight: 600;
    margin: 0 0 6pt;
}
.section-subheading {
    font-size: 11.5pt;
    font-weight: 600;
    margin-bottom: 4pt;
    color: #1e293b;
}
.question-box {
    border: 1px solid #cbd5f5;
    background: #f8fafc;
    padding: 8pt 10pt;
    border-radius: 6pt;
    white-space: pre-line;
}
.template-list {
    margin: 0 0 6pt 16pt;
    padding: 0;
}
.template-list li {
    margin-bottom: 4pt;
}
.pen-note {
    margin-top: 6pt;
    background: #eef2ff;
    border-left: 4pt solid #4338ca;
    padding: 6pt 10pt;
    border-radius: 4pt;
    font-size: 11.5pt;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8pt;
    font-size: 11.5pt;
}
th, td {
    border: 1px solid #d1d5db;
    padding: 6pt 8pt;
    vertical-align: top;
}
th {
    background: #f1f5f9;
    font-weight: 600;
    text-align: left;
}
.total-row td {
    background: #fff7ed;
    font-weight: 600;
}
.numbered-list {
    margin: 0 0 6pt 16pt;
    padding: 0;
}
.numbered-list li {
    margin-bottom: 6pt;
}
.issue-table th, .issue-table td {
    font-size: 11.5pt;
}
.model-argument {
    border: 1px solid #dbeafe;
    background: #eff6ff;
    border-radius: 6pt;
    padding: 8pt 10pt;
    margin-bottom: 6pt;
}
.criterion-comment {
    font-size: 11.5pt;
    color: #334155;
}
.final-comments {
    border: 1px solid #cbd5f5;
    background: #f8fafc;
    padding: 10pt 12pt;
    border-radius: 6pt;
}
.small-text {
    font-size: 10.5pt;
    color: #475569;
}
.continued {
    font-size: 10.5pt;
    color: #475569;
    text-align: center;
    margin-top: 4pt;
}
"""


def _wrap_page(page_title: str, content: str, subtitle: Optional[str] = None) -> str:
    """Wrap given body HTML into a standalone A4 page."""
    subtitle_html = f'<div class="subtitle">{html_escape(subtitle)}</div>' if subtitle else ""
    return f"""<html>
<head>
<meta charset="UTF-8">
<style>{BASE_PAGE_STYLE}</style>
</head>
<body>
<div class="page">
  <header class="page-header">
    <h1>{html_escape(page_title)}</h1>
    {subtitle_html}
  </header>
  <div class="divider"></div>
  {content}
</div>
</body>
</html>"""


def _chunk_list(items: Iterable[Any], size: int) -> List[List[Any]]:
    """Split iterable into fixed-size chunks."""
    chunked: List[List[Any]] = []
    current: List[Any] = []
    for item in items or []:
        current.append(item)
        if len(current) >= size:
            chunked.append(current)
            current = []
    if current:
        chunked.append(current)
    return chunked


def build_css_evaluation_report(rep: Any, writing_label: str) -> List[str]:
    """
    Build CSS 20-Marks Question Feedback Report following the provided template.
    Returns a list of HTML strings, each representing one A4 page.
    """

    subtitle = f"Evaluation — Question {rep.number}" if getattr(rep, "number", None) else "Evaluation Summary"
    pages: List[str] = []

    # --- Page 1: Question Statement + Breakdown + Scores ---
    question_statement = f"""
    <section class="section">
        <div class="section-title">Question Statement:</div>
        <div class="question-box">{html_escape(rep.question)}</div>
    </section>
    """

    breakdown_section = f"""
    <section class="section">
        <div class="section-title">1. Question Breakdown and Key Requirements</div>
        {_build_question_breakdown(rep)}
    </section>
    """

    score_section = f"""
    <section class="section">
        <div class="section-title">2. Score Breakdown</div>
        {_build_score_table(rep, writing_label)}
    </section>
    """

    page1_content = question_statement + '<div class="divider"></div>' + breakdown_section
    pages.append(_wrap_page("Feedback Report", page1_content, subtitle))

    # --- Page 2: Score Breakdown ---
    pages.append(_wrap_page("Feedback Report (Continued)", score_section, subtitle))

    # --- Page 3: Strengths ---
    strengths_section = f"""
    <section class="section">
        <div class="section-title">3. Strengths of the Answer</div>
        {_build_strengths_section(rep)}
    </section>
    """
    pages.append(_wrap_page("Feedback Report (Continued)", strengths_section, subtitle))

    # --- Page 4: Areas for Improvement ---
    improvements_section = f"""
    <section class="section">
        <div class="section-title">4. Areas for Improvement</div>
        {_build_improvements_section(rep)}
    </section>
    """
    pages.append(_wrap_page("Feedback Report (Continued)", improvements_section, subtitle))

    # --- Issues Pages ---
    issue_entries = rep.issues or []
    if issue_entries:
        chunk_size = 5
        issue_chunks = _chunk_list(issue_entries, chunk_size)
        for idx, chunk in enumerate(issue_chunks, 1):
            start_index = (idx - 1) * chunk_size + 1
            end_index = start_index + len(chunk) - 1
            issues_section = f"""
            <section class="section">
                <div class="section-title">5. Key Issues / Problems Identified (Items {start_index}–{end_index})</div>
                {_build_issues_table(rep, chunk)}
            </section>
            """
            pages.append(
                _wrap_page(
                    "Feedback Report (Continued)",
                    issues_section,
                    f"{subtitle} | {len(issue_entries)} total issues",
                )
            )
    else:
        issues_section = """
        <section class="section">
            <div class="section-title">5. Key Issues / Problems Identified</div>
            <p>There were no critical issues recorded for this attempt.</p>
        </section>
        """
        pages.append(_wrap_page("Feedback Report (Continued)", issues_section, subtitle))

    # --- Model Answer Outline & Final Comments ---
    final_comment = (
        html_escape(rep.evaluator_final_comments)
        if getattr(rep, "evaluator_final_comments", "")
        else "Overall evaluation comments were not provided."
    )
    final_section = f"""
    <section class="section">
        <div class="section-title">Evaluator’s Final Comments</div>
        <div class="final-comments">{final_comment}</div>
    </section>
    """

    outline_blocks = _build_model_answer_outline(rep)
    for idx, block in enumerate(outline_blocks):
        title_suffix = "" if idx == 0 else " (continued)"
        outline_page = f"""
        <section class="section">
            <div class="section-title">6. Suggested Model Answer Outline (High-Scoring Structure{title_suffix})</div>
            {block}
        </section>
        """
        pages.append(_wrap_page("Feedback Report (Continued)", outline_page, subtitle))
    pages.append(_wrap_page("Feedback Report (Continued)", final_section, subtitle))

    return pages


def _build_question_breakdown(rep: Any) -> str:
    """Build Section 1: Question Breakdown."""
    breakdown = rep.question_breakdown_detailed or "The question requires comprehensive understanding of the topic."

    html_parts = [f'<div class="pen-note">🖋️ {html_escape(breakdown)}</div>']

    if rep.question_requirements:
        html_parts.append('<div class="section-note">Key requirements mapped by the evaluator:</div><ul class="template-list">')
        for req in rep.question_requirements:
            requirement = html_escape(req.get("requirement", "Requirement"))
            expected = html_escape(req.get("expected_approach", "")) if req.get("expected_approach") else ""
            reason = html_escape(req.get("why_it_matters", "")) if req.get("why_it_matters") else ""
            details = requirement
            if expected:
                details += f". Expected approach: {expected}"
            if reason:
                details += f". Why it matters: {reason}"
            html_parts.append(f"<li>{details}</li>")
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _build_score_table(rep: Any, writing_label: str) -> str:
    """Build Section 2: Score Breakdown Table."""
    criterion_data = rep.criterion_labels or []

    if not criterion_data:
        return "<p>Score breakdown not available.</p>"

    table_rows = []
    total_scored = 0.0
    total_max = 0.0

    for i, crit in enumerate(criterion_data):
        criterion_name = html_escape(str(crit.get("label", "Criterion")))
        assessment_focus = html_escape(str(crit.get("detail", "")).split('.')[0]) if crit.get("detail") else ""

        # Get evaluator comment for this criterion
        evaluator_comment = ""
        if i < len(rep.criterion_evaluator_comments):
            evaluator_comment = html_escape(rep.criterion_evaluator_comments[i])
        elif crit.get("detail"):
            evaluator_comment = html_escape(str(crit.get("detail", "")))

        value = _fmt_num(crit.get("value", 0))
        max_marks = _fmt_num(crit.get("max", 0))

        total_scored += float(crit.get("value", 0))
        total_max += float(crit.get("max", 0))

        comment_text = evaluator_comment if evaluator_comment else "Evaluated per rubric indicators."
        table_rows.append(f"""
            <tr>
                <td><strong>{criterion_name}</strong></td>
                <td>{assessment_focus if assessment_focus else criterion_name}</td>
                <td><div class="criterion-comment">{comment_text}</div></td>
                <td style="text-align:center;"><strong>{value} / {max_marks}</strong></td>
            </tr>
        """)

    if getattr(rep, "writing_score_max", 0) > 0:
        writing_value = _fmt_num(rep.writing_score_2_value)
        writing_max = _fmt_num(rep.writing_score_max)
        comment = html_escape(writing_label) if writing_label else "Writing mechanics evaluation"
        table_rows.append(
            f"""
            <tr>
                <td><strong>Expression & Language</strong></td>
                <td>Clarity, grammar, coherence, academic tone</td>
                <td><div class="criterion-comment">{comment}</div></td>
                <td style="text-align:center;"><strong>{writing_value} / {writing_max}</strong></td>
            </tr>
            """
        )

    table_rows.append(f"""
        <tr class="total-row">
            <td colspan="3"><strong>TOTAL MARKS</strong></td>
            <td style="text-align:center;"><strong>{_fmt_num(rep.final_score_20)} / {_fmt_num(rep.score_max)}</strong></td>
        </tr>
    """)

    table_html = f"""
    <table>
        <tr>
            <th style="width:25%;">Criterion</th>
            <th style="width:25%;">Assessment Focus</th>
            <th style="width:35%;">Evaluator Comments</th>
            <th style="width:15%;text-align:center;">Marks (out of)</th>
        </tr>
        {''.join(table_rows)}
    </table>
    """

    return table_html


def _build_strengths_section(rep: Any) -> str:
    """Build Section 4: Strengths."""
    if not rep.strengths:
        return "<p>No specific strengths identified. The answer needs significant improvement across all criteria.</p>"

    met_requirements = [r for r in (rep.question_requirements or []) if r.get("met")]
    html_parts = ['<ol class="numbered-list">']
    for i, strength in enumerate(rep.strengths, 1):
        text = html_escape(strength)
        if met_requirements:
            reference = met_requirements[min(i - 1, len(met_requirements) - 1)]
            req_text = html_escape(reference.get("requirement", "question requirement"))
            why_text = html_escape(reference.get("why_it_matters", "")) if reference.get("why_it_matters") else ""
            text += f" (Directly supports the requirement: {req_text}"
            if why_text:
                text += f"; rationale noted: {why_text}"
            text += ")"
        html_parts.append(f"<li>{text}</li>")
    html_parts.append("</ol>")
    return "\n".join(html_parts)


def _build_improvements_section(rep: Any) -> str:
    """Build Section 5: Areas for Improvement."""
    if not rep.improvements:
        return "<p>No specific improvements identified.</p>"

    unmet_requirements = [r for r in (rep.question_requirements or []) if not r.get("met")]
    missing_points = rep.missing_points or []
    severe_issues = sorted(rep.issues or [], key=lambda x: (int(x.get("impact_points_0to3", 0)), int(x.get("severity_1to5", 0))), reverse=True)

    entries: List[str] = []

    # Start with provided improvements
    for improvement in rep.improvements:
        text = html_escape(improvement)
        entries.append(text)

    # Add unmet requirements not already covered
    for req in unmet_requirements:
        detail = html_escape(req.get("requirement", "prompt requirement"))
        expected = html_escape(req.get("expected_approach", "")) if req.get("expected_approach") else ""
        rationale = html_escape(req.get("why_it_matters", "")) if req.get("why_it_matters") else ""
        text = f"Explicitly address the unmet requirement \"{detail}\"."
        if expected:
            text += f" Required coverage: {expected}."
        if rationale:
            text += f" Importance: {rationale}."
        entries.append(text)

    # Incorporate missing points explicitly
    for mp in missing_points:
        entries.append(f"Integrate the missing point: {html_escape(mp)}.")

    # Highlight top severity issues as improvement tasks
    for issue in severe_issues[:3]:
        problem = html_escape(issue.get("problem", ""))
        fix = html_escape(issue.get("fix", "")) if issue.get("fix") else ""
        location = html_escape(issue.get("location_hint", "")) if issue.get("location_hint") else ""
        summary = f"Resolve the high-impact issue: {problem}"
        if location:
            summary += f" (Location: {location})"
        if fix:
            summary += f". Recommended fix: {fix}"
        entries.append(summary)

    if not entries:
        entries.append("Provide a detailed revision plan focusing on analytical depth, evidence, and alignment with each prompt requirement.")

    html_parts = ['<ol class="numbered-list">']
    for idx, entry in enumerate(entries, 1):
        html_parts.append(f"<li>{entry}</li>")
    html_parts.append("</ol>")
    return "\n".join(html_parts)


def _build_issues_table(rep: Any, issues_subset: Optional[List[dict]] = None) -> str:
    """Build Section 6: Key Issues Table."""
    issues = issues_subset if issues_subset is not None else (rep.issues or [])
    if not issues:
        return "<p>No critical issues identified.</p>"

    table_rows = []
    for issue in issues:
        problem = html_escape(issue.get("problem", ""))
        span = html_escape(issue.get("span", ""))

        # Explanation = why it's a problem + why it matters
        explanation_parts = []
        if problem:
            explanation_parts.append(problem)
        if issue.get("why_it_matters"):
            explanation_parts.append(f"<em>Why it matters:</em> {html_escape(issue.get('why_it_matters'))}")
        explanation = "<br/>".join(explanation_parts)

        # Fix = suggested fix + how to verify + evidence
        fix_parts = []
        if issue.get("fix"):
            fix_parts.append(html_escape(issue.get("fix")))
        if issue.get("how_to_verify"):
            fix_parts.append(f"<em>How to verify:</em> {html_escape(issue.get('how_to_verify'))}")
        if issue.get("evidence_suggestions"):
            ev_list = ", ".join(html_escape(e) for e in issue.get("evidence_suggestions", [])[:3])
            if ev_list:
                fix_parts.append(f"<em>Evidence:</em> {ev_list}")
        fix = "<br/>".join(fix_parts)

        severity = issue.get("severity_1to5")
        impact = issue.get("impact_points_0to3")
        meta_line = ""
        if severity is not None or impact is not None:
            meta_line = f"<div class='small-text'>Severity {severity}/5 · Impact {impact}/3</div>"
        quote_html = f'<div class="small-text">Answer excerpt: "{span}"</div>' if span else ""

        table_rows.append(
            f"""
            <tr>
                <td>
                    <strong>{html_escape(issue.get('category', 'Issue'))}</strong>
                    {meta_line}
                    {quote_html}
                </td>
                <td>{explanation}</td>
                <td>{fix}</td>
            </tr>
            """
        )

    table_html = f"""
    <table class="issue-table">
        <tr>
            <th style="width:30%;">Problem Identified</th>
            <th style="width:35%;">Explanation / Why It's a Problem</th>
            <th style="width:35%;">Suggested Fix / Improvement Strategy</th>
        </tr>
        {''.join(table_rows)}
    </table>
    """

    return table_html


def _build_model_answer_outline(rep: Any) -> List[str]:
    """Build Section 7: Model Answer Outline with 10-12 arguments, chunked across pages."""
    model_outline = rep.model_answer_outline

    if not model_outline or not isinstance(model_outline, dict):
        return ["<p>Model answer outline not available.</p>"]

    blocks: List[str] = []
    current: List[str] = []

    def flush_block() -> None:
        if current:
            blocks.append("\n".join(current))
            current.clear()

    def current_length() -> int:
        return sum(len(part) for part in current)

    # Introduction
    intro = model_outline.get("introduction", {})
    if intro:
        intro_parts = ["<h3>I. Introduction</h3><ul>"]
        if intro.get("key_terms_to_define"):
            terms = ", ".join(html_escape(t) for t in intro.get("key_terms_to_define", []))
            intro_parts.append(f"<li>Define key terms: {terms}</li>")
        if intro.get("thesis_statement"):
            intro_parts.append(f"<li>Present thesis: \"{html_escape(intro.get('thesis_statement'))}\"</li>")
        if intro.get("roadmap"):
            intro_parts.append(f"<li>Roadmap: {html_escape(intro.get('roadmap'))}</li>")
        intro_parts.append("</ul>")
        current.append("\n".join(intro_parts))

    # Background
    if model_outline.get("background_context"):
        background_html = "<h3>II. Background / Context</h3>" + f"<p>{html_escape(model_outline.get('background_context'))}</p>"
        if current_length() > 4000:
            flush_block()
        current.append(background_html)

    # Main Arguments (chunked)
    main_args = model_outline.get("main_arguments", [])
    if main_args:
        arg_chunks = _chunk_list(main_args, 3)
        for idx, chunk in enumerate(arg_chunks):
            section_title = "<h3>III. Main Arguments</h3>" if idx == 0 else "<h3>III. Main Arguments (continued)</h3>"
            chunk_parts = [section_title]
            for arg in chunk:
                arg_num = arg.get("argument_number", 0)
                heading = html_escape(arg.get("heading", f"Argument {arg_num}"))
                chunk_parts.append(f"""
                    <div class="model-argument">
                        <h4>Argument {arg_num}: {heading}</h4>
                        <ul>
                """)
                if arg.get("explanation"):
                    chunk_parts.append(f"<li><strong>Explanation:</strong> {html_escape(arg.get('explanation'))}</li>")
                if arg.get("example"):
                    chunk_parts.append(f"<li><strong>Example:</strong> {html_escape(arg.get('example'))}</li>")
                if arg.get("counterpoint"):
                    chunk_parts.append(f"<li><strong>Counterpoint:</strong> {html_escape(arg.get('counterpoint'))}</li>")
                if arg.get("critical_insight"):
                    chunk_parts.append(f"<li><strong>Critical Insight:</strong> {html_escape(arg.get('critical_insight'))}</li>")
                chunk_parts.append("</ul></div>")

            chunk_html = "\n".join(chunk_parts)
            if idx == 0:
                current.append(chunk_html)
            else:
                flush_block()
                current.append(chunk_html)

    # Critical Evaluation
    crit_eval = model_outline.get("critical_evaluation", {})
    if crit_eval:
        crit_parts = ["<h3>IV. Critical Evaluation</h3><ul>"]
        if crit_eval.get("strengths_of_arguments"):
            crit_parts.append(f"<li><strong>Strengths:</strong> {html_escape(crit_eval.get('strengths_of_arguments'))}</li>")
        if crit_eval.get("limitations_and_weaknesses"):
            crit_parts.append(f"<li><strong>Limitations:</strong> {html_escape(crit_eval.get('limitations_and_weaknesses'))}</li>")
        if crit_eval.get("multiple_perspectives"):
            crit_parts.append(f"<li><strong>Multiple Perspectives:</strong> {html_escape(crit_eval.get('multiple_perspectives'))}</li>")
        crit_parts.append("</ul>")
        if current_length() > 4000:
            flush_block()
        current.append("\n".join(crit_parts))

    # Conclusion
    conclusion = model_outline.get("conclusion", {})
    if conclusion:
        concl_parts = ["<h3>V. Conclusion</h3><ul>"]
        if conclusion.get("summary_of_arguments"):
            concl_parts.append(f"<li>Summarize: {html_escape(conclusion.get('summary_of_arguments'))}</li>")
        if conclusion.get("thesis_reaffirmation"):
            concl_parts.append(f"<li>Reaffirm thesis: {html_escape(conclusion.get('thesis_reaffirmation'))}</li>")
        if conclusion.get("evaluative_closure"):
            concl_parts.append(f"<li>Final insight: {html_escape(conclusion.get('evaluative_closure'))}</li>")
        concl_parts.append("</ul>")
        if current_length() > 4000:
            flush_block()
        current.append("\n".join(concl_parts))

    flush_block()
    return blocks or ["<p>Model answer outline not available.</p>"]
