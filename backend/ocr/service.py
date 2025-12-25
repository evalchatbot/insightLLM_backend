#!/usr/bin/env python3
"""
Grok-powered OCR evaluation service.
"""

from __future__ import annotations

import logging
import tempfile
import os
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

# Import the restored function
from backend.utils.rubric_loader import list_available_subjects as get_subjects_for_dropdown

logger = logging.getLogger(__name__)


@dataclass
class OCRAnnotator:
    """
    Thin wrapper that invokes the Grok pipeline and exposes the old interface.
    """

    def annotate_pdf(
        self,
        *,
        pdf_bytes: bytes,
        original_filename: str,
        subject: str,
        user_id: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        logger.info(
            "Running Grok evaluation for '%s' (%s bytes) subject=%s",
            original_filename,
            len(pdf_bytes),
            subject,
        )

        # Create temporary files for input PDF, output JSON, and output PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as input_pdf, \
             tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output_json, \
             tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output_pdf:
            
            input_pdf_path = input_pdf.name
            output_json_path = output_json.name
            output_pdf_path = output_pdf.name
            
            # Write input bytes
            input_pdf.write(pdf_bytes)
            input_pdf.flush()

        try:
            # Lazy import to avoid loading heavy OCR/vision libs unless needed
            from .grade_pdf_answer import grade_pdf_answer  # type: ignore
            # Call the restored grading function
            # grade_pdf_answer(pdf_path, subject, output_json_path, output_pdf_path)
            grade_pdf_answer(
                pdf_path=input_pdf_path,
                subject=subject,
                output_json_path=output_json_path,
                output_pdf_path=output_pdf_path,
                user_id=user_id,
            )

            # Read back the results
            if os.path.exists(output_pdf_path):
                with open(output_pdf_path, "rb") as f:
                    annotated_pdf_bytes = f.read()
            else:
                raise RuntimeError("Output PDF was not generated.")

            if os.path.exists(output_json_path):
                with open(output_json_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                metadata = {}

            return annotated_pdf_bytes, metadata

        finally:
            # Cleanup temp files
            for path in [input_pdf_path, output_json_path, output_pdf_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {path}: {e}")


def get_all_available_subjects() -> List[Dict[str, str]]:
    return get_subjects_for_dropdown()
