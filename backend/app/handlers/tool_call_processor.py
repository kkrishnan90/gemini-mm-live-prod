"""
Handles tool call processing and execution.
Enhanced with callback-based execution for non-blocking function calls.
"""

import asyncio
import traceback
import time
import uuid
from typing import Dict, Any, Callable, List

from quart import websocket
from google.genai import types
from app.tools.registry import CallbackBasedFunctionRegistry


class ToolCallProcessor:
    """Processes tool calls from Gemini Live API."""
    
    def __init__(self, session, available_functions: Dict[str, Callable], tool_results_queue: asyncio.Queue):
        self.session = session
        self.available_functions = available_functions
        self.tool_results_queue = tool_results_queue
        
        # Create callback-based registry for enhanced execution
        self.callback_registry = CallbackBasedFunctionRegistry(session, available_functions, self.tool_results_queue)
        
        # Keep original implementation for fallback/compatibility
        self.use_callback_pattern = True  # Enable callback-based execution
    
    async def process_tool_call(self, tool_call):
        """Process tool call from Gemini with NON-BLOCKING execution."""
        if self.use_callback_pattern:
            if tool_call.function_calls:
                fc = tool_call.function_calls[0]
                function_name = fc.name
                function_args = dict(fc.args)
                call_id = fc.id if hasattr(fc, 'id') else None
                
                await self.callback_registry.start_function_with_callback(
                    function_name, function_args, call_id
                )
