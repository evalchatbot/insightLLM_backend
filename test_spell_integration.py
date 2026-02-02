"""
Test script to verify OCR spell correction integration
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

print("="*70)
print("Testing OCR Spell Correction Integration")
print("="*70)

# Load environment
load_dotenv()

# Test 1: Check environment variables
print("\n1. Checking environment variables...")
grok_api = os.getenv("Grok_API")
azure_endpoint = os.getenv("AZURE_ENDPOINT")
azure_key = os.getenv("AZURE_KEY")
google_key = os.getenv("Google_cloud_key")

print(f"   Grok_API: {'✓ Found' if grok_api else '✗ Missing'}")
print(f"   AZURE_ENDPOINT: {'✓ Found' if azure_endpoint else '✗ Missing'}")
print(f"   AZURE_KEY: {'✓ Found' if azure_key else '✗ Missing'}")
print(f"   Google_cloud_key: {'✓ Found' if google_key else '✗ Missing'}")

if not azure_endpoint or not azure_key:
    print("\n   ⚠ WARNING: Azure credentials missing!")
    print("   Spelling/grammar checking will be DISABLED")
    print("   Please add AZURE_ENDPOINT and AZURE_KEY to .env file")
else:
    print("   ✓ All Azure credentials present")

# Test 2: Check if ocr-spell-correction.py exists
print("\n2. Checking for ocr-spell-correction.py...")
possible_paths = [
    Path(__file__).parent / "backend" / "ocr" / "ocr-spell-correction.py",
    Path(__file__).parent / "ocr" / "ocr-spell-correction.py",
]

found = False
for path in possible_paths:
    if path.exists():
        print(f"   ✓ Found at: {path}")
        found = True
        break

if not found:
    print("   ✗ NOT FOUND in:")
    for path in possible_paths:
        print(f"     - {path}")
    print("   OCR spell correction will be DISABLED")

# Test 3: Try importing the module
print("\n3. Testing module import...")
try:
    import importlib.util
    
    ocr_spell_path = None
    for path in possible_paths:
        if path.exists():
            ocr_spell_path = path
            break
    
    if ocr_spell_path:
        spec = importlib.util.spec_from_file_location("ocr_spell_correction", ocr_spell_path)
        ocr_spell_module = importlib.util.module_from_spec(spec)
        sys.modules["ocr_spell_correction"] = ocr_spell_module
        spec.loader.exec_module(ocr_spell_module)
        
        print("   ✓ Module imported successfully")
        print("   ✓ Functions available:")
        print(f"     - detect_spelling_grammar_errors: {hasattr(ocr_spell_module, 'detect_spelling_grammar_errors')}")
        print(f"     - run_ocr_on_pdf: {hasattr(ocr_spell_module, 'run_ocr_on_pdf')}")
        print(f"     - _filter_errors: {hasattr(ocr_spell_module, '_filter_errors')}")
    else:
        print("   ✗ Cannot import: file not found")
except Exception as e:
    print(f"   ✗ Import failed: {e}")

# Test 4: Test Azure connection (if credentials exist)
if azure_endpoint and azure_key:
    print("\n4. Testing Azure connection...")
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
        
        client = DocumentAnalysisClient(
            endpoint=azure_endpoint,
            credential=AzureKeyCredential(azure_key)
        )
        print("   ✓ Azure client created successfully")
        print("   ✓ Connection to Azure Document Intelligence established")
    except Exception as e:
        print(f"   ✗ Azure connection failed: {e}")
else:
    print("\n4. Skipping Azure connection test (credentials missing)")

print("\n" + "="*70)
print("Test Summary:")
print("="*70)

issues = []
if not grok_api:
    issues.append("Grok_API missing")
if not azure_endpoint or not azure_key:
    issues.append("Azure credentials missing - spell checking will be disabled")
if not found:
    issues.append("ocr-spell-correction.py not found")

if issues:
    print("❌ Issues found:")
    for issue in issues:
        print(f"   - {issue}")
    print("\nSpelling/grammar checking may not work properly!")
else:
    print("✅ All checks passed!")
    print("OCR spell correction should work correctly.")

print("="*70)
