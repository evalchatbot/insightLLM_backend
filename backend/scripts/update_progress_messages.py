#!/usr/bin/env python3
"""Update essay progress messages to user-friendly versions."""

from pathlib import Path


TARGET_FILE = Path(__file__).resolve().parents[1] / "eng_essay" / "grade_pdf_essay.py"

REPLACEMENTS = {
    "Loading environment and rubrics...": "Starting evaluation...",
    "Running OCR (Azure Document Intelligence)...": "Reading your essay...",
    "Preparing images for analysis...": "Analyzing structure...",
    "Analyzing essay structure (outline & flow)...": "Understanding outline & content...",
    "Performing strict grading evaluation...": "Evaluating quality...",
    "Generating detailed annotations...": "Adding feedback...",
    "Saving JSON results...": "Processing results...",
    "Generating report pages...": "Creating report...",
    "Creating annotated PDF...": "Finalizing PDF...",
    "Essay evaluation complete!": "Complete!",
}


def main() -> None:
    content = TARGET_FILE.read_text(encoding="utf-8")
    updated_content = content

    for old, new in REPLACEMENTS.items():
        updated_content = updated_content.replace(f'"{old}"', f'"{new}"')

    TARGET_FILE.write_text(updated_content, encoding="utf-8")

    print("Progress messages updated to user-friendly versions")
    print("\nChanges made:")
    for old, new in REPLACEMENTS.items():
        print(f'  "{old}" -> "{new}"')


if __name__ == "__main__":
    main()
