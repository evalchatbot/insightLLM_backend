# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Development Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the development server with auto-reload
uvicorn backend.main:app --reload

# Run the server on specific host/port
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Deployment
```bash
# Build the Docker image
docker build -t notebooklm-backend .

# Run the container with environment variables
docker run -d -p 8000:8000 \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_KEY=your_key \
  -e JWT_SECRET_KEY=your_secret \
  -e GROQ_API_KEY=your_groq_key \
  notebooklm-backend
```

### Testing
```bash
# Test new tool-based architecture
python backend/tests/test_tool_based_architecture.py

# Run specific test modules
python backend/tests/test_conversation_summarization.py
python backend/tests/test_css_exam_format.py
python backend/tests/test_performance_optimization.py

# Run RAG component tests  
python backend/tests/test_step1_scaffold.py
python backend/tests/test_step2_supabase_adapter_mock.py
python backend/tests/test_step3_planner_mock.py
python backend/tests/test_step4_controller_mock.py

# Run smoke test for multi-step agent
python backend/tests/smoke_multistep_agent.py
```

### API Documentation
- Interactive docs: http://localhost:8000/docs
- Redoc: http://localhost:8000/redoc

## Architecture Overview

### Core System Design
This is a **FastAPI-based chatbot backend** specialized for **CSS (Central Superior Services) exam preparation** using a **unified tool-based architecture** with intelligent domain boundary enforcement.

**Key Components:**
- **Single Agent with Tools**: Unified ChatbotAgent with domain-intent classification routing
- **Domain-Intent Classifier**: Fast, lightweight classification (CSS content, FAQ/Policy, Out-of-domain)
- **Three Specialized Tools**: RAG Tool, FAQ/Policy Tool, Guardrail Tool
- **Intelligent Memory System**: Short-term (LangGraph) + Long-term (Supabase) with conversation summarization
- **CSS Exam Optimization**: Structured responses with 12-20 headings, Introduction/Body/Conclusion format
- **Domain Boundaries**: Strict CSS exam domain enforcement with polite out-of-domain redirections

### Tool-Based Architecture

**Unified Agent Flow:**
```
User Query → Domain Classification → Tool Routing → Response Generation → Memory Update
```

**Domain-Intent Classification:**
- **CSS_EXAM_CONTENT**: Specific subject questions requiring RAG retrieval
- **FAQ_POLICY**: General CSS exam guidance and preparation tips  
- **OUT_OF_DOMAIN**: Non-CSS exam queries handled with polite redirection

**Tool Specialization:**
- **RAG Tool**: Handles complex academic content with multi-mode pipeline (fast/multi-step/adaptive)
- **FAQ/Policy Tool**: Built-in knowledge base for common CSS exam questions
- **Guardrail Tool**: Polite out-of-domain handling with CSS topic suggestions

**Key Classes:**
- `ChatbotAgent`: Unified orchestrator with tool-based routing
- `DomainIntentClassifier`: Fast pattern-based classification with context awareness
- `RAGTool`: Encapsulated RAG pipeline with citation support
- `FAQPolicyTool`: Knowledge base + LLM enhancement for guidance
- `GuardrailTool`: Out-of-domain handling with educational bridging

### RAG Architecture

**Three-Tier RAG System:**
1. **Fast Mode** (`ask_fast`): Single-step RAG optimized for speed (~2-5s)
2. **Multi-Step Mode** (`ask_multi_step`): Advanced pipeline with planning → retrieval → validation → synthesis (~5-15s)  
3. **Adaptive Mode**: Tries multi-step with timeout, falls back to fast mode (Recommended)

**Multi-Step RAG Flow:**
```
User Query → Plan Generation → Parallel Retrieval → Evidence Validation → Final Synthesis
```

**Key Classes:**
- `ChatbotAgent`: Main orchestrator with all three modes
- `SupabaseVectorStoreAdapter`: Vector store interface for RAG
- `HybridRetriever`: Combines vector and BM25 search
- `SubquestionGenerator`: Breaks complex queries into sub-questions
- `GraphController`: Manages multi-step RAG execution flow

### Memory Management Architecture

**Two-Layer Memory System:**
- **Short-term**: `ShortTermMemory` using LangGraph InMemoryStore for current session
- **Long-term**: `LongTermMemory` using Supabase for persistent storage

**Intelligent Summarization:**
- Auto-summarizes after 5 conversation exchanges
- `ConversationSummarizer` creates intelligent summaries using LLM
- 95-99% storage reduction while preserving context quality
- Automatic cleanup of redundant individual messages

### Database Schema (Supabase)

**Required Tables:**
- `users`: User accounts and profiles
- `books`: Book metadata (title, author, genre, file_url)
- `chat_messages`: Conversation history storage
- `document_chunks`: Processed book content with embeddings
- `sessions`: User session management
- `long_term_memory`: Conversation summaries and user context

**Key Enhancement:**
Long-term memory table supports conversation summarization with `content_type`, `metadata`, `created_at`, `archived_at` columns.

### Authentication & Security
- **JWT-based authentication** for all endpoints (except `/user/token`)
- **Supabase integration** for user management and data security
- **CORS configured** for frontend integration (Vercel and localhost)

## Performance Optimization

### Environment Variables for Performance
```bash
# Performance modes
USE_MULTI_STEP_RAG=true
USE_ADAPTIVE_RAG=true  # Recommended

# RAG optimization  
MAX_ITERATIONS=2
TOP_K=5
MAX_TIME_S=15
ENABLE_EARLY_STOPPING=true
MIN_EVIDENCE_THRESHOLD=3
PARALLEL_SUBQUESTION_RETRIEVAL=true

# Caching
ENABLE_CACHE=true
CACHE_TTL_S=600

# Tracing
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_key
LANGSMITH_PROJECT=insightLLM
```

### Performance Features
- **Embedding Caching**: TTL-based cache for repeated queries  
- **Parallel Processing**: Concurrent retrieval for independent sub-questions
- **Early Stopping**: Stops when sufficient evidence is found
- **Timeout Protection**: Global and per-operation timeouts
- **Adaptive Mode**: Automatic speed vs quality balancing

## CSS Exam Specialization

### Response Format Requirements
All chatbot responses must follow this structure:
1. **Introduction** (2-3 sentences): Overview and significance
2. **Body** (12-20 headings): Comprehensive topic coverage with specific headings
3. **Conclusion** (2-3 sentences): Summary and takeaways

### Content Guidelines
- **Academic tone** suitable for civil service examination
- **Pakistan-specific context** when relevant
- **Current affairs integration** for contemporary relevance  
- **Policy implications** and administrative aspects
- **Comprehensive coverage** (historical, political, economic, social dimensions)

### System Prompt Location
CSS exam formatting instructions are defined in `prompts/chatbot.txt` - this file controls the response structure and academic style.

## Development Guidelines

### Tool-Based Architecture Development
- **Domain Classifier** is in `backend/agents/domain_classifier.py`
- **RAG Tool** is in `backend/agents/tools/rag_tool.py` (encapsulates existing RAG pipeline)
- **FAQ/Policy Tool** is in `backend/agents/tools/faq_policy_tool.py`
- **Guardrail Tool** is in `backend/agents/tools/guardrail_tool.py`
- **Unified Agent** is in `backend/agents/chatbot_agent.py`

### RAG Pipeline Development (Legacy - now encapsulated in RAG Tool)
- **Multi-step pipeline** is in `backend/rag/reasoning/graph_controller.py`
- **Retrieval logic** is in `backend/rag/retrieval/hybrid_retriever.py`  
- **Planning logic** is in `backend/rag/planning/subquestion_generator.py`
- **LLM integration** is in `backend/rag/llm/groq_httpx.py`

### Memory System Development
- **Conversation summarization** logic is in `backend/memory/conversation_summarizer.py`
- **Short-term memory** implementation is in `backend/memory/short_term.py`
- **Long-term memory** implementation is in `backend/memory/long_term.py`

### Testing Strategy
- **Component tests** for individual RAG components (`test_step*.py`)
- **Integration tests** for conversation summarization and CSS format
- **Performance tests** for optimization validation
- **Smoke tests** for end-to-end pipeline validation

### API Route Structure
```
/chatbot/ask              # Main endpoint (adaptive mode)
/chatbot/ask-multistep    # Explicit multi-step mode
/user/token              # JWT token generation
/user/session/create     # Session management
/books/genres           # Content discovery
/books/{genre}          # Genre-specific books
/ingest/upload          # Book processing
```

### Book Processing Pipeline
The system processes uploaded books through:
1. **Document ingestion** (`backend/ingest/document_processor.py`)
2. **Text chunking** with overlapping windows
3. **Embedding generation** using FastEmbed
4. **Vector storage** in Supabase with metadata

### Error Handling Patterns
- **Graceful degradation** when components fail
- **Fallback modes** for performance issues  
- **Timeout protection** for long-running operations
- **Comprehensive logging** with structured metadata

## Key Files & Directories

### Core Application
- `backend/main.py` - FastAPI application entry point
- `backend/config.py` - Environment configuration
- `backend/agents/chatbot_agent.py` - Unified tool-based chatbot agent

### Tool-Based Architecture
- `backend/agents/domain_classifier.py` - Domain-intent classification system
- `backend/agents/tools/rag_tool.py` - RAG pipeline encapsulated as tool
- `backend/agents/tools/faq_policy_tool.py` - CSS exam guidance tool
- `backend/agents/tools/guardrail_tool.py` - Out-of-domain handling tool

### RAG System (Legacy - now part of RAG Tool)
- `backend/rag/reasoning/graph_controller.py` - Multi-step RAG controller
- `backend/rag/retrieval/hybrid_retriever.py` - Search implementation
- `backend/rag/planning/subquestion_generator.py` - Query decomposition

### Memory & Persistence  
- `backend/memory/` - Short-term and long-term memory implementations
- `backend/db/` - Database models and Supabase integration

### Performance & Monitoring
- `backend/rag/telemetry/` - LangSmith tracing and performance monitoring
- `backend/rag/memory/cache.py` - Embedding and response caching

### Documentation
- `CONVERSATION_SUMMARIZATION.md` - Memory optimization details
- `PERFORMANCE_OPTIMIZATION.md` - Speed optimization guide  
- `CSS_EXAM_FORMAT.md` - Response format specifications

This backend uses a **unified tool-based architecture** optimized for **CSS exam preparation** with **strict domain boundaries**, **enterprise-grade RAG capabilities**, **intelligent memory management**, and **polite out-of-domain handling**. The system reduces complexity while maintaining sophisticated functionality through specialized tools orchestrated by a single intelligent agent.
