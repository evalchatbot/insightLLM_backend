#!/usr/bin/env python3
"""
Rubric-Based Evaluator - Conduct LLM evaluation using rubric criteria.

Uses dynamic prompts and schemas generated from rubric structure.
"""

from typing import Dict, Any, Tuple, Optional
import logging

from groq import Groq

from .rubric_parser import RubricStructure, load_rubric
from .prompt_generator import PromptGenerator, generate_user_prompt
from .ocr import QAReportDetailed, QAItem, IssueRow

logger = logging.getLogger(__name__)


class RubricEvaluator:
    """Evaluate answers using rubric-based prompts and strict marking."""

    # Supported models for JSON schema mode
    # Note: Most Groq models don't actually support json_schema, only json_object
    SCHEMA_MODELS = {
        "openai/gpt-4o",
        "openai/gpt-4o-mini"
    }

    def __init__(
        self,
        groq_client: Groq,
        subject: str,
        model: str = "llama-3.3-70b-versatile"
    ):
        """
        Initialize evaluator for a subject.

        Args:
            groq_client: Groq API client
            subject: Subject name (e.g., "Political Science")
            model: Groq model ID
        """
        self.groq_client = groq_client
        self.model = model
        self.subject = subject

        # Load rubric and generate prompts/schema
        self.rubric = load_rubric(subject)
        self.prompt_generator = PromptGenerator(self.rubric)
        self.system_prompt = self.prompt_generator.generate_system_prompt()
        self.json_schema = self.prompt_generator.generate_json_schema()

        # Check if model supports JSON schema
        self.use_schema = model in self.SCHEMA_MODELS

        logger.info(
            f"RubricEvaluator initialized for {subject}: "
            f"{len(self.rubric.dimensions)} dimensions, "
            f"{self.rubric.total_indicators} indicators, "
            f"schema_mode={self.use_schema}"
        )

    def evaluate_answer(
        self,
        qa: QAItem,
        writing_value: float,
        writing_label: str
    ) -> Tuple[QAReportDetailed, str]:
        """
        Evaluate answer using rubric criteria.

        Args:
            qa: Question and answer item
            writing_value: Writing score value
            writing_label: Writing score label

        Returns:
            (QAReportDetailed, writing_label)
        """
        # Generate user prompt
        user_prompt = generate_user_prompt(
            qa.question,
            qa.answer,
            self.rubric.subject_display_name
        )

        # Call LLM with rubric-based evaluation
        logger.info(f"Evaluating answer for Q{qa.number} using {self.model}")

        evaluation_data = self._call_llm(user_prompt)

        # Extract scores from dynamic dimension keys
        scores_dict = evaluation_data.get("scores", {})
        dimension_scores = self._extract_dimension_scores(scores_dict)

        # Calculate content score
        content_score = sum(dimension_scores.values())

        # Apply strict marking cap (16/20 for 20-mark questions)
        achievable_max = self.prompt_generator.STRICT_MAX_20_MARKS
        if self.rubric.total_marks == 20:
            content_score = min(content_score, achievable_max)

        # Calculate final score
        writing_max = 0.0  # Writing is separate, not included in 20 marks
        final_score = content_score  # For 20-mark questions, no writing component

        # Build report
        report = self._build_report(
            qa=qa,
            evaluation_data=evaluation_data,
            dimension_scores=dimension_scores,
            content_score=content_score,
            writing_value=writing_value,
            writing_label=writing_label,
            final_score=final_score
        )

        logger.info(
            f"Evaluation complete: Q{qa.number} scored {final_score}/{self.rubric.total_marks} "
            f"(content: {content_score}, {len(report.issues)} issues identified)"
        )

        return report, writing_label

    def _call_llm(self, user_prompt: str) -> Dict[str, Any]:
        """
        Call Groq LLM with rubric-based prompt.

        Args:
            user_prompt: User prompt with question and answer

        Returns:
            Parsed JSON response from LLM
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            if self.use_schema:
                # Use JSON schema mode for strict validation
                response = self.groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": self.json_schema
                    },
                    temperature=0.1,
                    timeout=120
                )
            else:
                # Fallback to json_object mode
                response = self.groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    timeout=120
                )

            content = response.choices[0].message.content or "{}"

            # Parse JSON
            import json
            import re

            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                else:
                    # Try to find any JSON object
                    match = re.search(r'\{.*\}', content, re.DOTALL)
                    if match:
                        data = json.loads(match.group(0))
                    else:
                        raise ValueError("No valid JSON found in LLM response")

            return data

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Return minimal valid response
            return self._get_fallback_response()

    def _extract_dimension_scores(self, scores_dict: Dict[str, int]) -> Dict[str, int]:
        """
        Extract dimension scores from dynamic score keys.

        Args:
            scores_dict: Dict with dynamic keys like "understanding_0to4": 3

        Returns:
            Dict mapping dimension_name -> score
        """
        dimension_scores = {}

        for dim in self.rubric.dimensions:
            # Find matching key in scores_dict
            key = self.prompt_generator._dimension_to_key(dim.name)

            if key in scores_dict:
                score = scores_dict[key]
                # Clamp to dimension max
                score = max(0, min(int(dim.max_marks), int(score)))
            else:
                # Try to find by similar key (case-insensitive, fuzzy match)
                score = 0
                for k, v in scores_dict.items():
                    if key.lower() in k.lower() or k.lower() in key.lower():
                        score = max(0, min(int(dim.max_marks), int(v)))
                        break

            dimension_scores[dim.name] = score

        return dimension_scores

    def _build_report(
        self,
        qa: QAItem,
        evaluation_data: Dict[str, Any],
        dimension_scores: Dict[str, int],
        content_score: float,
        writing_value: float,
        writing_label: str,
        final_score: float
    ) -> QAReportDetailed:
        """Build QAReportDetailed from evaluation data."""

        # Extract criterion comments (should match number of dimensions)
        criterion_comments = evaluation_data.get("criterion_evaluator_comments", [])
        if len(criterion_comments) < len(self.rubric.dimensions):
            # Pad with empty strings
            criterion_comments.extend(
                [""] * (len(self.rubric.dimensions) - len(criterion_comments))
            )

        # Build criterion_labels with scores and comments
        criterion_labels = []
        for i, dim in enumerate(self.rubric.dimensions):
            criterion_labels.append({
                "attr": dim.name.lower().replace(" ", "_"),
                "label": dim.name,
                "value": dimension_scores.get(dim.name, 0),
                "max": dim.max_marks,
                "detail": criterion_comments[i] if i < len(criterion_comments) else dim.assessment_focus
            })

        # Extract model answer outline
        model_outline = evaluation_data.get("model_answer_outline", {})

        # Create report
        report = QAReportDetailed(
            number=qa.number,
            question=qa.question,
            answer_full=qa.answer,
            relevance=dimension_scores.get(self.rubric.dimensions[0].name, 0) if len(self.rubric.dimensions) > 0 else 0,
            coverage=dimension_scores.get(self.rubric.dimensions[1].name, 0) if len(self.rubric.dimensions) > 1 else 0,
            accuracy=dimension_scores.get(self.rubric.dimensions[2].name, 0) if len(self.rubric.dimensions) > 2 else 0,
            analysis=dimension_scores.get(self.rubric.dimensions[3].name, 0) if len(self.rubric.dimensions) > 3 else 0,
            organization=dimension_scores.get(self.rubric.dimensions[4].name, 0) if len(self.rubric.dimensions) > 4 else 0,
            content_score_18=content_score,
            writing_score_2_value=writing_value,
            final_score_20=final_score,
            strengths=evaluation_data.get("strengths", []),
            improvements=evaluation_data.get("improvements", []),
            issues=evaluation_data.get("issues", []),
            missing_points=evaluation_data.get("missing_points", []),
            suggested_outline=[],  # Will be replaced with model_answer_outline
            question_summary=evaluation_data.get("question_summary", ""),
            answer_summary=evaluation_data.get("answer_summary", ""),
            question_requirements=evaluation_data.get("question_requirements", []),
            improvement_plan=evaluation_data.get("improvement_plan", []),
            content_score_max=self.rubric.total_marks,
            writing_score_max=0.0,  # No writing component for 20-mark questions
            score_max=self.rubric.total_marks,
            final_score_cap=self.prompt_generator.STRICT_MAX_20_MARKS,
            criterion_labels=criterion_labels,
            # NEW FIELDS
            question_breakdown_detailed=evaluation_data.get("question_breakdown_detailed", ""),
            evaluator_final_comments=evaluation_data.get("evaluator_final_comments", ""),
            model_answer_outline=model_outline,
            criterion_evaluator_comments=criterion_comments
        )

        return report

    def _get_fallback_response(self) -> Dict[str, Any]:
        """Get minimal valid response for error cases."""
        return {
            "question_breakdown_detailed": "Evaluation failed - unable to process answer.",
            "question_summary": "",
            "answer_summary": "",
            "scores": {dim.name.lower().replace(" ", "_"): 0 for dim in self.rubric.dimensions},
            f"content_score_{self.rubric.total_marks}": 0,
            "criterion_evaluator_comments": [""] * len(self.rubric.dimensions),
            "strengths": [],
            "improvements": ["Unable to evaluate - please try again."],
            "issues": [],
            "missing_points": [],
            "question_requirements": [],
            "improvement_plan": [],
            "model_answer_outline": {
                "introduction": {"thesis_statement": ""},
                "main_arguments": [],
                "conclusion": {"thesis_reaffirmation": ""}
            },
            "evaluator_final_comments": "Evaluation could not be completed."
        }
