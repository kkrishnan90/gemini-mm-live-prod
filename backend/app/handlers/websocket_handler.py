"""
WebSocket connection handler for Gemini Live API integration.
"""

import asyncio
import uuid
import traceback
import json
from typing import Dict, Any, Optional
from websockets.exceptions import ConnectionClosedOK

from quart import websocket
from google.genai import types

from app.core.config import settings
from app.services.gemini_client import gemini_manager
from app.handlers.client_input_handler import ClientInputHandler
from app.handlers.gemini_response_handler import GeminiResponseHandler
from app.utils.audio import AudioBuffer
from app.tools import (
    take_a_nap, NameCorrectionAgent, SpecialClaimAgent, Enquiry_Tool,
    Eticket_Sender_Agent, ObservabilityAgent, DateChangeAgent,
    Connect_To_Human_Tool, Booking_Cancellation_Agent,
    Flight_Booking_Details_Agent, Webcheckin_And_Boarding_Pass_Agent
)


class WebSocketHandler:
    """Handles WebSocket connections and Gemini Live API integration."""
    
    def __init__(self):
        self.available_functions = {
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
            "Webcheckin_And_Boarding_Pass_Agent": Webcheckin_And_Boarding_Pass_Agent
        }
    
    async def handle_connection(self):
        """Main WebSocket connection handler."""
        connection_start_time = asyncio.get_event_loop().time()
        
        # Initialize connection state and a queue for graceful tool result delivery
        session_state = self._initialize_session_state(connection_start_time)
        tool_results_queue = asyncio.Queue()
        
        try:
            async with self._create_gemini_session() as session:
                # Inform the client that the backend is ready
                await websocket.send(json.dumps({"type": "control", "signal": "server_ready"}))
                
                # Create handlers, passing the queue to the response handler
                client_handler = ClientInputHandler(session, session_state)
                gemini_handler = GeminiResponseHandler(
                    session, session_state, self.available_functions, tool_results_queue
                )
                
                # Create and run tasks
                forward_task = asyncio.create_task(
                    client_handler.handle_client_input(),
                    name="ClientInputForwarder"
                )
                receive_task = asyncio.create_task(
                    gemini_handler.handle_gemini_responses(),
                    name="GeminiReceiver"
                )
                
                try:
                    await asyncio.gather(forward_task, receive_task)
                except Exception as e_gather:
                    traceback.print_exc()
                finally:
                    await self._cleanup_tasks(forward_task, receive_task, session_state)
                    
        except asyncio.CancelledError:
            pass
        except TimeoutError as e_timeout:
            traceback.print_exc()
        except Exception as e_ws_main:
            traceback.print_exc()
    
    def _initialize_session_state(self, connection_start_time: float) -> Dict[str, Any]:
        """Initialize session state for the connection."""
        return {
            'connection_start_time': connection_start_time,
            'current_session_handle': None,
            'client_ready_for_audio': False,
            'mic_audio_buffer': AudioBuffer(),
            'gemini_audio_buffer': AudioBuffer(),
            'audio_sequence_counter': 0,
            'active_processing': True,
            'current_user_utterance_id': None,
            'accumulated_user_speech_text': "",
            'current_model_utterance_id': None,
            'accumulated_model_speech_text': ""
        }
    
    def _create_gemini_session(self):
        """Create and return Gemini Live API session."""
        client = gemini_manager.initialize_client()
        config = gemini_manager.get_live_config()
        
        return client.aio.live.connect(
            model=settings.GEMINI_MODEL_NAME,
            config=config
        )

    
    async def _cleanup_tasks(self, forward_task, receive_task, session_state):
        """Clean up asyncio tasks."""
        session_state['active_processing'] = False
        
        # Cancel tasks if not done
        if not forward_task.done():
            forward_task.cancel()
        if not receive_task.done():
            receive_task.cancel()
        
        # Wait for task cleanup