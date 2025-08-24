import asyncio
from backend.agents.chatbot_agent import ChatbotAgent

async def main():
    agent = ChatbotAgent()
    res = await agent.ask(
        user_id="7d88e562-35ed-465c-82ac-921a34412b49",
        session_id="sess_1756032857.111156_7d88e562-35ed-465c-82ac-921a34412b49",
        question="Difference between iran and USA constitution",
        genre="Political-Science",
        book_ids=[]  # or provide specific IDs
    )
    print("ANSWER:\n", res["answer"][:])
    print("\nSOURCES:", len(res["sources"]))
    print("ITERATIONS:", res["metadata"].get("iterations"))
    print("TRACE STEPS:", len(res["metadata"].get("traces", [])))

if __name__ == "__main__":
    asyncio.run(main())
