"""
Application configuration management.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Settings:
    """Application settings and configuration."""
    
    # Gemini API Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-live-preview")
    
    # Vertex AI Configuration
    GOOGLE_GENAI_USE_VERTEXAI: bool = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    GOOGLE_CLOUD_PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "")
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "")
    
    # Audio Configuration
    INPUT_SAMPLE_RATE: int = 16000
    OUTPUT_SAMPLE_RATE: int = 24000
    DISABLE_VAD: bool = os.getenv("DISABLE_VAD", "true").lower() == "true"
    
    # Buffer Configuration
    MAX_BUFFER_SIZE: int = 5000
    BUFFER_TIMEOUT_SECONDS: float = 3.0
    
    # Voice Configuration
    LANGUAGE_CODE: str = "en-US"
    VOICE_NAME: str = "Zephyr"
    
    @property
    def is_vertex_ai_configured(self) -> bool:
        """Check if Vertex AI is properly configured."""
        if not self.GOOGLE_GENAI_USE_VERTEXAI:
            return False
        return bool(self.GOOGLE_CLOUD_PROJECT_ID and self.GOOGLE_CLOUD_LOCATION)
    
    def validate_configuration(self) -> None:
        """Validate that required configuration is present."""
        if self.GOOGLE_GENAI_USE_VERTEXAI:
            if not self.GOOGLE_CLOUD_PROJECT_ID or not self.GOOGLE_CLOUD_LOCATION:
                raise ValueError(
                    "GOOGLE_CLOUD_PROJECT_ID and GOOGLE_CLOUD_LOCATION must be set "
                    "when using Vertex AI"
                )
        elif not self.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY must be set when not using Vertex AI")


# Global settings instance
settings = Settings()