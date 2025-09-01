"""
Performance optimization tests for ChatbotAgent.
"""
import asyncio
import time
import os
from backend.agents.chatbot_agent import ChatbotAgent

async def test_performance_modes():
    """Test different performance modes of the ChatbotAgent."""
    agent = ChatbotAgent()
    
    test_question = "What are the main themes in science fiction books?"
    user_id = "test_user"
    session_id = "test_session"
    genre = "Science Fiction"
    
    print("🚀 Testing ChatbotAgent Performance Modes")
    print("=" * 50)
    
    # Test 1: Fast mode
    print("\n1. Testing Fast Mode...")
    start = time.time()
    try:
        result_fast = await agent.ask_fast(user_id, session_id, test_question, genre)
        fast_time = time.time() - start
        print(f"   ✅ Fast mode completed in {fast_time:.2f}s")
        print(f"   📊 Sources: {len(result_fast.get('sources', []))}")
        print(f"   💬 Answer length: {len(result_fast.get('answer', ''))}")
    except Exception as e:
        print(f"   ❌ Fast mode failed: {e}")
    
    # Test 2: Optimized multi-step mode
    print("\n2. Testing Optimized Multi-step Mode...")
    start = time.time()
    try:
        # Set environment for optimized multi-step
        os.environ["USE_MULTI_STEP_RAG"] = "true"
        os.environ["USE_ADAPTIVE_RAG"] = "false"
        
        result_multi = await agent.ask(user_id, session_id + "_multi", test_question, genre)
        multi_time = time.time() - start
        print(f"   ✅ Multi-step mode completed in {multi_time:.2f}s")
        print(f"   📊 Sources: {len(result_multi.get('sources', []))}")
        print(f"   💬 Answer length: {len(result_multi.get('answer', ''))}")
        if "performance" in result_multi:
            print(f"   🔍 Performance: {result_multi['performance']}")
    except Exception as e:
        print(f"   ❌ Multi-step mode failed: {e}")
    
    # Test 3: Adaptive mode
    print("\n3. Testing Adaptive Mode...")
    start = time.time()
    try:
        # Set environment for adaptive mode
        os.environ["USE_ADAPTIVE_RAG"] = "true"
        
        result_adaptive = await agent.ask(user_id, session_id + "_adaptive", test_question, genre)
        adaptive_time = time.time() - start
        print(f"   ✅ Adaptive mode completed in {adaptive_time:.2f}s")
        print(f"   📊 Sources: {len(result_adaptive.get('sources', []))}")
        print(f"   💬 Answer length: {len(result_adaptive.get('answer', ''))}")
        print(f"   🎯 Mode used: {result_adaptive.get('metadata', {}).get('mode', 'unknown')}")
        if "performance" in result_adaptive:
            print(f"   🔍 Performance: {result_adaptive['performance']}")
    except Exception as e:
        print(f"   ❌ Adaptive mode failed: {e}")
    
    print("\n" + "=" * 50)
    print("🏁 Performance test completed!")

if __name__ == "__main__":
    asyncio.run(test_performance_modes())
