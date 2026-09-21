"""
Report rendering on synthetic data: the shared brand-aware cover page, the essay cover
adapter, PDF merge helpers, page rasterising utilities and the issue-panel overlay.
"""

from __future__ import annotations

import base64
import io

import fitz
import pytest
from PIL import Image

from backend.utils import report_cover as rc
from support.pdfs import page_count, page_text, text_pdf

pytestmark = pytest.mark.pdf


def cover_model(**overrides):
    model = {
        "meta_lines": [[("Subject", "Political Science"), ("Type", "CSS")]],
        "score_value": "12",
        "score_denom": "out of 20",
        "score_pct": 0.6,
        "score_caption": rc.score_caption(0.6),
        "question_label": "Question Statement",
        "question": "Discuss the doctrine of separation of powers in Pakistan.",
        "table_label": "Marks Breakdown",
        "columns": [
            {"title": "Criterion", "key": "category", "w": 0.4, "kind": "cat"},
            {"title": "Obtained", "key": "obtained", "w": 0.2, "align": "center", "kind": "mono_score"},
            {"title": "Remarks", "key": "remarks", "w": 0.4, "kind": "text"},
        ],
        "rows": [
            {"category": "Introduction", "obtained": "2", "remarks": "Clear thesis", "obtained_color": rc.obtained_color(2, 3)},
            {"category": "Analysis", "obtained": "6", "remarks": "Needs case law", "obtained_color": rc.obtained_color(6, 10)},
        ],
        "left_section": {"label": "Key Gaps", "accent": "red", "items": ["No reference to Article 175."]},
        "right_section": {"label": "How to Improve", "accent": "green", "items": ["Cite the Asma Jilani case."]},
        "footer_note": "AI-generated evaluation report",
        "footer_url": "rubric.ai",
    }
    model.update(overrides)
    return model


def _text(doc: fitz.Document) -> str:
    return doc[0].get_text()


def _max_font_size(doc: fitz.Document) -> float:
    sizes = [s["size"] for b in doc[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
    return max(sizes)


@pytest.fixture(autouse=True)
def reset_brand():
    rc.set_report_brand("rubric")
    yield
    rc.set_report_brand("rubric")


# ---------------------------------------------------------------- shared cover page


def test_rubric_cover_is_single_a4_page_with_content():
    doc = rc.build_cover_doc(cover_model(brand="rubric"))
    assert len(doc) == 1
    assert (round(doc[0].rect.width, 2), round(doc[0].rect.height, 2)) == (rc.PAGE_W, rc.PAGE_H)
    text = _text(doc)
    for expected in ("Rubric.ai", "rubric.ai", "12", "separation of powers", "Introduction", "Cite the Asma Jilani case.", "KEY GAPS"):
        assert expected in text
    assert "Lahore CSS Academy" not in text
    # The rubric mark is vector shapes; the only raster is the examiner signature.
    assert len(doc[0].get_images()) == 1


def test_lca_cover_uses_lca_name_logo_and_url():
    doc = rc.build_cover_doc(cover_model(brand="lca"))
    text = _text(doc)
    assert "Lahore CSS Academy" in text
    assert "lca-portal.org" in text
    assert "Rubric.ai" not in text
    assert len(doc[0].get_images()) == 2  # the academy mark PNG + the examiner signature


@pytest.mark.parametrize("brand", ["rubric", "lca"])
def test_signoff_signature_and_remark_on_every_cover(brand):
    remark = "A promising answer that needs sharper case law."
    doc = rc.build_cover_doc(cover_model(brand=brand, signoff_remark=remark))
    assert len(doc) == 1
    assert " ".join(_text(doc).split()).find(remark) != -1
    # Signature sits in the bottom band, right of centre, above the footer.
    sig = [r for xref, *_ in doc[0].get_images() for r in doc[0].get_image_rects(xref) if r.x0 > rc.PAGE_W / 2]
    assert sig and all(r.y0 > rc.PAGE_H * 0.7 and r.y1 < rc.PAGE_H for r in sig)


@pytest.mark.parametrize(
    ("grading", "expected"),
    [
        ({"one_line_remark": "Good structure overall."}, "Good structure overall."),
        ({"one_line_remark": "n/a", "overall_remarks": "Weak ending."}, "Weak ending."),
        ({"one_line_remark": "string"}, ""),
        ({}, ""),
    ],
)
def test_one_line_remark_skips_placeholder_values(grading, expected):
    assert rc.one_line_remark(grading, "one_line_remark", "overall_remarks") == expected


def test_cover_takes_brand_from_worker_thread_when_model_has_none():
    rc.set_report_brand("lca")
    model = cover_model()
    doc = rc.build_cover_doc(model)
    assert model["brand"] == "lca"  # locked into the model for the multi-pass render
    assert "Lahore CSS Academy" in _text(doc)


def test_rating_mode_replaces_numeric_score():
    doc = rc.build_cover_doc(cover_model(brand="rubric", rating_value="Good", score_value="99"))
    text = _text(doc)
    assert "Good" in text and "Overall Assessment" in text
    assert "99" not in text


def test_overlong_content_is_shrunk_to_fit_one_page():
    small = rc.build_cover_doc(cover_model(brand="rubric"))
    # Just over one page at nominal size -> one or two shrink steps (each step re-renders).
    many_rows = [{"category": f"C{i}", "obtained": "1", "remarks": "Long remark " * 8} for i in range(21)]
    big = rc.build_cover_doc(cover_model(brand="rubric", rows=many_rows))
    assert len(big) == 1
    assert _max_font_size(big) < _max_font_size(small)


def test_render_cover_images_matches_requested_width():
    (img,) = rc.render_cover_images(cover_model(brand="rubric"), page_size=(1191, 1684))
    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"
    assert img.width == 1191
    assert abs(img.height - round(1191 * rc.PAGE_H / rc.PAGE_W)) <= 1


def test_render_cover_pdf_writes_one_page(tmp_path):
    out = tmp_path / "nested" / "cover.pdf"
    rc.render_cover_pdf(cover_model(brand="lca"), str(out))
    data = out.read_bytes()
    assert page_count(data) == 1
    assert "Lahore CSS Academy" in page_text(data)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(12, "12"), (12.0, "12"), (7.5, "7.5"), (7.25, "7.2"), ("8", "8"), (None, ""), ("n/a", "n/a")],
)
def test_fmt_num(value, expected):
    assert rc.fmt_num(value) == expected


@pytest.mark.parametrize(
    ("pct", "band"),
    [(0.85, "excellent"), (0.7, "strong"), (0.5, "satisfactory"), (0.45, "needs improvement"), (0.1, "rework needed"), (1.7, "excellent"), (-1, "rework needed")],
)
def test_score_caption_bands(pct, band):
    caption = rc.score_caption(pct)
    assert caption.endswith(band)
    assert caption.startswith(f"{int(round(max(0, min(1, pct)) * 100))}%")


@pytest.mark.parametrize(
    ("awarded", "allocated", "colour"),
    [(0, 5, rc.ZERO_GREY), (3, 5, rc.RED), (5, 5, rc.OK_GREY), ("x", 5, rc.OK_GREY), (2, 0, rc.OK_GREY)],
)
def test_obtained_color(awarded, allocated, colour):
    assert rc.obtained_color(awarded, allocated) == colour


# ---------------------------------------------------------------- essay adapter + merge


@pytest.fixture(scope="module")
def essay():
    from backend.eng_essay import grade_pdf_essay

    return grade_pdf_essay


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("6-8", (6, 8)), ("6–8", (6, 8)), ("6 — 8", (6, 8)), ("6 to 8", (6, 8)), ("8-6", (6, 8)), ("", (0, 0)), ("six-8", (0, 0)), ("1-2-3", (0, 0))],
)
def test_essay_parse_range(essay, raw, expected):
    assert essay._parse_range(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("55-60", 57.5), ("30", 30.0), ("", 0.0), (None, 0.0)])
def test_essay_parse_range_mid(essay, raw, expected):
    assert essay._parse_range_mid(raw) == expected


@pytest.mark.parametrize("brand", ["rubric", "lca"])
def test_essay_cover_renders_for_both_brands(essay, brand):
    grading = {
        "topic": "Climate change is a threat multiplier",
        "total_awarded_range": "34-38",
        "overall_rating": "Average",
        "overall_remarks": "Argument drifts in the middle.",
        "criteria": [
            {"criterion": "Outline", "rating": "Good", "key_comments": "Logical flow"},
            {"criterion": "", "rating": "skip me"},
            {"criterion": "Expression", "key_comments": "Frequent errors"},
        ],
        "reasons_for_low_score": ["Weak conclusion", " "],
        "suggested_improvements_for_higher_score_70_plus": [],
    }
    model = essay._build_essay_cover_model(grading)
    # Name + key comments only: no per-criterion rating column any more.
    assert model["rows"] == [
        {"category": "Outline", "remarks": "Logical flow"},
        {"category": "Expression", "remarks": "Frequent errors"},
    ]
    assert [c["key"] for c in model["columns"]] == ["category", "remarks"]
    assert model["left_section"]["items"] == ["Weak conclusion"]
    assert model["right_section"]["items"] == ["No improvement suggestions provided."]
    assert model["signoff_remark"] == "Argument drifts in the middle."

    model["brand"] = brand
    text = _text(rc.build_cover_doc(model))
    assert "Climate change is a threat multiplier" in text
    assert "Overall Assessment" not in text  # essays have no rating badge
    assert ("Lahore CSS Academy" in text) is (brand == "lca")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Articulation of Stance — 15", "Articulation of Stance"),
        ("Clarity – 10", "Clarity"),
        ("Grammar - 5", "Grammar"),
        ("Grammar-5", "Grammar"),
        ("Section 2 Analysis", "Section 2 Analysis"),
    ],
)
def test_essay_criterion_column_strips_trailing_marks(essay, raw, expected):
    model = essay._build_essay_cover_model({"criteria": [{"criterion": raw, "key_comments": "ok"}]})
    assert model["rows"][0]["category"] == expected


def test_essay_cover_defaults_for_empty_grading(essay):
    model = essay._build_essay_cover_model({})
    assert model["question"] == "No topic provided."
    assert not model.get("rating_value")
    assert model["rows"] == []
    assert model["left_section"]["items"] == ["No specific weaknesses identified."]
    assert model["signoff_remark"] == ""


def test_merge_report_and_answer_pages(essay, tmp_path):
    report = [Image.new("RGB", (400, 566), "white")]
    answer = [Image.new("RGB", (400, 566), (200, 200, 200)), Image.new("L", (400, 566), 128)]
    out = tmp_path / "final.pdf"
    essay.merge_report_and_annotated_answer(report, answer, str(out))
    assert page_count(out.read_bytes()) == 3
    assert essay.pil_images_to_pdf_bytes([]) == b""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("```json\n{\"a\": 1}\n```", '{"a": 1}'), ("```\n[1]\n```", "[1]"), ("  {\"b\": 2} ", '{"b": 2}'), (None, "")],
)
def test_essay_clean_json(essay, raw, expected):
    assert essay.clean_json_from_llm(raw) == expected


def test_essay_json_repair_parses_without_llm_when_possible(essay, tmp_path, monkeypatch):
    def no_llm(*args, **kwargs):
        raise AssertionError("repair round-trip should not be needed")

    monkeypatch.setattr(essay, "_grok_chat", no_llm)
    out = essay.parse_json_with_repair("k", 'Here: {"score": "6-8"} thanks', debug_dir_override=str(tmp_path))
    assert out == {"score": "6-8"}
    assert (tmp_path / "grok_raw.txt").read_text(encoding="utf-8").startswith("Here:")


def test_essay_json_repair_asks_llm_to_fix_invalid_json(essay, tmp_path, monkeypatch):
    calls = []

    def fake_chat(key, messages, temperature):
        calls.append(messages[-1]["content"])
        return {"choices": [{"message": {"content": '```json\n{"fixed": true}\n```'}}]}

    monkeypatch.setattr(essay, "_grok_chat", fake_chat)
    out = essay.parse_json_with_repair("k", "{'fixed': True,}", debug_tag="grading", debug_dir_override=str(tmp_path))
    assert out == {"fixed": True}
    assert "{'fixed': True,}" in calls[0]
    assert (tmp_path / "grading_repaired_attempt1.txt").exists()


def test_essay_json_repair_gives_up(essay, tmp_path, monkeypatch):
    monkeypatch.setattr(essay, "_grok_chat", lambda *a, **k: {"choices": [{"message": {"content": "still not json"}}]})
    with pytest.raises(ValueError, match="Failed to parse Grok JSON after repair attempts"):
        essay.parse_json_with_repair("k", "nope", max_fix_attempts=2, debug_dir_override=str(tmp_path))


# ---------------------------------------------------------------- page utilities / overlay


def test_extract_text_per_page():
    from backend.utils.pdf_utils import extract_text_per_page

    pages = extract_text_per_page(text_pdf(["alpha", "beta"]))
    assert [(p.page_number, p.text) for p in pages] == [(1, "alpha"), (2, "beta")]
    assert extract_text_per_page(b"") == []


def test_pages_to_base64_png_data_urls():
    from backend.utils.pdf_utils import pdf_pages_to_base64_images

    images = pdf_pages_to_base64_images(text_pdf(["a", "b"]), dpi=72)
    assert [i["page"] for i in images] == [1, 2]
    prefix = "data:image/png;base64,"
    assert images[0]["data_url"].startswith(prefix)
    png = Image.open(io.BytesIO(base64.b64decode(images[0]["data_url"][len(prefix):])))
    assert png.size == (595, 842)
    assert pdf_pages_to_base64_images(b"") == []


def test_annotated_pdf_prepends_reports_and_overlays_issues():
    from backend.utils.pdf_renderer import IssueRow, render_annotated_pdf

    issues = [IssueRow(page=1, issue_type="Spelling", original_text="goverment", correction="government", rewrite="-", reason="typo")]
    issues += [IssueRow(page=2, issue_type="Grammar", original_text=f"err{i}", correction="c", rewrite="r", reason="x") for i in range(14)]
    out = render_annotated_pdf(
        original_pdf=text_pdf(["answer page one", "answer page two"]),
        report_pages_html=["<h1>Evaluation Report</h1><p>Score 12/20</p>", "<p>Appendix</p>"],
        issue_rows=issues,
    )
    assert page_count(out) == 4
    assert "Evaluation Report" in page_text(out, 0)
    assert "Appendix" in page_text(out, 1)
    first_answer = page_text(out, 2)
    assert "answer page one" in first_answer
    assert "goverment" in first_answer and "Writing Issues" in first_answer
    assert "+2 additional issues" in page_text(out, 3)


def test_annotated_pdf_requires_input():
    from backend.utils.pdf_renderer import render_annotated_pdf

    with pytest.raises(ValueError):
        render_annotated_pdf(original_pdf=b"", report_pages_html=[], issue_rows=[])
