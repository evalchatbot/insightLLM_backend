# Performance Optimization Guide for InsightLLM

This guide explains the performance optimizations implemented to reduce `chatbot_multi_step_rag` response times.

## 🚀 Key Optimizations Implemented

### 1. **Reduced Iterations & Timeouts**
- `MAX_ITERATIONS`: Reduced from 4 → 2
- `TOP_K`: Reduced from 8 → 5 
- `MAX_TIME_S`: Reduced from 30 → 15 seconds
- `MIN_EVIDENCE_THRESHOLD`: Set to 3 for early stopping

### 2. **Embedding Caching**
- Added `EmbeddingCache` with TTL-based storage
- Avoids redundant embedding generation for similar queries
- Significant speedup for repeated or similar questions

### 3. **Parallel Processing**
- Parallel retrieval for independent subquestions
- Concurrent processing using `asyncio.gather()`
- Controlled by `PARALLEL_SUBQUESTION_RETRIEVAL` setting

### 4. **Early Stopping**
- Stops processing when sufficient evidence is found
- Configurable via `ENABLE_EARLY_STOPPING` and `MIN_EVIDENCE_THRESHOLD`
- Prevents unnecessary iterations

### 5. **Optimized Planning**
- Reduced max subquestions from 5 → 3
- Shorter token limits for planning (300 tokens)
- Faster fallback to single question mode

### 6. **Timeout Protection**
- Global timeout for entire RAG pipeline
- Per-operation timeouts for synthesis
- Graceful degradation when time runs out

## 🎛️ Configuration Options

Add these environment variables to control performance:

```env
# Performance settings
USE_MULTI_STEP_RAG=true
USE_ADAPTIVE_RAG=true  # Recommended for best performance

# RAG Configuration
MAX_ITERATIONS=2
TOP_K=5
MAX_TIME_S=15
ENABLE_EARLY_STOPPING=true
MIN_EVIDENCE_THRESHOLD=3
PARALLEL_SUBQUESTION_RETRIEVAL=true

# Caching
ENABLE_CACHE=true
CACHE_TTL_S=600
```

## 🔄 Operating Modes

### 1. **Fast Mode** (`ask_fast`)
- Single-step RAG with optimizations
- ~2-5 seconds response time
- Reduced context and retrieval scope
- Best for simple questions

### 2. **Optimized Multi-step** (`ask_multi_step`)
- Enhanced multi-step pipeline
- ~5-15 seconds response time
- Parallel processing and early stopping
- Best for complex questions

### 3. **Adaptive Mode** (Recommended)
- Tries multi-step with 10-second timeout
- Falls back to fast mode if timeout exceeded
- Automatically balances quality vs speed
- Enable with `USE_ADAPTIVE_RAG=true`

## 📊 Performance Monitoring

The system now includes comprehensive performance tracking:

### Metrics Tracked
- Total execution time
- Time per component (planning, retrieval, synthesis)
- Cache hit/miss ratios
- Evidence collection efficiency
- Early stopping triggers

### Response Metadata
Each response now includes performance data:
```json
{
  "answer": "...",
  "performance": {
    "total_time": 3.45,
    "planning_time": 0.8,
    "retrieval_time": 1.2,
    "synthesis_time": 1.1,
    "cache_hits": 2,
    "cache_misses": 1,
    "efficiency_score": 0.85,
    "early_stopped": true
  }
}
```

## ⚡ Expected Performance Improvements

| Scenario | Before | After | Improvement |
|----------|--------|-------|-------------|
| Simple questions | 15-30s | 2-5s | **70-85% faster** |
| Complex questions | 30-60s | 8-15s | **50-75% faster** |
| Repeated questions | 15-30s | 1-3s | **80-90% faster** |
| Cache hit scenarios | 15-30s | 0.5-2s | **90-95% faster** |

## 🛠️ Usage Examples

### Enable Adaptive Mode (Recommended)
```python
import os
os.environ["USE_ADAPTIVE_RAG"] = "true"

agent = ChatbotAgent()
result = await agent.ask(user_id, session_id, question, genre)
# Automatically uses best mode for the situation
```

### Force Fast Mode
```python
agent = ChatbotAgent()
result = await agent.ask_fast(user_id, session_id, question, genre)
# Always uses single-step optimized RAG
```

### Monitor Performance
```python
result = await agent.ask(user_id, session_id, question, genre)
performance = result.get("performance", {})
print(f"Response time: {performance.get('total_time')}s")
print(f"Efficiency score: {performance.get('efficiency_score')}")
```

## 🔧 Tuning Recommendations

### For Even Faster Responses
```env
MAX_ITERATIONS=1
TOP_K=3
MIN_EVIDENCE_THRESHOLD=2
MAX_TIME_S=10
```

### For Better Quality (Slower)
```env
MAX_ITERATIONS=3
TOP_K=8
MIN_EVIDENCE_THRESHOLD=5
MAX_TIME_S=20
```

### For High-Traffic Scenarios
```env
USE_ADAPTIVE_RAG=true
ENABLE_CACHE=true
CACHE_TTL_S=1800  # 30 minutes
PARALLEL_SUBQUESTION_RETRIEVAL=true
```

## 🐛 Troubleshooting

### Common Issues

1. **Still slow responses**:
   - Check if `ENABLE_CACHE=true`
   - Verify `PARALLEL_SUBQUESTION_RETRIEVAL=true`
   - Consider using adaptive mode

2. **Cache not working**:
   - Ensure `langsmith` is installed
   - Check cache TTL settings
   - Verify no memory constraints

3. **Timeout errors**:
   - Increase `MAX_TIME_S`
   - Reduce `TOP_K` and `MAX_ITERATIONS`
   - Use fast mode for time-critical scenarios

### Performance Debugging

Check the logs for performance warnings:
```
Performance: subquestion_planning took 2.1s
RAG Performance Metrics: {"total_time": 8.5, "efficiency_score": 0.75}
Slow RAG response: 18.2s
```

## 🎯 Next Steps

1. **Test the optimizations** with your typical workload
2. **Monitor performance metrics** in production
3. **Adjust configuration** based on your speed/quality requirements
4. **Consider caching** at the database level for frequently accessed books

The optimizations should provide **50-90% faster response times** while maintaining answer quality!
