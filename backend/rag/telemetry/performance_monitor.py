"""
Performance monitoring utilities for RAG pipeline.
"""
import time
import logging
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetrics:
    """Performance metrics for RAG operations."""
    total_time: float = 0.0
    planning_time: float = 0.0
    retrieval_time: float = 0.0
    synthesis_time: float = 0.0
    embedding_time: float = 0.0
    iterations: int = 0
    evidence_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    subquestions_generated: int = 0
    parallel_retrievals: int = 0
    early_stopped: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_time": round(self.total_time, 3),
            "planning_time": round(self.planning_time, 3),
            "retrieval_time": round(self.retrieval_time, 3),
            "synthesis_time": round(self.synthesis_time, 3),
            "embedding_time": round(self.embedding_time, 3),
            "iterations": self.iterations,
            "evidence_count": self.evidence_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "subquestions_generated": self.subquestions_generated,
            "parallel_retrievals": self.parallel_retrievals,
            "early_stopped": self.early_stopped,
            "efficiency_score": self._calculate_efficiency_score()
        }
    
    def _calculate_efficiency_score(self) -> float:
        """Calculate an efficiency score (0-1, higher is better)."""
        if self.total_time == 0:
            return 0.0
        
        # Factors that improve efficiency
        cache_hit_ratio = self.cache_hits / max(self.cache_hits + self.cache_misses, 1)
        evidence_per_second = self.evidence_count / max(self.total_time, 0.1)
        
        # Normalize and combine factors
        score = (
            cache_hit_ratio * 0.3 +  # 30% weight on caching
            min(evidence_per_second / 10, 1.0) * 0.4 +  # 40% weight on evidence throughput
            (1.0 if self.early_stopped else 0.5) * 0.3  # 30% weight on early stopping
        )
        
        return round(score, 3)


class PerformanceMonitor:
    """Monitor and track performance metrics for RAG operations."""
    
    def __init__(self):
        self.current_metrics: Optional[PerformanceMetrics] = None
    
    @asynccontextmanager
    async def track_operation(self, operation_name: str):
        """Track the performance of an async operation."""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            logger.info(f"Performance: {operation_name} took {duration:.3f}s")
    
    @contextmanager
    def track_sync_operation(self, operation_name: str):
        """Track the performance of a sync operation."""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            logger.info(f"Performance: {operation_name} took {duration:.3f}s")
    
    def start_session(self) -> PerformanceMetrics:
        """Start a new performance monitoring session."""
        self.current_metrics = PerformanceMetrics()
        return self.current_metrics
    
    def log_metrics(self, metrics: PerformanceMetrics):
        """Log performance metrics."""
        logger.info(f"RAG Performance Metrics: {metrics.to_dict()}")
        
        # Log warnings for performance issues
        if metrics.total_time > 20:
            logger.warning(f"Slow RAG response: {metrics.total_time:.2f}s")
        if metrics.cache_hits + metrics.cache_misses > 0:
            hit_ratio = metrics.cache_hits / (metrics.cache_hits + metrics.cache_misses)
            if hit_ratio < 0.3:
                logger.warning(f"Low cache hit ratio: {hit_ratio:.2%}")


# Global performance monitor instance
_performance_monitor = PerformanceMonitor()

def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    return _performance_monitor
