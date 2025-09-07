"""
Test conversation summarization functionality.
"""
import asyncio
from backend.memory.short_term import ShortTermMemory
from backend.memory.long_term import LongTermMemory
from backend.memory.conversation_summarizer import ConversationSummarizer

async def test_conversation_summarization():
    """Test the conversation summarization workflow."""
    print("🧠 Testing Conversation Summarization")
    print("=" * 50)
    
    # Initialize components
    short_term = ShortTermMemory(summarization_threshold=5)
    long_term = LongTermMemory()
    summarizer = ConversationSummarizer()
    
    user_id = "test_user"
    session_id = "test_session_summary"
    
    # Simulate a conversation with 6 messages (exceeds threshold of 5)
    test_conversation = [
        {"sender": "user", "message": "What are some good science fiction books?"},
        {"sender": "assistant", "message": "I recommend Dune by Frank Herbert, Foundation by Isaac Asimov, and Neuromancer by William Gibson."},
        {"sender": "user", "message": "Tell me more about Dune."},
        {"sender": "assistant", "message": "Dune is set on the desert planet Arrakis and follows Paul Atreides as he navigates political intrigue and discovers his destiny."},
        {"sender": "user", "message": "What about Isaac Asimov's other works?"},
        {"sender": "assistant", "message": "Asimov wrote the Robot series, including I, Robot and The Caves of Steel, which explore robotics and AI themes."},
        {"sender": "user", "message": "Can you recommend some cyberpunk novels?"},
        {"sender": "assistant", "message": "For cyberpunk, try Neuromancer by William Gibson, Snow Crash by Neal Stephenson, and Altered Carbon by Richard K. Morgan."}
    ]
    
    print(f"📝 Adding {len(test_conversation)} messages to conversation...")
    
    # Add messages one by one
    for i, msg in enumerate(test_conversation, 1):
        short_term.add_message(user_id, session_id, msg)
        count = short_term.get_conversation_count(user_id, session_id)
        should_sum = short_term.should_summarize(user_id, session_id)
        
        print(f"   Message {i}: Count={count}, Should summarize={should_sum}")
        
        # Test summarization when threshold is reached
        if should_sum:
            print(f"\n🔄 Triggering summarization at message {i}...")
            
            # Get current messages
            current_messages = short_term.get_recent_messages(user_id, session_id)
            print(f"   📚 Summarizing {len(current_messages)} messages")
            
            # Test direct summarization
            summary = await summarizer.summarize_conversation(current_messages)
            print(f"   📄 Generated summary ({len(summary)} chars):")
            print(f"   {summary[:200]}...")
            
            # Test contextual summary
            contextual = await summarizer.create_contextual_summary(current_messages)
            print(f"   🏷️  Topics identified: {contextual['topics']}")
            
            # Test saving to long-term memory
            try:
                await long_term.save_conversation_summary(user_id, session_id, current_messages)
                print(f"   ✅ Summary saved to long-term memory")
                
                # Reset count
                short_term.reset_conversation_count(user_id, session_id)
                print(f"   🔄 Conversation count reset")
                
            except Exception as e:
                print(f"   ❌ Failed to save summary: {e}")
    
    # Test retrieval of user context
    print(f"\n📖 Testing context retrieval...")
    try:
        user_context = long_term.get_user_context(user_id)
        print(f"   📚 Retrieved user context ({len(user_context)} chars):")
        print(f"   {user_context[:300]}...")
        
        summaries = long_term.get_conversation_summaries(user_id)
        print(f"   📊 Found {len(summaries)} conversation summaries")
        
    except Exception as e:
        print(f"   ❌ Failed to retrieve context: {e}")
    
    print("\n" + "=" * 50)
    print("🏁 Summarization test completed!")

if __name__ == "__main__":
    asyncio.run(test_conversation_summarization())
