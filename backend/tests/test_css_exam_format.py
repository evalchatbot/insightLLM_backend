"""
Test CSS exam format for ChatbotAgent responses.
"""
import asyncio
import re
from backend.agents.chatbot_agent import ChatbotAgent

async def test_css_exam_format():
    """Test that ChatbotAgent provides responses in CSS exam format."""
    agent = ChatbotAgent()
    
    # Test questions typical for CSS exams
    test_questions = [
        "Discuss the role of civil service in good governance",
        "Analyze the challenges of federalism in Pakistan",
        "Explain the importance of constitutional supremacy",
        "Evaluate the impact of globalization on developing countries"
    ]
    
    user_id = "css_test_user"
    session_id = "css_test_session"
    genre = "Political Science"
    
    print("📚 Testing CSS Exam Format")
    print("=" * 60)
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n{i}. Testing Question: {question[:50]}...")
        
        try:
            # Test with fast mode for quicker validation
            result = await agent.ask_fast(
                user_id=user_id,
                session_id=f"{session_id}_{i}",
                question=question,
                genre=genre
            )
            
            answer = result.get("answer", "")
            print(f"   📝 Answer length: {len(answer)} characters")
            
            # Analyze structure
            structure_analysis = analyze_css_format(answer)
            print(f"   🔍 Structure Analysis:")
            print(f"      ✅ Has Introduction: {structure_analysis['has_introduction']}")
            print(f"      📋 Heading count: {structure_analysis['heading_count']}")
            print(f"      ✅ Has Conclusion: {structure_analysis['has_conclusion']}")
            print(f"      🎯 Format Score: {structure_analysis['format_score']:.1f}/10")
            
            if structure_analysis['format_score'] >= 7:
                print(f"      ✅ GOOD CSS format!")
            else:
                print(f"      ⚠️  Format needs improvement")
                
            # Show first few lines as sample
            lines = answer.split('\n')[:8]
            print(f"   📄 Sample (first 8 lines):")
            for line in lines:
                if line.strip():
                    print(f"      {line[:80]}...")
                    
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("🏁 CSS Format Test Completed!")

def analyze_css_format(answer: str) -> dict:
    """Analyze if answer follows CSS exam format."""
    lines = answer.split('\n')
    text = answer.lower()
    
    # Check for introduction
    has_intro = any(word in text[:200] for word in ['introduction', 'overview', 'significance', 'brief'])
    
    # Check for conclusion
    has_conclusion = any(word in text[-300:] for word in ['conclusion', 'summary', 'takeaway', 'finally'])
    
    # Count headings (look for numbered items, bold text, or heading patterns)
    heading_patterns = [
        r'^\d+\.\s*\*\*.*\*\*',  # 1. **Heading**
        r'^\*\*.*\*\*',          # **Heading**
        r'^\d+\.\s*[A-Z].*:',    # 1. Heading:
        r'^#+\s*',               # # Heading
        r'^\d+\.\s*[A-Z][^.]*$'  # 1. Heading (standalone line)
    ]
    
    heading_count = 0
    for line in lines:
        line = line.strip()
        if line:
            for pattern in heading_patterns:
                if re.match(pattern, line):
                    heading_count += 1
                    break
    
    # Calculate format score (0-10)
    score = 0
    if has_intro:
        score += 2
    if has_conclusion:
        score += 2
    if heading_count >= 6:
        score += 3
    if heading_count >= 12:
        score += 2
    if len(answer) > 500:  # Substantial content
        score += 1
    
    return {
        'has_introduction': has_intro,
        'has_conclusion': has_conclusion,
        'heading_count': heading_count,
        'format_score': min(score, 10),
        'answer_length': len(answer)
    }

if __name__ == "__main__":
    asyncio.run(test_css_exam_format())
