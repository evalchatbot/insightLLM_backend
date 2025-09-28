#!/usr/bin/env python3
"""
Test suite for the simplified RAG-only chatbot architecture.
Tests direct RAG processing and end-to-end functionality.
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.agents.chatbot_agent import ChatbotAgent


async def test_direct_rag_processing():
    """Test direct RAG processing for all query types."""

    
    agent = ChatbotAgent()
    
    # Test various types of questions - all should be processed by RAG
    test_questions = [
        "Discuss the role of civil service in good governance",
        "Explain the federal structure of Pakistan", 
        "What is public administration theory?",
        "How to prepare for CSS exam?",
        "What are the eligibility criteria for CSS?",
        "Best study tips for civil service exam"
    ]
    
    for question in test_questions:
        try:
            result = await agent.ask(
                user_id="test_user",
                session_id="test_session",
                question=question,
                genre="test_genre"
            )
            assert result.get("answer") is not None
            assert "tool_used" in result.get("metadata", {})
            assert result["metadata"]["tool_used"] == "rag_tool"
        except Exception as e:
            raise


async def test_agent_capabilities():
    """Test agent capabilities and initialization."""
    
    agent = ChatbotAgent()
    capabilities = agent.get_agent_capabilities()
    
    # Verify simplified architecture
    assert capabilities["agent_type"] == "simplified_rag_only"
    assert capabilities["architecture"] == "direct_rag_processing"
    
    # Verify only RAG tool is loaded
    tools = capabilities["tools"]
    assert "rag_tool" in tools
    
    # Verify processing approach
    processing = capabilities["processing"]
    assert processing["approach"] == "Direct RAG for all queries"
    assert processing["classification"] == "Removed - all queries processed"





async def test_error_handling():
    """Test error handling and fallback mechanisms."""
    
    agent = ChatbotAgent()
    
    # Test with invalid inputs
    try:
        result = await agent.ask(
            user_id="test_user",
            session_id="test_session",
            question="",  # Empty question
            genre="test_genre"
        )
        assert "error" in result["metadata"] or result["answer"] is not None
    except Exception as e:
        raise


async def main():
    """Run all tests."""

    
    try:
        await test_direct_rag_processing()
        await test_agent_capabilities()
        await test_error_handling()

        
    except Exception as e:
        raise


if __name__ == "__main__":
    asyncio.run(main())
