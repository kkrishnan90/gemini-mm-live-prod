"""
Handles responses from Gemini Live API and forwards to client.
"""

import asyncio
import uuid
import traceback
import time
from typing import Dict, Any, Callable

from quart import websocket
from google.genai import types
from websockets.exceptions import ConnectionClosedOK

from app.core.config import settings
from app.utils.audio import AudioBuffer, AudioMetadata
from app.handlers.audio_processor import AudioProcessor
from app.handlers.transcription_processor import TranscriptionProcessor
from app.handlers.tool_call_processor import ToolCallProcessor


class GeminiResponseHandler:
    """Handles responses from Gemini Live API."""
    
    def __init__(self, session, session_state: Dict[str, Any], 
                 available_functions: Dict[str, Callable], tool_results_queue: asyncio.Queue):
        self.session = session
        self.session_state = session_state
        self.available_functions = available_functions
        self.tool_results_queue = tool_results_queue
        
        # Speech state tracking for coordinated tool response delivery
        self.speech_state = {
            'is_gemini_speaking': False,
            'current_turn_id': None,
            'last_audio_timestamp': None,
            'speech_start_time': None,
            'pending_tool_responses': 0
        }
        
        # Initialize processors
        self.audio_processor = AudioProcessor(session_state)
        self.transcription_processor = TranscriptionProcessor(session_state)
        self.tool_processor = ToolCallProcessor(session, available_functions, tool_results_queue)
        self.is_tool_response = False
        self.audio_processing_lock = asyncio.Lock()
        self.processed_tool_calls = set()

    def set_is_tool_response(self, value: bool):
        """Sets the flag to indicate the next response is from a tool call."""
        self.is_tool_response = value
    
    async def handle_gemini_responses(self):
        """Main Gemini response handling loop."""
        try:
            while self.session_state['active_processing']:
                had_activity = False
                
                async for response in self.session.receive():
                    had_activity = True
                    if not self.session_state['active_processing']:
                        break
                    
                    await self._process_response(response)

                    # Enhanced tool response delivery - coordinate with speech state

                    
                    # Also check for speech completion based on audio gap
                    await self._check_speech_completion_and_deliver_responses()
                    
                    if not self.session_state['active_processing']:
                        break
                
                # Small delay if no activity
                if not had_activity and self.session_state['active_processing']:
                    await asyncio.sleep(0.1)
                    

        finally:
            self.session_state['active_processing'] = False
    
    async def _process_response(self, response):
        """Process individual response from Gemini."""
        try:
            # Handle session updates
            await self._handle_session_updates(response)
            
            # Handle audio data
            if response.data is not None:
                async with self.audio_processing_lock:
                    # Track speech state - Gemini is speaking when sending audio
                    if not self.speech_state['is_gemini_speaking']:
                        self.speech_state['is_gemini_speaking'] = True
                        self.speech_state['speech_start_time'] = time.time()
                    
                    self.speech_state['last_audio_timestamp'] = time.time()
                    await self.audio_processor.process_audio_response(response.data)
            
            # Handle server content
            elif response.server_content:
                await self._handle_server_content(response.server_content)
            
            # Handle tool calls
            elif response.tool_call:
                # This should be NON-BLOCKING
                await self.tool_processor.process_tool_call(response.tool_call)
                await self._deliver_queued_tool_responses("tool_call_processed")
            
            # Handle errors
            elif hasattr(response, 'error') and response.error:
                await self._handle_error(response.error)
            else:
                pass
                
        except Exception as e:
            traceback.print_exc()
            self.session_state['active_processing'] = False

    
    async def _handle_session_updates(self, response):
        """Handle session resumption updates."""
        if response.session_resumption_update:
            update = response.session_resumption_update
            if update.resumable and update.new_handle:
                self.session_state['current_session_handle'] = update.new_handle
        
        if hasattr(response, 'session_handle') and response.session_handle:
            new_handle = response.session_handle
            if new_handle != self.session_state['current_session_handle']:
                self.session_state['current_session_handle'] = new_handle
    
    async def _handle_server_content(self, server_content):
        """Handle server content responses."""
        # Handle interruption
        if server_content.interrupted:
            await self._handle_interruption()
        
        # Handle transcriptions
        await self.transcription_processor.process_transcriptions(server_content)
        
        # Handle unhandled content
        await self._handle_unhandled_content(server_content)

    async def _handle_interruption(self):
        """Handle Gemini interruption signal."""
        if not self.is_tool_response:
            try:
                await websocket.send_json({"type": "interrupt_playback"})
            except Exception as send_exc:
                self.session_state['active_processing'] = False

    async def _handle_unhandled_content(self, server_content):
        """Handle unhandled server content."""
        is_transcription_related = (
            (hasattr(server_content, 'input_transcription') and server_content.input_transcription) or
            (hasattr(server_content, 'output_transcription') and server_content.output_transcription)
        )
        
        is_control_signal = (
            (hasattr(server_content, 'generation_complete') and server_content.generation_complete) or
            (hasattr(server_content, 'turn_complete') and server_content.turn_complete) or
            (hasattr(server_content, 'interrupted') and server_content.interrupted)
        )
        
        if not is_transcription_related and not is_control_signal:
            unhandled_text = self._extract_unhandled_text(server_content)
            if unhandled_text:
                pass
            elif not hasattr(server_content, 'tool_call'):
                pass

    
    def _extract_unhandled_text(self, server_content) -> str:
        """Extract unhandled text from server content."""
        unhandled_text = None
        
        if hasattr(server_content, 'text') and server_content.text:
            unhandled_text = server_content.text
        elif (hasattr(server_content, 'model_turn') and server_content.model_turn and 
              hasattr(server_content.model_turn, 'parts')):
            for part in server_content.model_turn.parts:
                if part.text:
                    unhandled_text = (unhandled_text + " " if unhandled_text else "") + part.text
        elif hasattr(server_content, 'output_text') and server_content.output_text:
            unhandled_text = server_content.output_text
        
        return unhandled_text
    
    async def _deliver_queued_tool_responses(self, trigger_reason: str):
        """Deliver all queued tool responses with coordination logging."""
        if self.tool_results_queue.empty():
            return
            
        response_count = 0
        while not self.tool_results_queue.empty():
            function_response = await self.tool_results_queue.get()
            
            try:
                # Create a unique ID for the tool response to prevent reprocessing
                # Use the function call ID and the unique ID from the response content
                if 'id' in function_response and 'uuid' in function_response.get('response', {}):
                    tool_call_id = f"{function_response['id']}-{function_response['response']['uuid']}"
                else:
                    # Fallback for older responses or different structures
                    tool_call_id = f"{function_response.get('name')}-{function_response.get('response', {}).get('uuid', '')}"

                if tool_call_id in self.processed_tool_calls:
                    self.tool_results_queue.task_done()
                    continue

                # It's a FunctionResponse object - send as tool response
                self.is_tool_response = True
                await self.session.send_tool_response(function_responses=[types.FunctionResponse(**function_response)])
                
                self.processed_tool_calls.add(tool_call_id)
                
                response_count += 1
            finally:
                self.tool_results_queue.task_done()


    
    async def _check_speech_completion_and_deliver_responses(self):
        """Check if speech has completed based on audio timing and deliver queued responses."""
        current_time = time.time()
        
        # Only check if we think Gemini is speaking and we have queued responses
        if not self.speech_state['is_gemini_speaking'] or self.tool_results_queue.empty():
            return
            
        # Check if enough time has passed since last audio to consider speech complete