"""
Handles client input and forwards to Gemini Live API.
"""

import asyncio
import time
from typing import Dict, Any
from websockets.exceptions import ConnectionClosedOK

from quart import websocket
from google.genai import types

from app.core.config import settings
from app.utils.audio import AudioMetadata


class ClientInputHandler:
    """Handles client WebSocket input and forwards to Gemini."""
    
    def __init__(self, session, session_state: Dict[str, Any]):
        self.session = session
        self.session_state = session_state
    
    async def handle_client_input(self):
        """Main client input handling loop."""
        try:
            while self.session_state['active_processing']:
                try:
                    client_data = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    
                    receive_timestamp = time.strftime("%H:%M:%S.%f")[:-3]
                    
                    if isinstance(client_data, str):
                        print(f"\\033[94m[{receive_timestamp}] 📝 CLIENT_TEXT: Received text message from client\\033[0m")
                        await self._handle_text_message(client_data)
                    elif isinstance(client_data, bytes):

                        
                        await self._handle_audio_data(client_data)
                    else:
                        print(f"\\033[94m[{receive_timestamp}] ❓ CLIENT_UNKNOWN: Unexpected data type: {type(client_data)}\\033[0m")
                        
                except asyncio.TimeoutError:
                    if not self.session_state['active_processing']:
                        break
                    continue
                except ConnectionClosedOK:
                    print("INFO: Client closed the connection.")
                    self.session_state['active_processing'] = False
                    break
                except Exception as e_fwd_outer:
                    print(f"Backend: Error in handle_client_input: {type(e_fwd_outer).__name__}: {e_fwd_outer}")
                    self.session_state['active_processing'] = False
                    break
        finally:
            self.session_state['active_processing'] = False
    
    async def _handle_text_message(self, message_text: str):
        """Handle text message from client."""
        if message_text == "CLIENT_AUDIO_READY":
            await self._handle_client_ready_signal()
        else:
            await self._handle_text_prompt(message_text)
    
    async def _handle_client_ready_signal(self):
        """Handle client audio ready signal and flush buffered audio."""
        self.session_state['client_ready_for_audio'] = True
        mic_buffer = self.session_state['mic_audio_buffer']
        
        print(f"🔊 Client audio ready! Flushing {mic_buffer.size()} buffered chunks")
        
        # Flush buffered audio chunks
        buffered_chunks = mic_buffer.flush_all()
        flushed_count = 0
        
        for buffered_chunk in buffered_chunks:
            try:
                if isinstance(buffered_chunk, dict) and buffered_chunk.get("type") == "buffered_audio":
                    # Send metadata first
                    metadata_msg = {
                        "type": "audio_metadata",
                        **buffered_chunk["metadata"],
                        "flushed_by_timeout": True
                    }
                    await websocket.send_json(metadata_msg)
                    await websocket.send(buffered_chunk["audio_data"])
                    
                    flushed_count += 1
                    chunk_size = buffered_chunk["metadata"]["size_bytes"]
                    sequence = buffered_chunk["metadata"]["sequence"]
                    # Chunk flushed successfully
                else:
                    # Fallback for old format
                    await websocket.send(buffered_chunk)
                    flushed_count += 1
            except Exception as send_exc:
                print(f"Error sending buffered audio chunk #{flushed_count}: {send_exc}")
        
        print(f"✅ Flushed {flushed_count} buffered audio chunks")
    
    async def _handle_text_prompt(self, message_text: str):
        """Handle text prompt from client."""
        prompt_for_gemini = message_text
        if message_text == "SEND_TEST_AUDIO_PLEASE":
            prompt_for_gemini = "Hello Gemini, please say 'testing one two three'."
        
        user_content = types.Content(
            role="user",
            parts=[types.Part(text=prompt_for_gemini)]
        )
        await self.session.send_client_content(turns=user_content)
    
    async def _handle_audio_data(self, audio_chunk: bytes):
        """Handle audio data from client."""
        if not audio_chunk:
            print("⚠️ AUDIO WARNING: Received empty audio chunk")
            return
        
        # Send audio to Gemini with the correct parameter based on the configuration
        if settings.GOOGLE_GENAI_USE_VERTEXAI:
            await self.session.send_realtime_input(
                media=types.Blob(
                    mime_type=f"audio/pcm;rate={settings.INPUT_SAMPLE_RATE}",
                    data=audio_chunk
                )
            )
        else:
            await self.session.send_realtime_input(
                audio=types.Blob(
                    mime_type=f"audio/pcm;rate={settings.INPUT_SAMPLE_RATE}",
                    data=audio_chunk
                )
            )
    
    def _get_connection_time(self) -> float:
        """Get time since connection started."""
        current_time = asyncio.get_event_loop().time()
        return current_time - self.session_state['connection_start_time']