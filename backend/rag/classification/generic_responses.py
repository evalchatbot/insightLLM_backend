"""
Pre-defined responses for generic questions to avoid unnecessary RAG retrieval.
"""
from typing import Dict, Optional
import re

class GenericResponseHandler:
    """
    Handles generic questions with pre-defined, structured responses.
    Maintains CSS exam format even for generic questions.
    """
    
    def __init__(self):
        self.responses = self._load_generic_responses()
    
    def _load_generic_responses(self) -> Dict[str, str]:
        """Load pre-defined responses for common generic questions."""
        return {
            "greeting": """
## Introduction
Welcome to InsightLLM, your specialized CSS exam preparation assistant. I am designed to help you excel in Pakistan's Central Superior Services examination through comprehensive, structured learning.

## My Capabilities

### 1. **Comprehensive CSS Exam Preparation**
I provide detailed answers in the exact format required for CSS examinations, with Introduction, Body (12-20 headings), and Conclusion structure.

### 2. **Multi-Subject Coverage**
I can assist with Political Science, Public Administration, International Relations, Economics, Current Affairs, Pakistan Studies, and Essay Writing.

### 3. **Structured Learning Approach**
Every answer follows academic standards with proper headings, analysis, and exam-relevant insights.

### 4. **Current Affairs Integration**
I incorporate recent developments and contemporary relevance into all responses.

### 5. **Pakistan-Specific Context**
All answers are tailored to Pakistan's specific context, constitution, and administrative framework.

### 6. **Evidence-Based Responses**
I use relevant book content and scholarly sources to provide accurate, comprehensive information.

### 7. **Adaptive Response Modes**
I can provide detailed comprehensive answers or quicker condensed responses based on your needs.

### 8. **Conversation Memory**
I remember our previous discussions and can build upon earlier conversations for continuity.

### 9. **Performance Optimization**
I use advanced caching and parallel processing to provide fast, efficient responses.

### 10. **Quality Assurance**
Every response is structured to help you practice and master CSS exam writing techniques.

## Conclusion
I am your dedicated partner in CSS exam preparation, designed to help you develop the comprehensive knowledge and structured thinking required for success in Pakistan's premier civil service examination. Ask me any CSS-related question to get started!
            """,
            
            "capabilities": """
## Introduction
As your CSS exam preparation assistant, I offer specialized capabilities designed to help you excel in Pakistan's Central Superior Services examination through structured, comprehensive learning.

## My Core Capabilities

### 1. **CSS Exam-Formatted Answers**
I provide responses in the exact structure required for CSS examinations: Introduction, Body with 12-20 headings, and Conclusion.

### 2. **Multi-Subject Expertise**
I cover all major CSS subjects including Political Science, Public Administration, International Relations, Economics, and Pakistan Studies.

### 3. **Comprehensive Topic Analysis**
I analyze topics from multiple dimensions - historical, political, economic, social, and administrative perspectives.

### 4. **Current Affairs Integration**
I incorporate recent developments, contemporary issues, and their relevance to CSS exam topics.

### 5. **Pakistan-Centric Approach**
All responses are tailored to Pakistan's specific context, constitutional framework, and administrative structure.

### 6. **Evidence-Based Learning**
I use relevant book content and scholarly sources to provide accurate, well-researched information.

### 7. **Structured Writing Practice**
I help you learn proper CSS answer formatting through model responses and structured examples.

### 8. **Adaptive Response Modes**
I can provide detailed comprehensive answers or quicker condensed responses based on time constraints.

### 9. **Conversation Continuity**
I maintain context from previous discussions and can build upon earlier conversations.

### 10. **Performance Optimization**
I use advanced technology to provide fast, efficient responses while maintaining quality.

## Conclusion
I am specifically designed to be your comprehensive CSS exam preparation partner, helping you develop both the knowledge base and writing skills necessary for success in Pakistan's civil service examination.
            """,
            
            "help": """
## Introduction
I'm here to assist you with CSS exam preparation through structured, comprehensive responses. Let me guide you on how to make the most of our interactions.

## How to Use This System

### 1. **Ask Specific CSS Topics**
Ask questions about Political Science, Public Administration, International Relations, Economics, Current Affairs, or Pakistan Studies.

### 2. **Use CSS Exam Language**
Frame questions as you would see them in CSS exams: "Discuss...", "Analyze...", "Examine...", "Evaluate..."

### 3. **Request Comprehensive Coverage**
I will provide 12-20 headings covering all aspects of your topic in CSS exam format.

### 4. **Build on Previous Conversations**
I remember our discussions and can elaborate on previous topics or connect related concepts.

### 5. **Specify Your Focus**
If you want emphasis on particular aspects (historical, economic, political), mention it in your question.

### 6. **Practice Exam Writing**
Use my responses as model answers to learn CSS exam writing structure and approach.

### 7. **Ask Follow-up Questions**
Seek clarification, additional details, or related topics to deepen your understanding.

### 8. **Request Current Affairs**
Ask about recent developments and their relevance to CSS exam topics.

### 9. **Seek Comparative Analysis**
Request comparisons with international examples or best practices.

### 10. **Get Policy Insights**
Ask about administrative and governance implications of various topics.

## Sample Questions
- "Discuss the challenges of federalism in Pakistan"
- "Analyze Pakistan's foreign policy in the contemporary world"
- "Examine the role of civil service in good governance"
- "Evaluate the impact of globalization on developing countries"

## Conclusion
Simply ask any CSS-related question, and I'll provide a comprehensive, structured response that will help you prepare effectively for your examination. Start with any topic you'd like to explore!
            """,
            
            "default_generic": """
## Introduction
Thank you for your question. As your CSS exam preparation assistant, I'm designed to help you excel in Pakistan's Central Superior Services examination through comprehensive, structured learning.

## How I Can Assist You

### 1. **Comprehensive Topic Coverage**
I can provide detailed analysis of any CSS exam topic with proper Introduction, Body (12-20 headings), and Conclusion format.

### 2. **Current Affairs Integration**
I incorporate recent developments and contemporary relevance into all responses for CSS exam preparation.

### 3. **Pakistan-Specific Context**
All my responses are tailored to Pakistan's constitutional, political, and administrative framework.

### 4. **Evidence-Based Learning**
I use relevant book content and scholarly sources to provide accurate information.

### 5. **Structured Writing Practice**
I help you learn proper CSS answer formatting through model responses.

### 6. **Multi-Dimensional Analysis**
I examine topics from historical, political, economic, social, and administrative perspectives.

## Getting Started
Ask me any specific CSS exam topic such as:
- Constitutional law and governance
- Political systems and democracy
- International relations and foreign policy
- Economic development and policy
- Public administration and civil service
- Current affairs and contemporary issues

## Conclusion
I'm ready to help you prepare for CSS exams with comprehensive, structured responses. Please ask any specific topic you'd like to explore in detail!
            """
        }
    
    def _load_procedural_patterns(self) -> List[str]:
        """Patterns for CSS exam procedure questions."""
        return [
            r'\b(css exam|css test|css examination)\b',
            r'\b(how to prepare|preparation strategy|study plan)\b',
            r'\b(exam pattern|exam format|examination structure)\b',
            r'\b(syllabus|curriculum|subjects|papers)\b',
            r'\b(marking scheme|grading|scoring|evaluation)\b',
            r'\b(time management|exam timing|duration)\b',
            r'\b(writing style|answer format|how to write)\b',
            r'\b(tips|strategy|approach|methodology)\b',
        ]
    
    def get_response(self, question: str, question_type: str = None) -> Optional[str]:
        """
        Get pre-defined response for generic questions.
        
        Args:
            question: User's question
            question_type: Optional override for response type
            
        Returns:
            Pre-defined response or None if not available
        """
        question_lower = question.lower().strip()
        
        # Match specific patterns to responses
        if any(re.search(pattern, question_lower) for pattern in [
            r'\b(hello|hi|hey|good morning|good afternoon|good evening)\b',
            r'\b(how are you|what\'s up)\b'
        ]):
            return self.responses["greeting"]
        
        if any(re.search(pattern, question_lower) for pattern in [
            r'\b(what can you do|what are your capabilities|how can you help)\b',
            r'\b(capabilities|features|functions)\b'
        ]):
            return self.responses["capabilities"]
        
        if any(re.search(pattern, question_lower) for pattern in [
            r'\b(help|how to use|instructions|guide)\b',
            r'\b(how should I|what should I)\b'
        ]):
            return self.responses["help"]
        
        # Default generic response
        return self.responses["default_generic"]
    
    def should_use_generic_response(self, question: str, confidence_threshold: float = 0.4) -> bool:
        """
        Determine if question should use generic response.
        
        Args:
            question: User's question
            confidence_threshold: Minimum confidence for generic classification
            
        Returns:
            True if should use generic response
        """
        from backend.rag.classification.question_classifier import get_question_classifier
        
        classifier = get_question_classifier()
        question_type, confidence = classifier.classify_question(question)
        
        return (question_type.value == "generic" and confidence >= confidence_threshold)


# Global response handler instance
_generic_response_handler = None

def get_generic_response_handler() -> GenericResponseHandler:
    """Get the global generic response handler instance."""
    global _generic_response_handler
    if _generic_response_handler is None:
        _generic_response_handler = GenericResponseHandler()
    return _generic_response_handler
