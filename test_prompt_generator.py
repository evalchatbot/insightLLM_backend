#!/usr/bin/env python3
"""Test prompt generator with Political Science rubric."""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from utils.prompt_generator import generate_prompt_for_subject, generate_user_prompt

def test_prompt_generator():
    """Test prompt generator."""

    print("=" * 80)
    print("TESTING PROMPT GENERATOR")
    print("=" * 80)

    # Generate prompt for Political Science
    print("\n--- Generating System Prompt for Political Science ---\n")

    try:
        system_prompt = generate_prompt_for_subject("Political Science")

        print("[OK] System prompt generated!")
        print(f"\nPrompt length: {len(system_prompt)} characters")
        print(f"Prompt lines: {len(system_prompt.splitlines())} lines")

        # Show first 2000 characters
        print("\n--- System Prompt Preview (first 2000 chars) ---\n")
        print(system_prompt[:2000])
        print("\n... [truncated] ...\n")

        # Check for key components
        print("\n--- Verification ---\n")

        checks = [
            ("Strict marking cap (16/20)", "16/20" in system_prompt or "STRICT MARKING CAP" in system_prompt),
            ("Line-by-line analysis", "line by line" in system_prompt.lower() or "paragraph by paragraph" in system_prompt.lower()),
            ("Specific examples required", "20-30 words" in system_prompt or "EXACT text" in system_prompt),
            ("All 6 dimensions", "EVALUATION CRITERIA" in system_prompt),
            ("Indicator checklist", "INDICATOR CHECKLIST" in system_prompt or "indicators" in system_prompt.lower()),
            ("JSON output structure", "JSON OUTPUT" in system_prompt or "question_breakdown_detailed" in system_prompt),
            ("Model answer outline", "model_answer_outline" in system_prompt),
            ("10-12 arguments", "10-12" in system_prompt),
            ("Minimum 15-25 issues", "15-25" in system_prompt),
            ("Bot instructions", "BOT" in system_prompt or "Detect" in system_prompt)
        ]

        for check_name, check_result in checks:
            status = "[OK]" if check_result else "[FAIL]"
            print(f"  {status} {check_name}")

        all_passed = all(result for _, result in checks)

        # Generate user prompt
        print("\n--- Generating User Prompt ---\n")

        sample_question = "Discuss the concept of social contract theory as propounded by Hobbes, Locke, and Rousseau."
        sample_answer = "Social contract theory is important. Hobbes said life is nasty, brutish and short. Locke believed in natural rights. Rousseau talked about general will."

        user_prompt = generate_user_prompt(sample_question, sample_answer, "Political Science")

        print("[OK] User prompt generated!")
        print(f"\nUser prompt length: {len(user_prompt)} characters")
        print("\n--- User Prompt Preview ---\n")
        print(user_prompt[:500])
        print("\n... [truncated] ...\n")

        if all_passed:
            print("\n" + "=" * 80)
            print("[SUCCESS] ALL TESTS PASSED")
            print("=" * 80)
            return True
        else:
            print("\n" + "=" * 80)
            print("[WARN] Some checks failed - review output")
            print("=" * 80)
            return False

    except Exception as e:
        print(f"[ERROR] Failed to generate prompt: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_prompt_generator()
    sys.exit(0 if success else 1)
