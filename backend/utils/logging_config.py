"""
Centralized logging configuration for the InsightLLM backend system.
Provides detailed logging for all Supabase requests, API calls, and system operations.
"""

import logging
import logging.config
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional


class SupabaseRequestFormatter(logging.Formatter):
    """Custom formatter for Supabase requests with colored output and detailed info."""
    
    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Add timestamp
        record.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Color the level name
        if hasattr(record, 'levelname'):
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.colored_levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        
        # Format the message with colors for Supabase operations
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            if '[SUPABASE]' in record.msg:
                record.msg = record.msg.replace('[SUPABASE]', f"\033[94m[SUPABASE]\033[0m")
            elif '[CHATBOT]' in record.msg:
                record.msg = record.msg.replace('[CHATBOT]', f"\033[93m[CHATBOT]\033[0m")
            elif '[API]' in record.msg:
                record.msg = record.msg.replace('[API]', f"\033[92m[API]\033[0m")
        
        # Use the parent formatter
        formatted = super().format(record)
        return formatted


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None, enable_colors: bool = True):
    """
    Set up comprehensive logging configuration for the entire system.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        enable_colors: Whether to enable colored output in console
    """
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create logs directory if needed
    if log_file and not os.path.exists(os.path.dirname(log_file)):
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Console handler configuration
    console_handler_config = {
        'class': 'logging.StreamHandler',
        'level': numeric_level,
        'stream': 'ext://sys.stdout'
    }
    
    if enable_colors:
        console_handler_config['formatter'] = 'colored'
    else:
        console_handler_config['formatter'] = 'detailed'
    
    # Base logging configuration
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'detailed': {
                'format': '%(timestamp)s | %(colored_levelname)s | %(name)s:%(lineno)d | %(message)s',
                '()': SupabaseRequestFormatter,
            },
            'colored': {
                'format': '%(timestamp)s | %(colored_levelname)s | %(name)s:%(lineno)d | %(message)s',
                '()': SupabaseRequestFormatter,
            },
            'json': {
                'format': '%(timestamp)s | %(levelname)s | %(name)s | %(message)s',
                'class': 'logging.Formatter'
            }
        },
        'handlers': {
            'console': console_handler_config
        },
        'loggers': {
            # Root logger
            '': {
                'level': numeric_level,
                'handlers': ['console'],
                'propagate': False
            },
            # Supabase service logger
            'backend.db.supabase_service': {
                'level': 'DEBUG',
                'handlers': ['console'],
                'propagate': False
            },
            # Chatbot agent logger
            'backend.agents.chatbot_agent': {
                'level': 'DEBUG',
                'handlers': ['console'],
                'propagate': False
            },
            # API routers logger
            'backend.api': {
                'level': 'DEBUG',
                'handlers': ['console'],
                'propagate': False
            },
            # FastAPI logger
            'uvicorn': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'uvicorn.access': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            }
        }
    }
    
    # Add file handler if log file is specified
    if log_file:
        config['handlers']['file'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': numeric_level,
            'formatter': 'json',
            'filename': log_file,
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'encoding': 'utf8'
        }
        
        # Add file handler to all loggers
        for logger_config in config['loggers'].values():
            if 'file' not in logger_config['handlers']:
                logger_config['handlers'].append('file')
    
    # Apply the configuration
    logging.config.dictConfig(config)
    
    # Test the configuration
    logger = logging.getLogger(__name__)
    logger.info(f"🚀 Logging system initialized - Level: {log_level}")
    
    if log_file:
        logger.info(f"📝 Log file: {log_file}")
    
    return logger


def log_supabase_request(logger, operation: str, table: str, data: Dict[str, Any] = None, filters: Dict[str, Any] = None):
    """
    Log Supabase request with detailed information.
    
    Args:
        logger: Logger instance
        operation: Operation type (INSERT, SELECT, UPDATE, DELETE, RPC)
        table: Table name
        data: Data being sent (for INSERT/UPDATE)
        filters: Filters being applied (for SELECT/UPDATE/DELETE)
    """
    log_message = f"[SUPABASE] 📤 {operation} on table '{table}'"
    
    if filters:
        filter_str = ', '.join([f"{k}={v}" for k, v in filters.items()])
        log_message += f" | Filters: {filter_str}"
    
    if data:
        # Log data size and keys, not full content for privacy
        if isinstance(data, dict):
            data_info = f"Keys: {list(data.keys())}"
        elif isinstance(data, list):
            data_info = f"Array length: {len(data)}"
        else:
            data_info = f"Type: {type(data).__name__}"
        log_message += f" | Data: {data_info}"
    
    logger.info(log_message)


def log_supabase_response(logger, operation: str, table: str, response_data: Any, execution_time: float = None, error: str = None):
    """
    Log Supabase response with detailed information.
    
    Args:
        logger: Logger instance
        operation: Operation type
        table: Table name
        response_data: Response data from Supabase
        execution_time: Time taken for the operation
        error: Error message if operation failed
    """
    if error:
        logger.error(f"[SUPABASE] ❌ {operation} on '{table}' FAILED | Error: {error}")
        return
    
    log_message = f"[SUPABASE] 📥 {operation} on '{table}' SUCCESS"
    
    if response_data:
        if isinstance(response_data, list):
            log_message += f" | Returned: {len(response_data)} rows"
        elif isinstance(response_data, dict):
            log_message += f" | Returned: 1 object"
        else:
            log_message += f" | Returned: {type(response_data).__name__}"
    else:
        log_message += " | Returned: No data"
    
    if execution_time:
        log_message += f" | Time: {execution_time:.3f}s"
    
    logger.info(log_message)


def log_api_request(logger, method: str, endpoint: str, user_id: str = None, request_data: Dict[str, Any] = None):
    """
    Log API request with detailed information.
    
    Args:
        logger: Logger instance
        method: HTTP method
        endpoint: API endpoint
        user_id: User ID making the request
        request_data: Request payload
    """
    log_message = f"[API] 📤 {method} {endpoint}"
    
    if user_id:
        log_message += f" | User: {user_id[:8]}..."
    
    if request_data:
        data_keys = list(request_data.keys()) if isinstance(request_data, dict) else []
        log_message += f" | Payload keys: {data_keys}"
    
    logger.info(log_message)


def log_api_response(logger, method: str, endpoint: str, status_code: int, execution_time: float = None, error: str = None):
    """
    Log API response with detailed information.
    
    Args:
        logger: Logger instance
        method: HTTP method
        endpoint: API endpoint
        status_code: HTTP status code
        execution_time: Time taken for the request
        error: Error message if request failed
    """
    status_emoji = "✅" if 200 <= status_code < 300 else "❌" if status_code >= 400 else "⚠️"
    
    log_message = f"[API] 📥 {method} {endpoint} {status_emoji} {status_code}"
    
    if execution_time:
        log_message += f" | Time: {execution_time:.3f}s"
    
    if error:
        log_message += f" | Error: {error}"
    
    logger.info(log_message)


# Default logger instance
logger = None

def get_logger(name: str = None) -> logging.Logger:
    """Get a configured logger instance."""
    global logger
    if logger is None:
        logger = setup_logging(
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE"),
            enable_colors=os.getenv("LOG_COLORS", "true").lower() == "true"
        )
    
    return logging.getLogger(name or __name__)


# Initialize logging when module is imported
if not logger:
    logger = get_logger()
