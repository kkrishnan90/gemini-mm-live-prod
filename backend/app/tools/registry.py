"""
Tool registry that combines declarations and implementations.

This module exports the travel tool instance containing all function declarations
and provides a mapping of function names to their implementations.
Enhanced with callback-based execution for non-blocking function calls.
"""

import asyncio
import time
import uuid
from typing import Dict, Callable, Any, Optional
from google.genai import types
from .declarations import (
    take_a_nap_declaration,
    NameCorrectionAgent_declaration,
    SpecialClaimAgent_declaration,
    Enquiry_Tool_declaration,
    Eticket_Sender_Agent_declaration,
    ObservabilityAgent_declaration,
    DateChangeAgent_declaration,
    Connect_To_Human_Tool_declaration,
    Booking_Cancellation_Agent_declaration,
    Flight_Booking_Details_Agent_declaration,
    Webcheckin_And_Boarding_Pass_Agent_declaration,
)
from .implementations import (
    take_a_nap,
    NameCorrectionAgent,
    SpecialClaimAgent,
    Enquiry_Tool,
    Eticket_Sender_Agent,
    ObservabilityAgent,
    DateChangeAgent,
    Connect_To_Human_Tool,
    Booking_Cancellation_Agent,
    Flight_Booking_Details_Agent,
    Webcheckin_And_Boarding_Pass_Agent,
)


# Tool instance containing all function declarations
travel_tool = types.Tool(
    function_declarations=[
        take_a_nap_declaration,
        NameCorrectionAgent_declaration,
        SpecialClaimAgent_declaration,
        Enquiry_Tool_declaration,
        Eticket_Sender_Agent_declaration,
        ObservabilityAgent_declaration,
        DateChangeAgent_declaration,
        Connect_To_Human_Tool_declaration,
        Booking_Cancellation_Agent_declaration,
        Flight_Booking_Details_Agent_declaration,
        Webcheckin_And_Boarding_Pass_Agent_declaration,
    ]
)

# Function mapping for easy lookup of implementations
available_functions = {
    "take_a_nap": take_a_nap,
    "NameCorrectionAgent": NameCorrectionAgent,
    "SpecialClaimAgent": SpecialClaimAgent,
    "Enquiry_Tool": Enquiry_Tool,
    "Eticket_Sender_Agent": Eticket_Sender_Agent,
    "ObservabilityAgent": ObservabilityAgent,
    "DateChangeAgent": DateChangeAgent,
    "Connect_To_Human_Tool": Connect_To_Human_Tool,
    "Booking_Cancellation_Agent": Booking_Cancellation_Agent,
    "Flight_Booking_Details_Agent": Flight_Booking_Details_Agent,
    "Webcheckin_And_Boarding_Pass_Agent": Webcheckin_And_Boarding_Pass_Agent,
}


class CallbackBasedFunctionRegistry:
    """Enhanced function registry with callback-based execution for non-blocking function calls."""
    
    def __init__(self, session, functions_dict: Dict[str, Callable] = None, tool_results_queue: asyncio.Queue = None):
        """Initialize the callback-based function registry."""
        self.session = session
        self.functions = functions_dict or available_functions
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.tool_results_queue = tool_results_queue
        
    async def execute_function_async(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        call_id: str
    ) -> Dict[str, Any]:
        """Execute a function asynchronously and return the result."""
        try:
            if function_name not in self.functions:
                raise ValueError(f"Function '{function_name}' not found in registry")

            func = self.functions[function_name]
            
            exec_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
            print(f"\033[92m[{exec_timestamp}] 🛠️ REGISTRY_EXEC_START: Executing {function_name} with args: {arguments}\033[0m")

            # Execute the function
            start_time = time.time()
            if asyncio.iscoroutinefunction(func):
                result = await func(**arguments)
            else:
                # All our tools now take session and queue as the first arguments
                result = func(self.session, self.tool_results_queue, **arguments)
            
            end_time = time.time()
            duration = (end_time - start_time) * 1000
            
            result_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
            print(f"\033[92m[{result_timestamp}] 🎉 REGISTRY_EXEC_COMPLETE: {function_name} completed in {duration:.2f}ms\033[0m")

            return {
                'result': result,
                'status': 'success',
                'function_name': function_name,
                'call_id': call_id
            }

        except Exception as e:
            error_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
            print(f"\033[91m[{error_timestamp}] ❌ REGISTRY_EXEC_ERROR: Error executing {function_name}: {e}\033[0m")
            return {
                'error': str(e),
                'status': 'error',
                'function_name': function_name,
                'call_id': call_id
            }
        finally:
            # Clean up the running task
            if call_id in self.running_tasks:
                del self.running_tasks[call_id]

    def start_function_execution(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        call_id: str
    ) -> asyncio.Task:
        """Start function execution in background and return the task."""
        task_start_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
        print(f"\033[93m[{task_start_timestamp}] 🚀 REGISTRY_TASK_START: Starting background task for {function_name}\033[0m")
        
        task = asyncio.create_task(
            self.execute_function_async(function_name, arguments, call_id)
        )
        self.running_tasks[call_id] = task

        return task
    
    async def _on_function_completed(self, task: asyncio.Task, call_id: str, function_name: str) -> None:
        """Handle completion of a function call with callback pattern."""
        try:
            # Get the function result
            result = await task
            
            completion_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
            print(f"\033[93m[{completion_timestamp}] ✅ REGISTRY_CALLBACK_COMPLETE: Function {function_name} completed via callback\033[0m")
            
            # Extract the actual result message
            if isinstance(result, dict) and 'result' in result:
                result_message = result['result']
            else:
                result_message = str(result)

            # For the non-blocking agents, the immediate response is the "PENDING" message.
            # The final response is sent later by the background task.
            if isinstance(result_message, dict) and result_message.get("status") == "PENDING":
                # Send the pending response to unblock the model
                function_response = types.FunctionResponse(
                    name=function_name,
                    response=result_message,
                    id=call_id
                )
                if self.session:
                    await self.session.send_tool_response(function_responses=[function_response])
                return
            
            # Send function response back to Gemini and allow model to continue
            function_response = types.FunctionResponse(
                name=function_name,
                response=result_message if isinstance(result_message, dict) else {'result': result_message},
                id=call_id
            )
            
            if self.session:
                await self.session.send_tool_response(function_responses=[function_response])
                
                response_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
                print(f"\033[93m[{response_timestamp}] 📤 REGISTRY_RESPONSE_SENT: Function response sent immediately for {function_name}\033[0m")
                
        except Exception as e:
            error_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
            print(f"\033[91m[{error_timestamp}] ❌ REGISTRY_CALLBACK_ERROR: Error in callback for {function_name}: {e}\033[0m")

    async def start_function_with_callback(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        call_id: str = None
    ) -> str:
        """Start function execution with callback-based completion."""
        if call_id is None:
            call_id = str(uuid.uuid4())
            
        # Start function execution in background
        task = self.start_function_execution(function_name, arguments, call_id)
        
        # Set up task completion callback
        await task
        await self._on_function_completed(task, call_id, function_name)
        
        callback_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
        print(f"\033[96m[{callback_timestamp}] 🔄 REGISTRY_CALLBACK_SET: Callback set for {function_name} (ID: {call_id})\033[0m")
        
        return call_id

    def get_running_tasks(self) -> Dict[str, asyncio.Task]:
        """Get all currently running function tasks."""
        return self.running_tasks.copy()

    def is_function_available(self, name: str) -> bool:
        """Check if a function is available in the registry."""
        return name in self.functions


# Create default registry instance for backward compatibility
def create_callback_registry(session, functions_dict: Dict[str, Callable] = None, tool_results_queue: asyncio.Queue = None):
    """Factory function to create a callback-based registry."""
    return CallbackBasedFunctionRegistry(session, functions_dict, tool_results_queue)
