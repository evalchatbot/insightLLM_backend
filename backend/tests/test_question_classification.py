"""
Test question classification and smart routing functionality.
"""
import asyncio
from backend.agents.chatbot_agent import ChatbotAgent
from backend.rag.classification.question_classifier import get_question_classifier, QuestionType
from backend.rag.classification.generic_responses import get_generic_response_handler

async def test_question_classification():
    """Test the question classification and routing system."""
    print("🤖 Testing Smart Question Classification & Routing")
    print("=" * 70)
    
    classifier = get_question_classifier()
    generic_handler = get_generic_response_handler()
    agent = ChatbotAgent()
    
    # Test cases with expected classifications
    test_cases = [
        # Generic questions
        ("Hello", QuestionType.GENERIC),
        ("What can you do?", QuestionType.GENERIC),
        ("How can you help me?", QuestionType.GENERIC),
        ("What are your capabilities?", QuestionType.GENERIC),
        ("Hi there", QuestionType.GENERIC),
        ("Help me", QuestionType.GENERIC),
        
        # Procedural questions
        ("How to prepare for CSS exam?", QuestionType.PROCEDURAL),
        ("What is CSS exam pattern?", QuestionType.PROCEDURAL),
        ("CSS exam syllabus", QuestionType.PROCEDURAL),
        ("Tips for CSS preparation", QuestionType.PROCEDURAL),
        
        # Specific content questions
        ("What was the Constitution of Pakistan 1973?", QuestionType.SPECIFIC_CONTENT),
        ("Discuss the challenges of federalism in Pakistan", QuestionType.SPECIFIC_CONTENT),
        ("Analyze Pakistan's foreign policy", QuestionType.SPECIFIC_CONTENT),
        ("Who was Allama Iqbal?", QuestionType.SPECIFIC_CONTENT),
        ("Explain the role of civil service in governance", QuestionType.SPECIFIC_CONTENT),
        ("What are the causes of poverty in developing countries?", QuestionType.SPECIFIC_CONTENT),
    ]
    
    print("\n1. Testing Question Classification")
    print("-" * 50)
    
    correct_classifications = 0
    total_tests = len(test_cases)
    
    for question, expected_type in test_cases:
        classification_details = classifier.get_classification_details(question)
        actual_type = QuestionType(classification_details["classification"])
        confidence = classification_details["confidence"]
        
        is_correct = actual_type == expected_type
        if is_correct:
            correct_classifications += 1
        
        status = "✅" if is_correct else "❌"
        print(f"{status} Q: '{question[:40]}...'")
        print(f"    Expected: {expected_type.value}, Got: {actual_type.value} (conf: {confidence:.2f})")
        
        if not is_correct:
            print(f"    Scores: {classification_details['scores']}")
    
    accuracy = correct_classifications / total_tests
    print(f"\n📊 Classification Accuracy: {accuracy:.1%} ({correct_classifications}/{total_tests})")
    
    print("\n2. Testing Generic Response Handling")
    print("-" * 50)
    
    generic_questions = [
        "Hello",
        "What can you do?",
        "Help me",
        "How can you assist me?"
    ]
    
    for question in generic_questions:
        should_use_generic = generic_handler.should_use_generic_response(question)
        response = generic_handler.get_response(question)
        
        print(f"Q: '{question}'")
        print(f"   Should use generic: {should_use_generic}")
        print(f"   Has response: {response is not None}")
        if response:
            print(f"   Response length: {len(response)} chars")
            # Show first line of response
            first_line = response.split('\n')[0].strip()
            print(f"   Preview: {first_line[:60]}...")
        print()
    
    print("\n3. Testing Smart Routing in ChatbotAgent")
    print("-" * 50)
    
    user_id = "test_user"
    session_id = "classification_test"
    genre = "Political Science"
    
    routing_tests = [
        ("Hello there!", "Should route to generic response"),
        ("What can you help me with?", "Should route to generic response"),
        ("Discuss the Constitution of Pakistan 1973", "Should route to RAG pipeline"),
        ("What was the role of Jinnah in Pakistan movement?", "Should route to RAG pipeline"),
    ]
    
    for question, expectation in routing_tests:
        print(f"Q: '{question}'")
        print(f"   Expectation: {expectation}")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            result = await agent.ask(user_id, session_id + "_" + str(hash(question)), question, genre)
            
            end_time = asyncio.get_event_loop().time()
            response_time = end_time - start_time
            
            metadata = result.get("metadata", {})
            question_type = metadata.get("question_type", "unknown")
            mode = metadata.get("mode", "unknown")
            sources_count = len(result.get("sources", []))
            
            print(f"   ✅ Response time: {response_time:.2f}s")
            print(f"   📋 Classification: {question_type}")
            print(f"   🔄 Mode: {mode}")
            print(f"   📚 Sources used: {sources_count}")
            print(f"   📝 Answer length: {len(result.get('answer', ''))} chars")
            
            # Verify routing worked correctly
            if "generic" in expectation.lower():
                if question_type == "generic" and sources_count == 0:
                    print(f"   ✅ Correctly routed to generic response!")
                else:
                    print(f"   ⚠️  Expected generic routing but got {question_type}")
            else:
                if question_type in ["specific", "procedural"] and sources_count > 0:
                    print(f"   ✅ Correctly routed to RAG pipeline!")
                else:
                    print(f"   ⚠️  Expected RAG routing but got {question_type}")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print()
    
    print("=" * 70)
    print("🏁 Smart Classification Test Completed!")
    print(f"📊 Overall Classification Accuracy: {accuracy:.1%}")

if __name__ == "__main__":
    asyncio.run(test_question_classification())
