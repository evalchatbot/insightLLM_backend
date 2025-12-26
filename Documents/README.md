# Documentation Index

Welcome to the Rubrik AI project documentation! This directory contains comprehensive documentation for both the frontend and backend codebases.

---

## 📚 Backend Documentation

### Main Documentation

- **[BACKEND_DOCUMENTATION.md](./BACKEND_DOCUMENTATION.md)** - Complete overview of the backend architecture, structure, API routes, modules, and development guidelines.

### API Documentation

- **[BACKEND_API_ROUTES_DOCUMENTATION.md](./BACKEND_API_ROUTES_DOCUMENTATION.md)** - Detailed documentation for all FastAPI routes, including request/response formats, authentication, and error handling.

### Modules Documentation

- **[BACKEND_MODULES_DOCUMENTATION.md](./BACKEND_MODULES_DOCUMENTATION.md)** - Complete documentation for all backend modules, agents, services, utilities, and components.

### Documentation Guide

- **[DOCUMENTATION_PROCESS.md](./DOCUMENTATION_PROCESS.md)** - **⭐ START HERE** - Complete guide on how to document changes (mandatory process).
- **[QUICK_DOCUMENTATION_REFERENCE.md](./QUICK_DOCUMENTATION_REFERENCE.md)** - One-page quick reference for documenting changes.
- **[BACKEND_DOCUMENTATION_TEMPLATE.md](./BACKEND_DOCUMENTATION_TEMPLATE.md)** - Templates and guidelines for documenting future backend changes.

### Implementation Documentation

#### OCR Reliability (Issue #5)

- **[TIMEOUT_HANDLING_IMPLEMENTATION.md](./TIMEOUT_HANDLING_IMPLEMENTATION.md)** - Detailed documentation for OCR timeout handling implementation (Issue #5 Fix #1) - ✅ Completed
- **[RETRY_LOGIC_IMPLEMENTATION.md](./RETRY_LOGIC_IMPLEMENTATION.md)** - Implementation plan for retry logic with exponential backoff (Issue #5 Fix #2) - ✅ Completed
- **[RETRY_POLICY.md](./RETRY_POLICY.md)** - Official retry policy definition (Section 1 implementation) - ✅ Completed
- **[CONFIGURATION_IMPLEMENTATION_SUMMARY.md](./CONFIGURATION_IMPLEMENTATION_SUMMARY.md)** - Configuration knobs for retry logic (Section 2) - ✅ Completed
- **[ERROR_CLASSIFICATION_IMPLEMENTATION.md](./ERROR_CLASSIFICATION_IMPLEMENTATION.md)** - Error classification function implementation (Section 3) - ✅ Completed
- **[BACKOFF_CALCULATION_IMPLEMENTATION.md](./BACKOFF_CALCULATION_IMPLEMENTATION.md)** - Exponential backoff calculation implementation (Section 4) - ✅ Completed
- **[TIMEOUT_INTEGRATION_IMPLEMENTATION.md](./TIMEOUT_INTEGRATION_IMPLEMENTATION.md)** - Retry budget management and timeout integration (Section 5) - ✅ Completed
- **[RETRY_WRAPPER_IMPLEMENTATION.md](./RETRY_WRAPPER_IMPLEMENTATION.md)** - Retry wrapper function implementation (Section 6) - ✅ Completed
- **[LOGGING_AND_METRICS_IMPLEMENTATION.md](./LOGGING_AND_METRICS_IMPLEMENTATION.md)** - Enhanced logging and metrics tracking (Section 7) - ✅ Completed

#### Memory Error Fixes (Issue #7)

- **[MEMORY_MONITORING_IMPLEMENTATION.md](./MEMORY_MONITORING_IMPLEMENTATION.md)** - Memory monitoring and validation implementation (Solution 5) - ✅ Completed
- **[INCREMENTAL_PDF_WRITING_IMPLEMENTATION.md](./INCREMENTAL_PDF_WRITING_IMPLEMENTATION.md)** - Incremental PDF writing to prevent output re-accumulation - ✅ Completed

#### OCR Processing Time Optimization (Issue #3)

- **[PARALLEL_OCR_IMPLEMENTATION.md](./PARALLEL_OCR_IMPLEMENTATION.md)** - Bounded parallel OCR processing implementation (Step 1) - ✅ Completed
- **[WARMUP_PHASE_IMPLEMENTATION.md](./WARMUP_PHASE_IMPLEMENTATION.md)** - Warm-up phase implementation (Step 4) - ✅ Completed
- **[CONDITIONAL_PARALLEL_OCR_IMPLEMENTATION.md](./CONDITIONAL_PARALLEL_OCR_IMPLEMENTATION.md)** - Conditional parallel OCR implementation (Step 5) - ✅ Completed
- **[BATCH_ORCHESTRATION_IMPLEMENTATION.md](./BATCH_ORCHESTRATION_IMPLEMENTATION.md)** - Batch orchestration implementation (Step 6) - ✅ Completed
- **[ADAPTIVE_CONCURRENCY_IMPLEMENTATION.md](./ADAPTIVE_CONCURRENCY_IMPLEMENTATION.md)** - Adaptive concurrency implementation (Step 7) - ✅ Completed
- **[IMAGE_OPTIMIZATION_IMPLEMENTATION.md](./IMAGE_OPTIMIZATION_IMPLEMENTATION.md)** - Image optimization implementation (Step 8) - ✅ Completed
- **[PROGRESS_REPORTING_IMPLEMENTATION.md](./PROGRESS_REPORTING_IMPLEMENTATION.md)** - Progress reporting implementation (Step 9) - ✅ Completed
- **[ASYNC_BACKGROUND_JOBS_IMPLEMENTATION.md](./ASYNC_BACKGROUND_JOBS_IMPLEMENTATION.md)** - Async background jobs implementation (Step 10) - ✅ Completed
- **[CHANGELOG_PROGRESS_AND_ASYNC_JOBS.md](./CHANGELOG_PROGRESS_AND_ASYNC_JOBS.md)** - Complete changelog for progress and async jobs - ✅ Completed

---

## 📚 Frontend Documentation

The frontend documentation is located in: `insightLLM_frontend_2.0/Documents/`

See the [Frontend Documentation Index](../insightLLM_frontend_2.0/Documents/README.md) for details.

---

## 🚀 Quick Start

### For New Developers

#### Backend

1. Start with **[BACKEND_DOCUMENTATION.md](./BACKEND_DOCUMENTATION.md)** to understand the overall architecture
2. Review **[BACKEND_API_ROUTES_DOCUMENTATION.md](./BACKEND_API_ROUTES_DOCUMENTATION.md)** to learn about API endpoints
3. Check **[BACKEND_MODULES_DOCUMENTATION.md](./BACKEND_MODULES_DOCUMENTATION.md)** to understand modules and components

#### Frontend

1. Navigate to `insightLLM_frontend_2.0/Documents/`
2. Start with the Frontend Documentation Index

### For Making Changes

1. **⭐ READ FIRST**: [DOCUMENTATION_PROCESS.md](./DOCUMENTATION_PROCESS.md) - Complete documentation workflow
2. **Quick Reference**: [QUICK_DOCUMENTATION_REFERENCE.md](./QUICK_DOCUMENTATION_REFERENCE.md) - One-page guide
3. Use the appropriate template from [BACKEND_DOCUMENTATION_TEMPLATE.md](./BACKEND_DOCUMENTATION_TEMPLATE.md)
4. Update relevant documentation files
5. Commit documentation along with code changes

**⚠️ IMPORTANT**: Documentation is now mandatory for all code changes!

---

## 🔍 Finding Information

### Backend

- **Project structure** → [BACKEND_DOCUMENTATION.md](./BACKEND_DOCUMENTATION.md#project-structure)
- **API endpoints** → [BACKEND_API_ROUTES_DOCUMENTATION.md](./BACKEND_API_ROUTES_DOCUMENTATION.md)
- **Modules and agents** → [BACKEND_MODULES_DOCUMENTATION.md](./BACKEND_MODULES_DOCUMENTATION.md)
- **How to document changes** → [BACKEND_DOCUMENTATION_TEMPLATE.md](./BACKEND_DOCUMENTATION_TEMPLATE.md)

### Frontend

- See `insightLLM_frontend_2.0/Documents/README.md`

---

## 📝 Documentation Standards

### When to Update Documentation

- ✅ Adding a new API route
- ✅ Modifying an existing route
- ✅ Adding a new module/agent
- ✅ Changing module behavior
- ✅ Adding new utilities
- ✅ Changing database schema
- ✅ Fixing bugs (document the fix)
- ✅ Adding features (document the feature)

### Documentation Checklist

- [ ] Code follows project style guidelines
- [ ] Type hints are defined (Python)
- [ ] Error handling is documented
- [ ] Usage examples are provided
- [ ] Related files are cross-referenced
- [ ] "Last Updated" date is set

---

## 🛠️ Technology Stack

### Backend

- **Framework**: FastAPI
- **Language**: Python 3.13+
- **Database**: Supabase (PostgreSQL)
- **AI/LLM**: LangChain, Groq, Grok
- **Document Processing**: PyMuPDF, python-docx

### Frontend

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **UI Library**: React 18
- **Styling**: Tailwind CSS
- **Authentication**: Clerk
- **Database**: Supabase

---

## 📞 Getting Help

### Common Issues

1. **Can't find an API route?** → Check [BACKEND_API_ROUTES_DOCUMENTATION.md](./BACKEND_API_ROUTES_DOCUMENTATION.md)
2. **Module not working?** → Check [BACKEND_MODULES_DOCUMENTATION.md](./BACKEND_MODULES_DOCUMENTATION.md)
3. **How to document changes?** → Check [BACKEND_DOCUMENTATION_TEMPLATE.md](./BACKEND_DOCUMENTATION_TEMPLATE.md)

### Still Need Help?

- Review the main README files in project roots
- Check the code comments in relevant files
- Review the implementation

---

## 🔄 Keeping Documentation Updated

### Best Practices

1. **Document as you code** - Don't wait until the end
2. **Update docs with code** - Commit documentation with code changes
3. **Be specific** - Include file paths, code examples, and clear descriptions
4. **Explain why** - Not just what, but why decisions were made
5. **Use templates** - Follow the templates for consistency

### Review Process

1. Code review should include documentation review
2. Ensure documentation matches implementation
3. Update "Last Updated" dates
4. Cross-reference related documentation

---

## 📅 Documentation History

- **2025**: Initial comprehensive documentation created
- All documentation files include "Last Updated" dates

---

## 🎯 Quick Reference

### Backend API Categories

- **Chatbot API**: `/chatbot/*` - Chatbot interactions
- **OCR API**: `/api/ocr/*` - PDF evaluation endpoints
- **Conversation API**: `/conversations/*` - Conversation management
- **User API**: `/user/*` - User management
- **Book API**: `/books/*` - Book management
- **Quiz API**: `/quiz/*` - MCQ endpoints

### Backend Module Categories

- **Agents**: Chatbot, conversational, intent agents
- **OCR System**: PDF evaluation and annotation (with timeout handling, retry logic, and memory-efficient processing)
- **Memory Management**: Short-term and long-term memory
- **RAG System**: Retrieval and generation components
- **Database Services**: Supabase operations
- **Utilities**: Logging, PDF processing, rubric handling

### Recent Implementations

#### OCR Reliability Improvements (Issue #5)

- **Timeout Handling** (✅ Completed): OCR processing now includes per-page and overall timeouts to prevent indefinite hangs. See [TIMEOUT_HANDLING_IMPLEMENTATION.md](./TIMEOUT_HANDLING_IMPLEMENTATION.md) for details.
- **Retry Logic with Exponential Backoff** (✅ Completed): Comprehensive retry mechanism with error classification, exponential backoff, and budget management. See [RETRY_LOGIC_IMPLEMENTATION.md](./RETRY_LOGIC_IMPLEMENTATION.md) for details.

#### Memory Error Fixes (Issue #7)

- **Memory-Efficient Page Processing** (✅ Completed): Pages are now processed one at a time with explicit memory cleanup, reducing peak memory usage by ~60-70%. See [MEMORY_MONITORING_IMPLEMENTATION.md](./MEMORY_MONITORING_IMPLEMENTATION.md) for details.
- **Memory Monitoring** (✅ Completed): Proactive memory checks before and during processing with graceful failure handling. See [MEMORY_MONITORING_IMPLEMENTATION.md](./MEMORY_MONITORING_IMPLEMENTATION.md) for details.
- **Incremental PDF Writing** (✅ Completed): PDF writing uses PyPDF2 for incremental writing, eliminating double accumulation and reducing memory by ~40%. See [INCREMENTAL_PDF_WRITING_IMPLEMENTATION.md](./INCREMENTAL_PDF_WRITING_IMPLEMENTATION.md) for details.

---

**Remember**: Good documentation is an investment in the future. Keep it updated! 📚✨
