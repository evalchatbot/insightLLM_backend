#!/usr/bin/env python3
"""
Render annotated PDFs by prepending HTML report pages and overlaying issue panels.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - runtime guard
    raise ImportError(
        "PyMuPDF (fitz) is required for PDF annotation. Install it via 'pip install PyMuPDF==1.26.4'."
    ) from exc


@dataclass
class IssueRow:
    page: int
    issue_type: str
    original_text: str
    correction: str
    rewrite: str
    reason: str
    location_hint: str = ""


def _insert_html_page(doc: fitz.Document, html_text: str, base_rect: fitz.Rect) -> None:
    """
    Insert a new page at the front of the document containing the provided HTML.
    """

    page = doc.new_page(pno=0, width=base_rect.width, height=base_rect.height)
    margin = 36
    panel = fitz.Rect(
        margin,
        margin,
        base_rect.width - margin,
        base_rect.height - margin,
    )

    try:
        page.insert_htmlbox(panel, html_text, css="", archive=None, rotate=0)
    except Exception:
        # fallback: plain text insertion so we never fail the pipeline
        page.insert_textbox(panel, html_text, fontsize=11, fontname="helv", color=(0, 0, 0))


def _issues_panel_html(page_number: int, rows: Sequence[IssueRow], max_rows: int = 12) -> str:
    """
    Build a small HTML table describing writing issues for the overlay panel.
    """

    if not rows:
        body = "<p>No surface-level writing issues flagged on this page.</p>"
    else:
        limited = rows[:max_rows]
        body_rows = []
        for issue in limited:
            location_line = f"<div class='loc'>{issue.location_hint}</div>" if issue.location_hint else ""
            body_rows.append(
                "<div class='issue'>"
                f"<div class='type'>{issue.issue_type}</div>"
                f"{location_line}"
                f"<div class='orig'><strong>Original:</strong> {issue.original_text}</div>"
                f"<div class='corr'><strong>Correction:</strong> {issue.correction}</div>"
                f"<div class='rewrite'><strong>Rewrite:</strong> {issue.rewrite}</div>"
                f"<div class='reason'><strong>Why:</strong> {issue.reason}</div>"
                "</div>"
            )
        if len(rows) > max_rows:
            body_rows.append(
                f"<div class='more'>+{len(rows) - max_rows} additional issues</div>"
            )
        body = "".join(body_rows)

    html = f"""
    <html>
      <head>
        <style>
          body {{
            font-family: 'Helvetica', 'Arial', sans-serif;
            font-size: 9.5pt;
            margin: 0;
            padding: 6pt;
            color: #111827;
            background: #fdf8ef;
          }}
          .panel {{
            background: #fffdf5;
            border: 1px solid #fcd9aa;
            border-radius: 6pt;
            padding: 6pt;
            box-shadow: 0 6pt 16pt rgba(249, 115, 22, 0.25);
          }}
          h1 {{
            font-size: 11pt;
            margin: 0 0 6pt 0;
            color: #1f2937;
          }}
          .issue {{
            border-bottom: 1px solid #f1dec6;
            margin-bottom: 5pt;
            padding: 5pt 4pt;
            background: rgba(255, 248, 231, 0.95);
            border-radius: 4pt;
          }}
          .issue:last-child {{
            border-bottom: none;
          }}
          .type {{
            font-weight: 600;
            color: #2563eb;
          }}
          .loc {{
            font-size: 8.5pt;
            color: #6b7280;
            margin-bottom: 2pt;
          }}
          .orig, .corr, .rewrite, .reason {{
            margin-bottom: 2pt;
          }}
          .more {{
            font-size: 8.5pt;
            color: #6b7280;
          }}
        </style>
      </head>
      <body>
        <div class="panel">
          <h1>Writing Issues – Page {page_number}</h1>
          {body}
        </div>
      </body>
    </html>
    """
    return html


def render_annotated_pdf(
    *,
    original_pdf: bytes,
    report_pages_html: Sequence[str],
    issue_rows: Iterable[IssueRow],
) -> bytes:
    """
    Combine the original PDF, prepend report pages, and overlay issue panels.
    """

    if not original_pdf:
        raise ValueError("original_pdf must not be empty")

    issues_by_page: Dict[int, List[IssueRow]] = {}
    for row in issue_rows:
        issues_by_page.setdefault(row.page, []).append(row)

    with fitz.open(stream=io.BytesIO(original_pdf), filetype="pdf") as doc:
        base_rect = doc[0].rect if len(doc) else fitz.Rect(0, 0, 595, 842)

        for html in reversed(list(report_pages_html)):
            _insert_html_page(doc, html, base_rect)

        report_page_count = len(report_pages_html)
        for idx in range(report_page_count, len(doc)):
            page_number = idx - report_page_count + 1
            page = doc[idx]
            rect = page.rect
            panel_width = max(120, rect.width * 0.32)
            margin = 18
            panel_rect = fitz.Rect(
                rect.x1 - panel_width - margin,
                margin,
                rect.x1 - margin,
                rect.y1 - margin,
            )

            overlay_html = _issues_panel_html(
                page_number,
                issues_by_page.get(page_number, []),
            )
            try:
                page.insert_htmlbox(panel_rect, overlay_html, overlay=True, scale_low=0.75)
            except Exception:
                page.insert_textbox(
                    panel_rect,
                    "Unable to render issue overlay.",
                    fontsize=10,
                    fontname="helv",
                    color=(0, 0, 0),
                )

        buffer = io.BytesIO()
        doc.save(buffer, deflate=True)
        return buffer.getvalue()
