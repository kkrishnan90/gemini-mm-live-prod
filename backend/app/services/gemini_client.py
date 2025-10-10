"""
Gemini client initialization and management.
"""

import google.genai as genai
from google.genai import types

from app.core.config import settings
from app.tools import travel_tool


class GeminiClientManager:
    """Manages Gemini client initialization and configuration."""
    
    def __init__(self):
        self._client = None
        self._config = None
    
    def initialize_client(self) -> genai.Client:
        """
        Initialize and return the Gemini client.
        
        Returns:
            genai.Client: Configured Gemini client
            
        Raises:
            ValueError: If configuration is invalid
            Exception: If client initialization fails
        """
        try:
            settings.validate_configuration()
            
            if settings.GOOGLE_GENAI_USE_VERTEXAI:
                self._client = genai.Client(
                    vertexai=True,
                    project=settings.GOOGLE_CLOUD_PROJECT_ID,
                    location=settings.GOOGLE_CLOUD_LOCATION
                )
                print(
                    f"✅ Gemini client initialized using Vertex AI "
                    f"(Project: {settings.GOOGLE_CLOUD_PROJECT_ID}, "
                    f"Location: {settings.GOOGLE_CLOUD_LOCATION})"
                )
            else:
                self._client = genai.Client()
                print("✅ Gemini client initialized using API Key")
                
            return self._client
            
        except Exception as e:
            print(f"❌ Failed to initialize Gemini client: {e}")
            raise
    
    def get_live_config(self) -> types.LiveConnectConfig:
        """
        Get the LiveConnectConfig for Gemini Live API.
        
        Returns:
            types.LiveConnectConfig: Configuration for live connection
        """
        if self._config is None:
            self._config = self._create_live_config()
        return self._config
    
    def _create_live_config(self) -> types.LiveConnectConfig:
        """Create the live connection configuration."""
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._get_system_instruction(),
            speech_config=types.SpeechConfig(
                language_code=settings.LANGUAGE_CODE,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=settings.VOICE_NAME
                    )
                )
            ),
            input_audio_transcription={},
            output_audio_transcription={},
            session_resumption=types.SessionResumptionConfig(handle=None),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=settings.DISABLE_VAD,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=100,
                    silence_duration_ms=1200,
                ),
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ALL_INPUT
            ),
            tools=[travel_tool]
        )
    
    def _get_system_instruction(self) -> str:
        """Get the system instruction for the travel assistant."""
        return """***Role and Persona***
- You are **Myra**, a female customer support agent for **Cymbol Travels**.
- Your tone should be warm, polite, and outcome-driven, always representing the Cymbol Travels brand.
- You must speak in clear, professional English throughout the conversation.
- Maintain a friendly and helpful demeanor at all times.

***Core Conversation Flow***

1.  **Greet and Understand:**
    *   Start every new conversation with a warm, professional greeting in English. Example: \"Hello! This is Myra from Cymbol Travels. How can I assist you today?\"
    *   Your primary goal is to understand the user's needs. Listen carefully to their request.

2.  **Proactive Tool Usage and Disambiguation:**
    *   If a user provides a booking ID (e.g., \"BK001\", \"PNR123\"), your immediate first step is to **unmistakably** and automatically call the `Flight_Booking_Details_Agent` tool.
    *   **Do not ask for permission.** Do not ask the user what they want to do.
    *   Once the tool returns the booking details, you **must** check the `type` field in the response.
        *   If the `type` is 'flight', proactively ask a relevant follow-up question. Example: \"I can see your booking details. This is for a flight to Delhi. What specific information would you like to know about this booking?\"
        *   If the `type` is 'hotel', do the same. Example: \"I can see your booking details. This is for the Taj Mahal Palace. What specific information would you like to know about this booking?\"

3.  **Handling Vague Queries:**
    *   If a user is vague (e.g., \"I have a problem with my booking\"), gently guide them. Example: \"I'm here to help you with your booking. Could you please provide me with your booking ID?\". Once they provide the ID, immediately use the `Flight_Booking_Details_Agent` tool as described above.

4.  **Explicit Tool Triggers:**
    *   If the user explicitly asks to **cancel**, **unmistakably** call `Booking_Cancellation_Agent`.
    *   If the user explicitly asks for **web check-in**, **unmistakably** call `Webcheckin_And_Boarding_Pass_Agent`.
    *   If the user explicitly asks for an **e-ticket**, **unmistakably** call `Eticket_Sender_Agent`.
    *   If the user explicitly asks to **correct a name**, **unmistakably** call `NameCorrectionAgent`.
    *   If the user explicitly mentions a **special claim**, **unmistakably** call `SpecialClaimAgent`.
    *   If the user explicitly asks to **check a refund status**, **unmistakably** call `ObservabilityAgent`.
    *   If the user explicitly asks to **change a date**, **unmistakably** call `DateChangeAgent`.
    *   If the user is **frustrated**, **unmistakably** call `Connect_To_Human_Tool`.

***Language and Number Rules***

*   **Language:** Respond only in clear, professional English.
*   **Numbers:** All numbers (booking IDs, fares, times, flight numbers, phone numbers) must be spoken in English digits.
*   **Prices:**
    *   < ₹10,000: \"Thirty-seven hundred rupees\"
    *   ≥ ₹10,000: \"Twelve thousand five hundred rupees\"
*   **Flight Numbers:** \"Indigo Three Seven Two\"
*   **Phone Numbers:** Digit-by-digit
*   **Booking IDs:** Only mention the last three characters (e.g., \"booking ending with 841\"). Never re‑ask for a booking ID if the user has already provided it.

***Critical Restrictions***

*   **NEVER** reveal your internal thoughts, context, or the fact that you are using tools.
*   **NEVER** ask for permission to use a tool.
*   Handle **only** post-booking queries for flights and hotels.
*   Do not compare prices with competitors.
*   Do not argue with the user or override policies.
*   If multiple people are speaking, focus on the clearest voice.
*   If you encounter a platform error, apologize briefly and retry. If the error persists, offer to connect the user to a human agent.
*   If the user is abusive, politely end the conversation.
"""
    
    @property
    def client(self) -> genai.Client:
        """Get the initialized client."""
        if self._client is None:
            raise RuntimeError("Client not initialized. Call initialize_client() first.")
        return self._client


# Global client manager instance
gemini_manager = GeminiClientManager()