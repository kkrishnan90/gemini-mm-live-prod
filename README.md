# Cymbol Travels - Multimodal Live Travel Assistant

**Cymbol Travels** is a fictitious travel company showcasing cutting-edge AI-powered customer support. This project demonstrates a real-time voice-enabled travel assistant built with Google's Gemini Live API, featuring WebSocket-based audio streaming and comprehensive travel booking operations.

## Core features of the application

- **Real-time Audio Streaming**: WebSocket-based bidirectional audio with Gemini Live API.
- **Voice Activity Detection**: Configurable sensitivity settings with smart start/end detection.
- **Audio Enhancement**: Noise suppression worklets and audio quality monitoring.
- **Buffer Management**: Overflow protection and configurable audio queue management.
- **Network Resilience**: Connection stability management during unstable network conditions.
- **Booking Management**: Retrieve detailed flight/hotel booking information with full itineraries.
- **Cancellation Processing**: Quote-and-confirm cancellation flow with penalty calculations.
- **Web Check-in & Boarding**: Automated check-in with boarding pass generation.
- **E-ticket Delivery**: Multi-channel e-ticket sending (email, SMS, WhatsApp).
- **Date Modifications**: Change travel dates with dynamic penalty calculations.
- **Name Corrections**: Handle various types of name correction requests.
- **Special Claims**: Process and track special assistance requests.
- **Multi-language Support**: Supports 10+ languages including English, Hindi, and Spanish.
- **Advanced Monitoring & Debugging**: Structured logging, real-time tool tracking, and audio diagnostics.

## Project Structure

The application is composed of a Python/Quart backend and a React.js frontend.

### Backend (`backend/`)

The backend is a Python server built with the Quart web framework. It handles WebSocket connections, streams audio to and from the Gemini Live API, and executes tool calls for travel-related queries.

```
backend/
│
├── app/
│   ├── core/
│   │   ├── app.py               # Main Quart application factory and entry point
│   │   └── config.py            # Manages environment variables and settings
│   │
│   ├── data/
│   │   └── travel_mock_data.py  # Provides mock data for travel services
│   │
│   ├── handlers/
│   │   ├── websocket_handler.py # Orchestrates the WebSocket session lifecycle
│   │   ├── client_input_handler.py # Handles incoming messages from the client
│   │   ├── gemini_response_handler.py # Processes responses from the Gemini API
│   │   ├── audio_processor.py   # Manages and processes audio chunks
│   │   ├── tool_call_processor.py # Executes tool calls asynchronously
│   │   └── transcription_processor.py # Processes and forwards transcriptions
│   │
│   ├── routes/
│   │   ├── api.py               # Defines REST API endpoints (e.g., for logs)
│   │   └── websocket.py         # Defines the main WebSocket route
│   │
│   ├── services/
│   │   └── gemini_client.py     # Manages the connection to the Gemini Live API
│   │
│   ├── tools/
│   │   ├── declarations.py      # Defines the function schemas for the Gemini API
│   │   ├── implementations.py   # Contains the business logic for each tool
│   │   └── registry.py          # Creates and manages the tool registry
│   │
│   └── utils/
│       ├── audio.py             # Audio utility classes (e.g., AudioBuffer)
│       └── logging.py           # Utilities for capturing and serving logs
│
├── main.py                      # Application entry point for the server
├── requirements.txt             # Python package dependencies
└── Dockerfile                   # Container definition for deployment
```

### Frontend (`frontend/`)

The frontend is a React.js single-page application that provides the user interface. It captures audio from the microphone, sends it to the backend via WebSockets, and displays the real-time transcription and responses from the Gemini assistant.

```
frontend/
│
├── public/
│   ├── index.html               # The main HTML file for the React app
│   └── audio-processor.js       # The AudioWorklet for processing microphone input
│
├── src/
│   ├── components/              # Reusable React components for the UI
│   │   ├── MainPanel.js         # Displays the conversation transcript
│   │   ├── ConsolePanel.js      # Shows real-time application and tool logs
│   │   ├── ControlBar.js        # Container for action buttons and status indicators
│   │   └── StatusIndicators.js  # Displays connection, audio, and network status
│   │
│   ├── hooks/                   # Custom React Hooks for managing complex logic
│   │   ├── useSession.js        # Master hook that coordinates all other hooks
│   │   ├── useAudio.js          # Manages the entire audio pipeline (capture, VAD, etc.)
│   │   ├── useCommunication.js  # Manages the WebSocket connection and data flow
│   │   ├── useToolLogs.js       # Fetches and displays tool logs from the backend
│   │   └── useAppLogger.js      # Manages client-side application logs
│   │
│   ├── utils/                   # Utility classes and functions
│   │   ├── audioBufferManager.js # Manages adaptive audio buffering
│   │   ├── networkResilienceManager.js # Handles network backpressure and reliability
│   │   ├── webSocketUtils.js    # Provides helper functions for WebSocket communication
│   │   └── scriptProcessorFallback.js # Fallback for browsers without AudioWorklet
│   │
│   ├── App.js                   # The main application component
│   └── index.js                 # The entry point for the React application
│
├── package.json                 # Project dependencies and scripts
└── .env.example                 # Example environment variables for the frontend
```

## Installation of backend

1.  **Navigate to the backend directory**:
    ```bash
    cd backend
    ```
2.  **Create and activate a virtual environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```
3.  **Install the required dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Running the backend locally - on Vertex AI

1.  **Set up the environment variables**:
    - Copy the `.env.example` file to `.env`.
    - Set `GOOGLE_GENAI_USE_VERTEXAI` to `true`.
    - Set `GOOGLE_CLOUD_PROJECT_ID` to your Google Cloud project ID.
    - Set `GOOGLE_CLOUD_LOCATION` to your Google Cloud location (e.g., `us-central1`).
2.  **Start the server**:
    ```bash
    hypercorn main:app --bind 0.0.0.0:8000
    ```

## Installation of frontend

1.  **Navigate to the frontend directory**:
    ```bash
    cd frontend
    ```
2.  **Install the required dependencies**:
    ```bash
    npm install
    ```

## Running the frontend locally

1.  **Start the development server**:
    ```bash
    npm start
    ```
2.  **Open your browser and navigate to `http://localhost:3000`.**

## Function calls in the backend

The backend exposes a set of tools for the Gemini model to use for travel-related queries:

- `take_a_nap`: A dummy function for testing long-running tool calls.
- `NameCorrectionAgent`: Handles name corrections and changes for a given booking.
- `SpecialClaimAgent`: Manages special claims for flight-related issues.
- `Enquiry_Tool`: Retrieves relevant documentation for user queries.
- `Eticket_Sender_Agent`: Sends e-tickets to users via email or WhatsApp.
- `ObservabilityAgent`: Tracks the refund status for a given booking.
- `DateChangeAgent`: Quotes penalties or executes date changes for an itinerary.
- `Connect_To_Human_Tool`: Allows the user to connect with a human agent.
- `Booking_Cancellation_Agent`: Quotes penalties or executes cancellations for a booking.
- `Flight_Booking_Details_Agent`: Retrieves the full itinerary for a given booking.
- `Webcheckin_And_Boarding_Pass_Agent`: Handles web check-in and sends boarding passes.

## Critical configurations

The following environment variables are critical for running the backend with Vertex AI:

- `GOOGLE_GENAI_USE_VERTEXAI`: Must be set to `true`.
- `GOOGLE_CLOUD_PROJECT_ID`: Your Google Cloud project ID.
- `GOOGLE_CLOUD_LOCATION`: The Google Cloud location for your project (e.g., `us-central1`).
- `GEMINI_MODEL_NAME`: The Gemini model to use (e.g., `gemini-live-2.5-flash-native-audio`).
- `LANGUAGE_CODE`: The default language for the conversation (e.g., `en-US`).
- `VOICE_NAME`: The voice for the AI assistant (e.g., `Puck`).
- `DISABLE_VAD`: Whether to disable Voice Activity Detection.

## Architecture best practices

This project follows the best practices outlined in the [ARCHITECTURE_BEST_PRACTICES.md](https://github.com/kkrishnan90/gemini-mm-live-demo/blob/main/ARCHITECTURE_BEST_PRACTICES.md) document. This includes a modular architecture, asynchronous processing, and a resilient audio pipeline.

## Disclaimer

This is a demo application and is not 100% production ready which requires further tuning and adapting to the platforms of deployment.
