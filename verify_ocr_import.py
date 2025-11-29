import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath("d:/css_proj/insightLLM_backend"))

try:
    from backend.ocr.service import OCRAnnotator, get_all_available_subjects
    print("Successfully imported OCRAnnotator and get_all_available_subjects")
    
    annotator = OCRAnnotator()
    print("Successfully instantiated OCRAnnotator")
    
    subjects = get_all_available_subjects()
    print(f"Found {len(subjects)} subjects")
    if subjects:
        print(f"First subject: {subjects[0]}")
        
except ImportError as e:
    print(f"Verification failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
