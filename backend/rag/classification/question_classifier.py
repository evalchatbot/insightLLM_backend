"""
Question classification service for routing between generic and specific responses.
Determines whether a question requires RAG retrieval or can be answered with pre-defined responses.
"""
import re
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class QuestionType(Enum):
    """Types of questions the system can handle."""
    GENERIC = "generic"           # General system questions, capabilities, greetings
    SPECIFIC_CONTENT = "specific" # Questions requiring book content retrieval
    PROCEDURAL = "procedural"     # Questions about CSS exam procedures, format, etc.

class QuestionClassifier:
    """
    Classifies user questions to determine appropriate response strategy.
    """
    
    def __init__(self):
        self.generic_patterns = self._load_generic_patterns()
        self.procedural_patterns = self._load_procedural_patterns()
        self.content_indicators = self._load_content_indicators()
        
    def _load_generic_patterns(self) -> List[str]:
        """Patterns that indicate generic/system questions."""
        return [
            # Greetings and pleasantries
            r'\b(hello|hi|hey|good morning|good afternoon|good evening)\b',
            r'\b(how are you|what\'s up|how do you do)\b',
            
            # System capabilities
            r'\b(what can you do|what are your capabilities|how can you help)\b',
            r'\b(what do you know|what information do you have)\b',
            r'\b(how do you work|how does this work|explain how)\b',
            r'\b(what is this system|what is this chatbot|who are you)\b',
            
            # General assistance
            r'\b(can you help|help me|assist me|guide me)\b',
            r'\b(what should I|how should I|where should I)\b',
            r'\b(any suggestions|any recommendations|any advice)\b',
            
            # Meta questions
            r'\b(how to use|how to ask|how to get|instructions)\b',
            r'\b(features|functions|options|settings)\b',
            
            # Simple acknowledgments
            r'^(yes|no|ok|okay|thanks|thank you|bye|goodbye)$',
        ]
    
    def _load_procedural_patterns(self) -> List[str]:
        """Patterns for CSS exam procedure questions."""
        return [
            # CSS exam procedures
            r'\b(css exam|css test|css examination)\b',
            r'\b(how to prepare|preparation strategy|study plan)\b',
            r'\b(exam pattern|exam format|examination structure)\b',
            r'\b(syllabus|curriculum|subjects|papers)\b',
            r'\b(marking scheme|grading|scoring|evaluation)\b',
            r'\b(time management|exam timing|duration)\b',
            r'\b(writing style|answer format|how to write)\b',
            r'\b(tips|strategy|approach|methodology)\b',
        ]
    
    def _load_content_indicators(self) -> List[str]:
        """Keywords that indicate specific content questions."""
        return [
            # Question words for specific content
            r'\b(what was|what is|what are|what were)\b',
            r'\b(who was|who is|who were|who are)\b',
            r'\b(when was|when did|when were)\b',
            r'\b(where was|where is|where were)\b',
            r'\b(why was|why is|why did|why were)\b',
            r'\b(how was|how did|how were)\b',
            
            # Analysis keywords
            r'\b(discuss|analyze|examine|evaluate|assess|compare)\b',
            r'\b(explain|describe|elaborate|detail)\b',
            r'\b(causes|effects|impacts|consequences|implications)\b',
            r'\b(advantages|disadvantages|pros|cons|benefits|drawbacks)\b',
            
            # Specific content topics
            r'\b(constitution|constitutional|amendment)\b',
            r'\b(government|governance|administration|policy)\b',
            r'\b(history|historical|timeline|chronology)\b',
            r'\b(political|politics|democracy|federalism)\b',
            r'\b(economic|economy|development|trade)\b',
            r'\b(social|society|culture|education)\b',
            r'\b(international|foreign|diplomatic|relations)\b',
            
            # Pakistan-specific content
            r'\b(pakistan|pakistani|lahore|karachi|islamabad)\b',
            r'\b(punjab|sindh|balochistan|kpk|khyber pakhtunkhwa)\b',
            r'\b(jinnah|iqbal|liaquat|bhutto|zia)\b',
        ]
    
    def classify_question(self, question: str) -> Tuple[QuestionType, float]:
        """
        Classify a question and return type with confidence score.
        
        Args:
            question: User's question text
            
        Returns:
            Tuple of (QuestionType, confidence_score)
        """
        question_lower = question.lower().strip()
        
        # Remove extra whitespace and normalize
        question_normalized = re.sub(r'\s+', ' ', question_lower)
        
        # Check for generic patterns first
        generic_score = self._calculate_pattern_score(question_normalized, self.generic_patterns)
        
        # Check for procedural patterns
        procedural_score = self._calculate_pattern_score(question_normalized, self.procedural_patterns)
        
        # Check for content indicators
        content_score = self._calculate_pattern_score(question_normalized, self.content_indicators)
        
        # Additional heuristics
        word_count = len(question_normalized.split())
        
        # Very short questions are often generic
        if word_count <= 3 and generic_score > 0:
            generic_score *= 1.5
        
        # Questions with specific names, dates, or detailed topics are likely content questions
        if re.search(r'\b(19|20)\d{2}\b', question_normalized):  # Years
            content_score *= 1.3
        
        if re.search(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', question):  # Proper names
            content_score *= 1.2
        
        # Determine classification
        max_score = max(generic_score, procedural_score, content_score)
        
        if max_score == 0:
            # Default to content if no clear pattern
            return QuestionType.SPECIFIC_CONTENT, 0.5
        
        if generic_score == max_score:
            return QuestionType.GENERIC, min(generic_score, 1.0)
        elif procedural_score == max_score:
            return QuestionType.PROCEDURAL, min(procedural_score, 1.0)
        else:
            return QuestionType.SPECIFIC_CONTENT, min(content_score, 1.0)
    
    def _calculate_pattern_score(self, text: str, patterns: List[str]) -> float:
        """Calculate score based on pattern matches."""
        score = 0.0
        matches = 0
        
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                matches += 1
                score += 1.0
        
        # Normalize by pattern count and add bonus for multiple matches
        if matches > 0:
            base_score = score / len(patterns)
            bonus = min(matches * 0.1, 0.5)  # Bonus for multiple matches
            return base_score + bonus
        
        return 0.0
    
    def is_generic_question(self, question: str, threshold: float = 0.3) -> bool:
        """Quick check if question is generic."""
        question_type, confidence = self.classify_question(question)
        return question_type == QuestionType.GENERIC and confidence >= threshold
    
    def is_specific_content_question(self, question: str, threshold: float = 0.3) -> bool:
        """Quick check if question requires content retrieval."""
        question_type, confidence = self.classify_question(question)
        return question_type == QuestionType.SPECIFIC_CONTENT and confidence >= threshold
    
    def get_classification_details(self, question: str) -> Dict[str, any]:
        """Get detailed classification information for debugging."""
        question_type, confidence = self.classify_question(question)
        
        question_lower = question.lower().strip()
        question_normalized = re.sub(r'\s+', ' ', question_lower)
        
        generic_score = self._calculate_pattern_score(question_normalized, self.generic_patterns)
        procedural_score = self._calculate_pattern_score(question_normalized, self.procedural_patterns)
        content_score = self._calculate_pattern_score(question_normalized, self.content_indicators)
        
        return {
            "question": question,
            "classification": question_type.value,
            "confidence": round(confidence, 3),
            "scores": {
                "generic": round(generic_score, 3),
                "procedural": round(procedural_score, 3),
                "content": round(content_score, 3)
            },
            "word_count": len(question.split()),
            "normalized_question": question_normalized
        }


# Global classifier instance
_question_classifier = None

def get_question_classifier() -> QuestionClassifier:
    """Get the global question classifier instance."""
    global _question_classifier
    if _question_classifier is None:
        _question_classifier = QuestionClassifier()
    return _question_classifier
