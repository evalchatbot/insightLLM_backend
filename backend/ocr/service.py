#!/usr/bin/env python3
"""
Grok-powered OCR evaluation service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from backend.utils.grok_pipeline import (
    EvaluationResult,
    get_subjects_for_dropdown,
    run_grok_pipeline,
)

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
    ) -> Tuple[bytes, Dict[str, Any]]:
        logger.info(
            "Running Grok evaluation for '%s' (%s bytes) subject=%s",
            original_filename,
            len(pdf_bytes),
            subject,
        )
        result: EvaluationResult = run_grok_pipeline(
            pdf_bytes=pdf_bytes,
            subject_id=subject,
            original_filename=original_filename,
        )
        return result.annotated_pdf, result.metadata


def get_all_available_subjects() -> List[Dict[str, str]]:
    return get_subjects_for_dropdown()
