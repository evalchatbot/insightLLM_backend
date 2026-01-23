"""
FastAPI middleware for logging all incoming requests and outgoing responses.
"""

import time
import json
from typing import Callable
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware

from backend.utils.logging_config import get_logger, log_api_request, log_api_response


class APILoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all API requests and responses with detailed information."""
    
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.logger = get_logger(__name__)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log detailed information."""
        start_time = time.time()
        
        # Extract user information if available
        user_id = None
        if hasattr(request.state, 'user_id'):
            user_id = request.state.user_id
        elif request.headers.get('authorization'):
            # Try to extract user from auth header (simplified)
            auth_header = request.headers.get('authorization', '')
            if 'Bearer ' in auth_header:
                user_id = "authenticated_user"  # Placeholder
        
        # Extract request data
        method = request.method
        url = str(request.url)
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Log request
        request_info = {
            "method": method,
            "url": url,
            "client_ip": client_ip,
            "user_agent": user_agent[:100],  # Limit length
            "query_params": dict(request.query_params),
            "path_params": request.path_params
        }
        
        # Try to get request body for POST/PUT requests (carefully)
        if method in ["POST", "PUT", "PATCH"] and request.headers.get("content-type"):
            try:
                # Create a copy of the request body for logging without consuming the original
                body = await request.body()
                # Reset the request body for the actual handler
                request._body = body
                
                if request.headers.get("content-type", "").startswith("application/json"):
                    try:
                        request_data = json.loads(body.decode())
                        # Don't log sensitive data
                        if isinstance(request_data, dict):
                            filtered_data = {k: v for k, v in request_data.items() 
                                           if k.lower() not in ['password', 'token', 'secret', 'key']}
                            request_info["body_keys"] = list(filtered_data.keys())
                        else:
                            request_info["body_type"] = type(request_data).__name__
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        request_info["body_info"] = f"Non-JSON body ({len(body)} bytes)"
                else:
                    request_info["body_info"] = f"Non-JSON content ({len(body)} bytes)"
            except Exception as e:
                request_info["body_error"] = str(e)
        
        # Log the incoming request
        if "/api/ocr/progress/" not in request.url.path and "/api/essay/status/" not in request.url.path:
            log_api_request(
                self.logger,
                method=method,
                endpoint=request.url.path,
                user_id=user_id,
                request_data=request_info
            )
        
        # Process the request
        try:
            response = await call_next(request)
            execution_time = time.time() - start_time
            
            # Log successful response
            if "/api/ocr/progress/" not in request.url.path and "/api/essay/status/" not in request.url.path:
                log_api_response(
                    self.logger,
                    method=method,
                    endpoint=request.url.path,
                    status_code=response.status_code,
                    execution_time=execution_time
                )
            
            # Log response details for debugging
            # Only log headers for non-polling requests
            if "/api/ocr/progress/" not in request.url.path and "/api/essay/status/" not in request.url.path:
               response_headers = dict(response.headers)
               self.logger.debug(f"[API] Response headers: {response_headers}")
            
            return response
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            # Log error response
            log_api_response(
                self.logger,
                method=method,
                endpoint=request.url.path,
                status_code=500,
                execution_time=execution_time,
                error=str(e)
            )
            
            self.logger.error(f"[API] Request failed with exception: {e}")
            raise


def log_route_handler(route_handler: Callable) -> Callable:
    """Decorator to add detailed logging to individual route handlers."""
    
    async def logged_route_handler(request: Request, *args, **kwargs):
        logger = get_logger("route_handler")
        
        # Get route info
        route_name = route_handler.__name__
        logger.info(f"[API] 🎯 Route handler: {route_name}")
        
        try:
            result = await route_handler(request, *args, **kwargs)
            logger.info(f"[API] ✅ Route handler {route_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"[API] ❌ Route handler {route_name} failed: {e}")
            raise
    
    return logged_route_handler


class LoggedAPIRoute(APIRoute):
    """Custom APIRoute that logs detailed information about each endpoint call."""
    
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()
        
        async def logged_route_handler(request: Request) -> Response:
            logger = get_logger("api_route")
            
            # Log route-specific information
            route_info = {
                "path": self.path,
                "name": self.name,
                "methods": list(self.methods),
                "dependencies": len(self.dependencies) if self.dependencies else 0
            }
            
            logger.debug(f"[API] Route info: {route_info}")
            
            return await original_route_handler(request)
        
        return logged_route_handler


def setup_api_logging(app: FastAPI):
    """Set up comprehensive API logging for the FastAPI application."""
    logger = get_logger(__name__)
    
    # Add the logging middleware
    app.add_middleware(APILoggingMiddleware)
    
    # Replace default route class with logged route class
    app.router.route_class = LoggedAPIRoute
    
    logger.info("🔍 API logging middleware configured")
    
    return app
