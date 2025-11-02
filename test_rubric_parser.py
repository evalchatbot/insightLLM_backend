#!/usr/bin/env python3
"""Test rubric parser with Political Science rubric."""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from utils.rubric_parser import load_rubric, get_available_subjects

def test_parser():
    """Test rubric parser."""

    print("=" * 80)
    print("TESTING RUBRIC PARSER")
    print("=" * 80)

    # Test 1: Get available subjects
    print("\n--- Available Subjects ---")
    subjects = get_available_subjects()
    print(f"Found {len(subjects)} subjects:")
    for subject in subjects[:10]:  # First 10
        print(f"  - {subject}")
    if len(subjects) > 10:
        print(f"  ... and {len(subjects) - 10} more")

    # Test 2: Load Political Science rubric
    print("\n" + "=" * 80)
    print("PARSING: Political Science")
    print("=" * 80)

    try:
        rubric = load_rubric("Political Science")

        print(f"\n[OK] Successfully parsed!")
        print(f"\nSubject: {rubric.subject_display_name}")
        print(f"Normalized: {rubric.subject}")
        print(f"Total Marks: {rubric.total_marks}")
        print(f"Dimensions: {len(rubric.dimensions)}")
        print(f"Total Indicators: {rubric.total_indicators}")

        # Show dimensions
        print("\n--- Dimensions ---\n")
        for i, dim in enumerate(rubric.dimensions, 1):
            print(f"{i}. {dim.name}")
            print(f"   Weight: {dim.weight_percent}% | Marks: {dim.max_marks}")
            print(f"   Objective: {dim.objective[:80]}...")
            print(f"   Assessment Focus: {dim.assessment_focus[:80]}...")
            print(f"   Indicators: {len(dim.indicators)}")

            if dim.indicators:
                for j, indicator in enumerate(dim.indicators[:3], 1):  # First 3
                    print(f"      {j}. {indicator[:70]}...")
                if len(dim.indicators) > 3:
                    print(f"      ... and {len(dim.indicators) - 3} more")

            print()

        # Show bot instructions
        print("\n--- Bot Instructions ---")
        print(f"{rubric.bot_instructions[:300]}...")

        # Verify totals
        print("\n--- Verification ---")
        total_marks = sum(dim.max_marks for dim in rubric.dimensions)
        total_weight = sum(dim.weight_percent for dim in rubric.dimensions)

        print(f"Sum of dimension marks: {total_marks} / 20")
        print(f"Sum of dimension weights: {total_weight}% / 100%")

        if abs(total_marks - 20) < 0.1:
            print("[OK] Marks total correct!")
        else:
            print(f"[WARN] Marks total mismatch: {total_marks} != 20")

        if abs(total_weight - 100) < 0.1:
            print("[OK] Weight total correct!")
        else:
            print(f"[WARN] Weight total mismatch: {total_weight}% != 100%")

    except Exception as e:
        print(f"[ERROR] Failed to parse: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 80)
    print("[SUCCESS] ALL TESTS PASSED")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = test_parser()
    sys.exit(0 if success else 1)
