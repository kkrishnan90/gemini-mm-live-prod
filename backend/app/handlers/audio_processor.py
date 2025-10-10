"""
Handles audio processing and buffering for Gemini responses.
"""

import asyncio
from typing import Dict, Any

from quart import websocket

from app.core.config import settings
from app.utils.audio import AudioBuffer, AudioMetadata


class AudioProcessor:
    """Processes audio responses from Gemini Live API."""
    
    def __init__(self, session_state: Dict[str, Any]):
        self.session_state = session_state
    
    async def process_audio_response(self, audio_data: bytes):
        """Process audio data from Gemini."""
        # Generate correlation ID for this Gemini response
        correlation_id = f"gemini_response_{int(asyncio.get_event_loop().time() * 1000)}_{id(audio_data)}"
        current_time = asyncio.get_event_loop().time()
        time_since_connection = current_time - self.session_state['connection_start_time']
        
        # Process audio data from Gemini
        
        try:
            # Auto-flush buffer after timeout if client isn't ready
            if not self.session_state['client_ready_for_audio'] and time_since_connection > settings.BUFFER_TIMEOUT_SECONDS:
                await self._handle_buffer_timeout()
            
            if self.session_state['client_ready_for_audio']:
                await self._send_audio_immediately(audio_data, current_time, correlation_id)
            else:
                await self._buffer_audio(audio_data, current_time, time_since_connection, correlation_id)
                
        except Exception as send_exc:
            print(f"Backend: Error processing audio data: {send_exc} [ID: {correlation_id}]")
            self.session_state['active_processing'] = False
    
    async def _handle_buffer_timeout(self):
        """Handle buffer timeout when client isn't ready."""
        buffer = self.session_state['gemini_audio_buffer']
        time_since_connection = (
            asyncio.get_event_loop().time() - self.session_state['connection_start_time']
        )
        
        print(f"⏰ Client readiness timeout - auto-flushing {buffer.size()} buffered chunks")
        
        self.session_state['client_ready_for_audio'] = True
        
        # Flush buffered audio
        buffered_chunks = buffer.flush_all()
        timeout_flushed_count = 0
        
        for buffered_chunk in buffered_chunks:
            try:
                if isinstance(buffered_chunk, dict) and buffered_chunk.get("type") == "buffered_audio":
                    # Send metadata first
                    metadata = buffered_chunk["metadata"]
                    metadata["flushed_by_timeout"] = True
                    metadata_msg = {"type": "audio_metadata", **metadata}
                    
                    await websocket.send_json(metadata_msg)
                    await websocket.send(buffered_chunk["audio_data"])
                    
                    timeout_flushed_count += 1
                    chunk_size = metadata["size_bytes"]
                    duration = metadata["expected_duration_ms"]
                    # Timeout-flushed chunk sent
                else:
                    # Fallback for old format
                    await websocket.send(buffered_chunk)
                    timeout_flushed_count += 1
            except Exception as send_exc:
                print(f"Error sending timeout-flushed chunk #{timeout_flushed_count}: {send_exc}")
        
        print(f"✅ Timeout flushed {timeout_flushed_count} chunks")
    
    async def _send_audio_immediately(self, audio_data: bytes, current_time: float, correlation_id: str = None):
        """Send audio immediately to ready client."""
        chunk_size = len(audio_data)
        
        # Generate sequence number
        self.session_state['audio_sequence_counter'] += 1
        sequence_num = self.session_state['audio_sequence_counter']
        
        # Create metadata
        audio_metadata = AudioMetadata.create_metadata(
            sequence=sequence_num,
            chunk_size=chunk_size,
            sample_rate=settings.OUTPUT_SAMPLE_RATE,
            timestamp=current_time
        )
        
        # Send playback start signal to frontend for VAD correlation
        await websocket.send_json({
            "type": "gemini_playback_state", 
            "playing": True,
            "sequence": sequence_num,
            "correlation_id": correlation_id,
            "vad_should_activate": not settings.DISABLE_VAD
        })
        
        # Send metadata first, then audio
        await websocket.send_json(audio_metadata)
        await websocket.send(audio_data)
        

    
    async def _buffer_audio(self, audio_data: bytes, current_time: float, time_since_connection: float, correlation_id: str = None):
        """Buffer audio when client is not ready."""
        buffer = self.session_state['gemini_audio_buffer']
        
        # Generate sequence number
        self.session_state['audio_sequence_counter'] += 1
        sequence_num = self.session_state['audio_sequence_counter']
        
        # Add to buffer
        audio_chunk_data, removed_chunks = buffer.add_audio_chunk(
            audio_data,
            {"sequence": sequence_num, "timestamp": current_time}
        )
        
        chunk_size = len(audio_data)
        expected_duration = audio_chunk_data["metadata"]["expected_duration_ms"]
        
        print(f"📦 GEMINI BUFFERING: id={correlation_id}, seq={sequence_num} ({chunk_size} bytes, {expected_duration:.1f}ms) - client not ready (t+{time_since_connection:.1f}s)")
        
        # Handle buffer pressure
        await self._handle_buffer_pressure(buffer)
        
        # Handle overflow
        if removed_chunks:
            await self._handle_buffer_overflow(removed_chunks, buffer)
    
    async def _handle_buffer_pressure(self, buffer: AudioBuffer):
        """Handle buffer pressure warnings."""
        pressure_level = buffer.get_pressure_level()
        
        if pressure_level in ["medium", "high"]:
            pressure_warning = AudioMetadata.create_buffer_pressure_warning(
                buffer_size=buffer.size(),
                max_size=buffer.max_size,
                level=pressure_level
            )
            
            try:
                await websocket.send_json(pressure_warning)
                print(f"⚠️ Buffer pressure warning sent: {pressure_level} ({buffer.size()}/{buffer.max_size})")
            except Exception as e:
                print(f"Failed to send buffer pressure warning: {e}")
    
    async def _handle_buffer_overflow(self, removed_chunks, buffer: AudioBuffer):
        """Handle buffer overflow and send truncation warning."""
        truncation_warning = AudioMetadata.create_truncation_warning(
            chunks_removed=len(removed_chunks),
            buffer_size=buffer.size()
        )
        
        try:
            await websocket.send_json(truncation_warning)
            print(f"🗑️ Buffer overflow: removed {len(removed_chunks)} chunks, sent truncation warning")
        except Exception as e:
            print(f"Failed to send truncation warning: {e}")