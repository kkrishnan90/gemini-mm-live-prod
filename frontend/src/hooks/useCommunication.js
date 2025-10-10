import { useState, useRef, useCallback, useEffect } from "react";
import {
  BACKEND_HOST,
  OUTPUT_SAMPLE_RATE,
  WEBSOCKET_SEND_BUFFER_LIMIT,
  MAX_RETRY_ATTEMPTS,
  RETRY_DELAY_BASE,
  MAX_AUDIO_QUEUE_SIZE,
  JITTER_BUFFER_MIN_FILL,
} from "../utils/constants";
import { sendAudioReadySignal } from "../utils/webSocketUtils";
import { createWavFile } from "../utils/audioUtils.js";
import { debugLog, debugError } from "../config/debug";

export const useCommunication = (
  addLogEntry,
  handleStartListening,
  networkResilienceManagerRef,
  isSessionActive,
  isSessionActiveRef,
  isRecording,
  language,
  isAudioContextReady,
  isPlayingRef,
  stopSystemAudioPlayback,
  adaptiveJitterBufferSize,
  nextStartTimeRef,
  currentAudioSourceRef,
  gainNodeRef,
  jitterBufferRef,
  isPlaybackStartedRef,
  checkWebSocketBackpressure,
  sendAudioChunkWithBackpressure,
  pendingAudioChunks
) => {
  const [isWebSocketConnected, setIsWebSocketConnected] = useState(false);
  const [webSocketStatus, setWebSocketStatus] = useState("N/A");
  const [transcriptionMessages, setTranscriptionMessages] = useState([]);
  const [isWebSocketReady, setIsWebSocketReady] = useState(false);
  const [isServerReady, setIsServerReady] = useState(false); // New state for server readiness
  const socketRef = useRef(null);
  const playbackAudioContextRef = useRef(null);
  const connectionSignalTracker = useRef(new Set());
  const pendingMetadataRef = useRef(new Map());
  const addLogEntryRef = useRef(addLogEntry);

  // Refs for pre-flight buffering
  const isServerReadyRef = useRef(false);
  const preflightBufferRef = useRef([]);
  
  // Update ref when addLogEntry changes
  useEffect(() => {
    addLogEntryRef.current = addLogEntry;
  }, [addLogEntry]);
  
  // Enhanced chunk tracking
  const chunkTrackingRef = useRef({
    totalChunksReceived: 0,
    totalChunksPlayed: 0,
    chunksReceivedCurrentTurn: 0,
    chunksPlayedCurrentTurn: 0,
    currentTurnId: null,
    turnChunkData: {},  // turnId -> {received, played, startTime, endSignalReceived}
    lastChunkReceivedTime: null,
    lastChunkPlayedTime: null,
    turnEndSignals: new Set(), // Track when turn end signals are received
    isExpectingMoreChunks: true, // Flag to indicate if we're expecting more chunks
    pendingTurnId: null, // Turn ID waiting to start after current turn completes
    pendingTurnStartTime: null, // When the pending turn was requested
    pendingGenerationQueue: [] // Simple queue for audio chunks from new generations
  });
  
  // Function to detect potential truncation issues
  const checkForTruncationIssues = useCallback((turnId) => {
    const tracking = chunkTrackingRef.current;
    const turnData = tracking.turnChunkData[turnId];
    
    if (turnData && turnData.received !== turnData.played) {
      const missed = turnData.received - turnData.played;
      addLogEntryRef.current(
        "chunk_analysis",
        `⚠️ POTENTIAL TRUNCATION: Turn ${turnId} - ${missed} chunks not played (${turnData.received} received, ${turnData.played} played)`
      );
      
      // Check if this is the first turn (common truncation pattern)
      const turnIds = Object.keys(tracking.turnChunkData);
      const isFirstTurn = turnIds.length <= 1 || turnId === turnIds[0];
      
      if (isFirstTurn && missed > 0) {
        addLogEntryRef.current(
          "chunk_analysis",
          `🔴 FIRST TURN TRUNCATION DETECTED: This matches the reported issue pattern!`
        );
      }
    }
  }, []);

  // Function to check if we should start playback early
  const shouldStartPlaybackEarly = useCallback(() => {
    const tracking = chunkTrackingRef.current;
    const bufferLength = jitterBufferRef.current.length;
    const timeSinceLastChunk = tracking.lastChunkReceivedTime ? 
      Date.now() - tracking.lastChunkReceivedTime : 0;
    
    // Start playback early if:
    // 1. We have some chunks and it's been a while since the last chunk (end of turn)
    // 2. We received a turn end signal and have pending chunks
    // 3. We have chunks and aren't expecting more
    const shouldStart = bufferLength > 0 && (
      timeSinceLastChunk > 500 || // 500ms since last chunk
      !tracking.isExpectingMoreChunks ||
      (tracking.currentTurnId && tracking.turnEndSignals.has(tracking.currentTurnId))
    );

    if (shouldStart && bufferLength < adaptiveJitterBufferSize.current) {
      addLogEntryRef.current(
        "audio_playback", 
        `🚀 EARLY PLAYBACK: Starting with ${bufferLength} chunks (threshold: ${adaptiveJitterBufferSize.current}, time since last: ${timeSinceLastChunk}ms)`
      );
    }

    return shouldStart;
  }, []);

  // Simple function to process pending generation queue
  const processPendingGenerationQueue = useCallback(() => {
    const tracking = chunkTrackingRef.current;
    
    if (tracking.pendingGenerationQueue.length === 0) return;
    if (isPlayingRef.current || jitterBufferRef.current.length > 0) return;
    
    addLogEntryRef.current(
      "audio_generation_transition", 
      `🔄 PROCESSING PENDING GENERATION: Moving ${tracking.pendingGenerationQueue.length} queued chunks to playback queue`
    );
    
    // Move all pending chunks to main jitter buffer
    while (tracking.pendingGenerationQueue.length > 0) {
      const chunk = tracking.pendingGenerationQueue.shift();
      jitterBufferRef.current.push(chunk);
    }
    
    // Start playback
    if (jitterBufferRef.current.length > 0 && !isPlayingRef.current) {
      playAudioFromQueue();
    }
  }, []);

  const playAudioFromQueue = useCallback(async () => {
    addLogEntryRef.current(
      "diag_play_audio_start",
      `[DIAG] playAudioFromQueue called. isPlaying: ${isPlayingRef.current}, queue size: ${jitterBufferRef.current.length}`
    );
    const currentTime = new Date().toTimeString().split(' ')[0];
    
    // Improved jitter buffer logic - check if we should start playback early
    const hasMinimumChunks = jitterBufferRef.current.length >= adaptiveJitterBufferSize.current;
    const shouldStartEarly = shouldStartPlaybackEarly();
    
    addLogEntryRef.current(
      "playback_attempt",
      `[${currentTime}] 🎵 PLAYBACK ATTEMPT: isPlaying=${isPlayingRef.current}, queueLength=${jitterBufferRef.current.length}, hasMinimum=${hasMinimumChunks}, shouldStart=${shouldStartEarly}`
    );
    
    if (isPlayingRef.current || (!hasMinimumChunks && !shouldStartEarly)) {
      addLogEntryRef.current(
        "playback_blocked",
        `[${currentTime}] ⛔ PLAYBACK BLOCKED: Already playing or insufficient chunks`
      );
      return;
    }
    
    addLogEntryRef.current(
      "playback_starting",
      `[${currentTime}] 🚀 PLAYBACK STARTING: Setting isPlayingRef=true`
    );
    isPlayingRef.current = true;
    const audioChunk = jitterBufferRef.current.shift();
    if (!audioChunk) {
      isPlayingRef.current = false;
      return;
    }
    try {
      // Ensure playback context is ready
      if (!playbackAudioContextRef.current) {
        playbackAudioContextRef.current = new (window.AudioContext ||
          window.webkitAudioContext)({ sampleRate: OUTPUT_SAMPLE_RATE });
      }

      if (playbackAudioContextRef.current.state === "suspended") {
        await playbackAudioContextRef.current.resume();
        addLogEntryRef.current("audio_playback", "Playback AudioContext resumed");
      }

      // Create WAV file with error handling
      const wavData = createWavFile(audioChunk);
      if (!wavData) {
        addLogEntryRef.current("error", "Failed to create WAV file from audio chunk");
        isPlayingRef.current = false;
        playAudioFromQueue(); // Try next chunk
        return;
      }

      // Decode audio data with error handling
      let audioBuffer;
      try {
        audioBuffer = await playbackAudioContextRef.current.decodeAudioData(
          wavData
        );
      } catch (decodeError) {
        addLogEntryRef.current("error", `Audio decode failed: ${decodeError.message}`);
        isPlayingRef.current = false;
        playAudioFromQueue(); // Try next chunk
        return;
      }

      const source = playbackAudioContextRef.current.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(playbackAudioContextRef.current.destination);

      const currentTime = playbackAudioContextRef.current.currentTime;
      const startTime =
        nextStartTimeRef.current > currentTime
          ? nextStartTimeRef.current
          : currentTime;
      source.start(startTime);
      nextStartTimeRef.current = startTime + audioBuffer.duration;
      
      // Enhanced chunk tracking with proper turn management
      const tracking = chunkTrackingRef.current;
      tracking.totalChunksPlayed++;
      tracking.chunksPlayedCurrentTurn++;
      tracking.lastChunkPlayedTime = Date.now();
      
      // Update turn data
      if (tracking.currentTurnId && tracking.turnChunkData[tracking.currentTurnId]) {
        tracking.turnChunkData[tracking.currentTurnId].played++;
        
        addLogEntryRef.current(
          "chunk_playback",
          `📊 Chunk played for turn ${tracking.currentTurnId}: ${tracking.turnChunkData[tracking.currentTurnId].played}/${tracking.turnChunkData[tracking.currentTurnId].received} (queue: ${jitterBufferRef.current.length})`
        );
        
        // Check if turn is complete
        const turnData = tracking.turnChunkData[tracking.currentTurnId];
        const isTurnComplete = turnData.endSignalReceived && 
                             turnData.played >= turnData.received && 
                             jitterBufferRef.current.length === 0;
        
        if (isTurnComplete) {
          addLogEntryRef.current(
            "turn_complete",
            `✅ TURN COMPLETE: Turn ${tracking.currentTurnId} - all ${turnData.played} chunks played successfully`
          );
          
          // Check for any missed chunks before completing
          checkForTruncationIssues(tracking.currentTurnId);
        }
      }

      source.onended = () => {
        addLogEntryRef.current(
          "diag_chunk_ended",
          `[DIAG] Chunk playback ended. Queue size: ${jitterBufferRef.current.length}, isExpectingMoreChunks: ${chunkTrackingRef.current.isExpectingMoreChunks}`
        );
        const currentTime = new Date().toTimeString().split(' ')[0];
        const tracking = chunkTrackingRef.current;
        
        addLogEntryRef.current(
          "playback_ended",
          `[${currentTime}] 🏁 PLAYBACK ENDED: Setting isPlayingRef=false, queueLength=${jitterBufferRef.current.length}, pendingQueue=${tracking.pendingGenerationQueue.length}`
        );
        
        isPlayingRef.current = false;
        
        // Continue playing remaining chunks in queue
        if (jitterBufferRef.current.length > 0) {
          addLogEntryRef.current(
            "playback_continue",
            `[${currentTime}] ⏩ CONTINUING PLAYBACK: ${jitterBufferRef.current.length} chunks remaining`
          );
          playAudioFromQueue();
        } else {
          // No more chunks in queue - check if we should wait or if turn is complete
          const tracking = chunkTrackingRef.current;
          
          // Check if we have a pending turn transition that we can now complete
          if (tracking.pendingTurnId && tracking.currentTurnId) {
            addLogEntryRef.current(
              "turn_transition",
              `🔄 COMPLETING DEFERRED TURN TRANSITION: Previous turn ${tracking.currentTurnId} finished playing, now starting turn ${tracking.pendingTurnId}`
            );
            
            // Complete the previous turn
            if (tracking.turnChunkData[tracking.currentTurnId]) {
              tracking.turnChunkData[tracking.currentTurnId].endSignalReceived = true;
              tracking.turnEndSignals.add(tracking.currentTurnId);
              checkForTruncationIssues(tracking.currentTurnId);
            }
            
            // Start the new turn
            const newTurnId = tracking.pendingTurnId;
            tracking.currentTurnId = newTurnId;
            tracking.chunksReceivedCurrentTurn = 0;
            tracking.chunksPlayedCurrentTurn = 0;
            tracking.pendingTurnId = null;
            tracking.pendingTurnStartTime = null;
            tracking.isExpectingMoreChunks = true;
            
            // Initialize turn data if not already present
            if (!tracking.turnChunkData[newTurnId]) {
              tracking.turnChunkData[newTurnId] = {
                received: 0,
                played: 0,
                startTime: Date.now(),
                endSignalReceived: false
              };
            }
            
            addLogEntryRef.current(
              "turn_transition",
              `✅ TURN TRANSITION COMPLETED: Now active on turn ${newTurnId}`
            );
          } else if (tracking.isExpectingMoreChunks) {
            addLogEntryRef.current(
              "audio_queue_empty",
              `🔄 Audio queue empty but expecting more chunks. Waiting for next chunk...`
            );
            
            // Set a timeout to check again in case we miss chunks
            setTimeout(() => {
              if (jitterBufferRef.current.length > 0) {
                addLogEntryRef.current("audio_queue_resumed", "📥 New chunks arrived, resuming playback");
                playAudioFromQueue();
              }
            }, 100);
          } else {
            addLogEntryRef.current(
              "audio_turn_end",
              `🏁 Audio playback complete - no more chunks expected`
            );
            
            // Check if we have pending generation chunks to process
            addLogEntryRef.current(
              "pending_queue_check",
              `[${currentTime}] 🔍 CHECKING PENDING QUEUE: ${tracking.pendingGenerationQueue.length} chunks waiting`
            );
            processPendingGenerationQueue();
          }
        }
      };
      currentAudioSourceRef.current = { source };
    } catch (error) {
      addLogEntryRef.current("error", `Audio playback error: ${error.message}`);
      isPlayingRef.current = false;
      setTimeout(playAudioFromQueue, 100);
    }
  }, [adaptiveJitterBufferSize, currentAudioSourceRef, isPlayingRef, jitterBufferRef, nextStartTimeRef, shouldStartPlaybackEarly, checkForTruncationIssues, processPendingGenerationQueue]);


  const processPendingAudioChunks = useCallback(async () => {
    while (
      pendingAudioChunks.current.length > 0 &&
      !checkWebSocketBackpressure()
    ) {
      const chunkObj = pendingAudioChunks.current.shift();
      const audioData = chunkObj.data || chunkObj;
      const sent = await sendAudioChunkWithBackpressure(audioData);
      if (!sent) {
        pendingAudioChunks.current.unshift(chunkObj);
        break;
      }
    }
  }, [sendAudioChunkWithBackpressure, checkWebSocketBackpressure, pendingAudioChunks]);

  // Function to reset audio tracking state (called during barge-in or session reset)
  const resetAudioTrackingState = useCallback(() => {
    const tracking = chunkTrackingRef.current;
    
    addLogEntryRef.current(
      "audio_reset",
      `🔄 RESET: Clearing audio tracking state (current turn: ${tracking.currentTurnId}, chunks in queue: ${jitterBufferRef.current.length})`
    );
    
    // Check for truncation before reset
    if (tracking.currentTurnId) {
      checkForTruncationIssues(tracking.currentTurnId);
    }
    
    // Reset tracking state
    tracking.isExpectingMoreChunks = false;
    tracking.chunksReceivedCurrentTurn = 0;
    tracking.chunksPlayedCurrentTurn = 0;
    tracking.lastChunkReceivedTime = null;
    tracking.lastChunkPlayedTime = null;
    
    // Clear any pending turn transitions
    if (tracking.pendingTurnId) {
      addLogEntryRef.current("audio_reset", `🔄 Clearing pending turn transition: ${tracking.pendingTurnId}`);
      tracking.pendingTurnId = null;
      tracking.pendingTurnStartTime = null;
    }
    
    // Don't reset currentTurnId or turnChunkData as they're useful for analysis
    
    addLogEntryRef.current("audio_reset", "✅ Audio tracking state reset completed");
  }, [checkForTruncationIssues]);

  useEffect(() => {
    const interval = setInterval(() => {
      if (pendingAudioChunks.current.length > 0) processPendingAudioChunks();
    }, 100);
    return () => clearInterval(interval);
  }, [processPendingAudioChunks]);

  useEffect(() => {
    if (isWebSocketReady && isAudioContextReady) {
      addLogEntryRef.current("debug", "WebSocket and AudioContext are ready, sending CLIENT_AUDIO_READY");
      sendAudioReadySignal(
        playbackAudioContextRef.current,
        socketRef.current,
        addLogEntryRef.current,
        connectionSignalTracker,
        "useEffect-readiness"
      );
    }
  }, [isWebSocketReady, isAudioContextReady]);

  const connectWebSocket = useCallback(
    (lang) => {
      addLogEntryRef.current("debug", "connectWebSocket called");
      if (
        socketRef.current &&
        (socketRef.current.readyState === WebSocket.OPEN ||
          socketRef.current.readyState === WebSocket.CONNECTING)
      ) {
        if (socketRef.current.url.includes(`lang=${lang}`)) {
          addLogEntryRef.current(
            "ws",
            `WebSocket already open or connecting with ${lang}.`
          );
          if (isSessionActive && !isRecording) handleStartListening(false);
          return;
        }
        addLogEntryRef.current(
          "ws",
          `Closing existing WebSocket (url: ${socketRef.current.url}, state: ${socketRef.current.readyState}) before new connection for lang ${lang}.`
        );
        socketRef.current.close(
          1000,
          "New connection with different language initiated by connectWebSocket"
        );
      }
      addLogEntryRef.current(
        "ws",
        `Attempting to connect to WebSocket with language: ${lang}...`
      );
      setWebSocketStatus("Connecting...");

      // Reset server ready state for new connection
      setIsServerReady(false);
      isServerReadyRef.current = false;
      preflightBufferRef.current = [];

      socketRef.current = new WebSocket(
        `ws://${BACKEND_HOST}/listen?lang=${lang}`
      );
      if (!playbackAudioContextRef.current)
        playbackAudioContextRef.current = new (window.AudioContext ||
          window.webkitAudioContext)({ sampleRate: OUTPUT_SAMPLE_RATE });
      socketRef.current.binaryType = "arraybuffer";
      socketRef.current.onopen = () => {
        debugLog("🌐 WebSocket onopen event fired!");
        addLogEntryRef.current("debug", "WebSocket onopen event fired");
        if (networkResilienceManagerRef.current) {
          networkResilienceManagerRef.current.setWebSocket(socketRef.current);
          addLogEntryRef.current(
            "ws",
            "WebSocket assigned to network resilience manager after opening."
          );
        }
        setWebSocketStatus("Open");
        setIsWebSocketConnected(true);
        setIsWebSocketReady(true);
        addLogEntryRef.current("ws", `WebSocket Connected (Lang: ${lang}).`);
        if (networkResilienceManagerRef.current?.audioCircuitBreaker) {
          networkResilienceManagerRef.current.resetCircuitBreaker();
          addLogEntryRef.current(
            "ws",
            "Circuit breaker reset on successful WebSocket connection"
          );
        }
        const connectionId = `ws-${Date.now()}-${Math.random()
          .toString(36)
          .substring(2, 9)}`;
        socketRef.current._connectionId = connectionId;
        if (connectionId && connectionSignalTracker.current.has(connectionId)) {
          connectionSignalTracker.current.delete(connectionId);
          addLogEntryRef.current(
            "audio",
            `Cleared signal tracking for recovered connection ${connectionId}`
          );
        }
        debugLog(`🔍 Checking session state: isSessionActive=${isSessionActive}`);
        debugLog(`🔍 Checking session state REF: isSessionActiveRef.current=${isSessionActiveRef?.current}`);
        
        // Use the ref instead of state to avoid race condition
        const sessionIsActive = isSessionActiveRef?.current || isSessionActive;
        debugLog(`🔍 Final decision: sessionIsActive=${sessionIsActive}`);
        
        if (sessionIsActive) {
          debugLog("🎤 Session is active, but microphone activation is now deferred until server is ready.");
          addLogEntryRef.current(
            "session_flow",
            "WebSocket is open. Microphone will start after 'server_ready' signal."
          );
        } else {
          debugLog("❌ Session NOT active - microphone not started!");
          addLogEntryRef.current(
            "ws_warn",
            "WebSocket opened, but session is NOT marked active. Mic not started."
          );
        }
      };
      socketRef.current.onclose = () => {
        addLogEntryRef.current("debug", "WebSocket onclose event fired");
        setIsWebSocketReady(false);
        setIsWebSocketConnected(false);
        setWebSocketStatus("Closed");
        // Reset server ready state on close
        setIsServerReady(false);
        isServerReadyRef.current = false;
        preflightBufferRef.current = [];
      };
      socketRef.current.onerror = () => {
        addLogEntryRef.current("error", "WebSocket onerror event fired");
        setIsWebSocketReady(false);
        setIsWebSocketConnected(false);
        setWebSocketStatus("Error");
      };
      socketRef.current.onmessage = (event) => {
        if (typeof event.data === "string") {
          try {
            const receivedData = JSON.parse(event.data);
            if (receivedData.type === 'control' && receivedData.signal === 'server_ready') {
                addLogEntryRef.current('ws', '🚦 Server is ready to receive audio.');
                setIsServerReady(true);
                isServerReadyRef.current = true;
    
                // Flush pre-flight buffer
                if (preflightBufferRef.current.length > 0) {
                    addLogEntryRef.current('audio_flow', `Flushing ${preflightBufferRef.current.length} audio chunks from pre-flight buffer.`);
                    const bufferedChunks = [...preflightBufferRef.current];
                    preflightBufferRef.current = [];
                    bufferedChunks.forEach(chunk => {
                        sendAudioChunkWithBackpressure(chunk);
                    });
                }
            } else if (receivedData.type && receivedData.type.endsWith("_update")) {
              addLogEntryRef.current(
                receivedData.type,
                `${receivedData.sender}: ${receivedData.text} (Final: ${receivedData.is_final})`
              );
              
              // Enhanced turn tracking with better audio management
              const tracking = chunkTrackingRef.current;
              
              // Detect new turns and turn completion
              if (receivedData.id && receivedData.id !== tracking.currentTurnId) {
                // New turn started - but don't immediately close previous turn
                if (tracking.currentTurnId) {
                  // For async tool calls, we need to allow previous conversation to continue
                  // Only mark as ended if there are no pending chunks to play
                  const pendingChunksForPreviousTurn = jitterBufferRef.current.length;
                  
                  if (tracking.turnChunkData[tracking.currentTurnId]) {
                    const prevTurnData = tracking.turnChunkData[tracking.currentTurnId];
                    
                    if (pendingChunksForPreviousTurn === 0 && !isPlayingRef.current) {
                      // No pending audio, safe to close previous turn
                      prevTurnData.endSignalReceived = true;
                      tracking.turnEndSignals.add(tracking.currentTurnId);
                      checkForTruncationIssues(tracking.currentTurnId);
                      
                      addLogEntryRef.current(
                        "turn_transition",
                        `✅ Clean turn transition: Previous turn ${tracking.currentTurnId} completed, starting new turn ${receivedData.id}`
                      );
                    } else {
                      // Audio still playing from previous turn - defer the transition
                      addLogEntryRef.current(
                        "turn_transition",
                        `🔄 DEFERRED TURN TRANSITION: Previous turn ${tracking.currentTurnId} still has ${pendingChunksForPreviousTurn} chunks queued + ${isPlayingRef.current ? 'audio playing' : 'no active playback'}. New turn ${receivedData.id} will start after completion.`
                      );
                      
                      // Mark that we have a pending turn transition
                      tracking.pendingTurnId = receivedData.id;
                      tracking.pendingTurnStartTime = Date.now();
                      
                      // Don't change currentTurnId yet - let current turn finish
                      // Note: Continue processing instead of returning to handle subsequent updates
                    }
                  }
                }
                
                // Initialize new turn (only if we're not deferring)
                const previousTurnId = tracking.currentTurnId;
                tracking.currentTurnId = receivedData.id;
                tracking.chunksReceivedCurrentTurn = 0;
                tracking.chunksPlayedCurrentTurn = 0;
                
                if (!tracking.turnChunkData[receivedData.id]) {
                  tracking.turnChunkData[receivedData.id] = {
                    received: 0,
                    played: 0,
                    startTime: Date.now(),
                    endSignalReceived: false
                  };
                }
                
                // Simplified turn logging
              }
              
              // Handle turn completion
              if (receivedData.is_final) {
                tracking.isExpectingMoreChunks = false;
                if (tracking.turnChunkData[receivedData.id]) {
                  tracking.turnChunkData[receivedData.id].endSignalReceived = true;
                  tracking.turnEndSignals.add(receivedData.id);
                }
                
                // Turn completed - trigger playback
                
                // Trigger early playback if we have pending chunks
                if (jitterBufferRef.current.length > 0 && !isPlayingRef.current) {
                  addLogEntryRef.current("turn_final_playback", "▶️ Starting final chunk playback");
                  playAudioFromQueue();
                }
              } else {
                tracking.isExpectingMoreChunks = true;
              }
              
              setTranscriptionMessages((prevMessages) => {
                const existingMessageIndex = prevMessages.findIndex(
                  (msg) => msg.id === receivedData.id
                );
                if (existingMessageIndex !== -1) {
                  return prevMessages.map((msg) =>
                    msg.id === receivedData.id
                      ? {
                          ...msg,
                          text: receivedData.text,
                          is_final: receivedData.is_final,
                        }
                      : msg
                  );
                } else {
                  return [
                    ...prevMessages,
                    {
                      id: receivedData.id,
                      text: receivedData.text,
                      sender: receivedData.sender,
                      is_final: receivedData.is_final,
                    },
                  ];
                }
              });
            } else if (receivedData.type === "error") {
              addLogEntryRef.current(
                "error",
                `Server Error via WS: ${receivedData.message}`
              );
            } else if (receivedData.type === "audio_metadata") {
              const metadata = receivedData;
              addLogEntryRef.current(
                "audio_receive",
                `Audio metadata: ${metadata.size_bytes} bytes, ${metadata.expected_duration_ms}ms duration, seq=${metadata.sequence}`
              );
              pendingMetadataRef.current.set(metadata.sequence, metadata);
              if (pendingMetadataRef.current.size > 100) {
                const entries = Array.from(
                  pendingMetadataRef.current.entries()
                );
                entries.sort((a, b) => a[0] - b[0]);
                const toDelete = entries.slice(0, entries.length - 100);
                toDelete.forEach(([seq]) =>
                  pendingMetadataRef.current.delete(seq)
                );
              }
            } else if (receivedData.type === "buffer_pressure") {
              addLogEntryRef.current(
                "audio_flow_control",
                `Buffer pressure ${receivedData.level}: ${receivedData.buffer_size}/${receivedData.max_size} chunks, action: ${receivedData.recommended_action}`
              );
              if (receivedData.level === "high")
                addLogEntryRef.current(
                  "audio_flow_control",
                  `Buffer pressure detected - backend will handle optimization`
                );
            } else if (receivedData.type === "gemini_playback_state") {
              // Handle Gemini playback state for VAD correlation
              const { playing, sequence, correlation_id, vad_should_activate } = receivedData;
              
              addLogEntryRef.current(
                "gemini_playback_correlation",
                `Gemini playback ${playing ? 'STARTED' : 'STOPPED'}: seq=${sequence}, vad_should_activate=${vad_should_activate} [ID: ${correlation_id}]`
              );
              
              // Update global playing state for VAD coordination
              if (playing && isPlayingRef) {
                // Note: We don't directly set isPlayingRef here as that's managed by audio playback
                // This is for correlation logging only
                addLogEntryRef.current(
                  "vad_state_correlation",
                  `Backend signaled Gemini response start - frontend VAD should ${vad_should_activate ? 'REMAIN ACTIVE for barge-in' : 'defer to Gemini VAD'} [ID: ${correlation_id}]`
                );
              }
            } else if (receivedData.type === "function_call_response") {
              addLogEntryRef.current(
                "toolcall",
                `<div><strong>Function:</strong> ${receivedData.function_name}</div>
                 <div><strong>Args:</strong> <pre>${JSON.stringify(receivedData.function_args, null, 2)}</pre></div>
                 <div><strong>Response:</strong> <pre>${JSON.stringify(receivedData.response, null, 2)}</pre></div>`
              );
            } else if (receivedData.type === "interrupt_playback") {
              addLogEntryRef.current("diag_interrupt_received", "[DIAG] interrupt_playback message received from backend.");
              // Handle interruption signal from backend
              addLogEntryRef.current(
                "interrupt",
                "🛑 Playback interrupted by user input - clearing all audio buffers"
              );
              
              // Stop current audio playback immediately
              if (stopSystemAudioPlayback) {
                stopSystemAudioPlayback();
              }
              
              // Clear jitter buffer to prevent stale audio from playing
              const bufferedChunks = jitterBufferRef.current.length;
              jitterBufferRef.current = [];
              
              // Clear pending audio chunks from transmission queue
              const pendingChunks = pendingAudioChunks.current.length;
              pendingAudioChunks.current = [];
              
              // Clear pending metadata
              pendingMetadataRef.current.clear();
              
              // Reset turn tracking for clean state
              const tracking = chunkTrackingRef.current;
              if (tracking.currentTurnId) {
                addLogEntryRef.current(
                  "interrupt",
                  `🛑 Turn ${tracking.currentTurnId} interrupted - cleared ${bufferedChunks} buffered + ${pendingChunks} pending chunks`
                );
                
                // Mark current turn as interrupted
                if (tracking.turnChunkData[tracking.currentTurnId]) {
                  tracking.turnChunkData[tracking.currentTurnId].interrupted = true;
                }
              }
              
              // Reset playback state for clean barge-in
              isPlayingRef.current = false;
              
              addLogEntryRef.current(
                "interrupt",
                "✅ Audio pipeline cleared - ready for new user input"
              );
            } else if (receivedData.type === "audio_truncation") {
              addLogEntryRef.current(
                "error",
                `Audio truncated: ${receivedData.chunks_removed} chunks removed due to ${receivedData.reason}`
              );
            } else {
              addLogEntryRef.current(
                "ws_json_unhandled",
                `Unhandled JSON: ${event.data.substring(0, 150)}...`
              );
            }
          } catch (e) {
            addLogEntryRef.current(
              "error",
              `Failed to parse JSON from WS: ${
                e.message
              }. Raw: ${event.data.substring(0, 150)}...`
            );
          }
        } else if (event.data instanceof ArrayBuffer) {
          addLogEntryRef.current(
            "diag_audio_chunk_received",
            `[DIAG] Audio chunk received. Queue size: ${jitterBufferRef.current.length}, Pending queue size: ${chunkTrackingRef.current.pendingGenerationQueue.length}`
          );
          // Enhanced audio chunk tracking
          const tracking = chunkTrackingRef.current;
          tracking.totalChunksReceived++;
          tracking.lastChunkReceivedTime = Date.now();
          
          // DETAILED STATE LOGGING
          const currentTime = new Date().toTimeString().split(' ')[0];
          addLogEntryRef.current(
            "audio_chunk_debug",
            `[${currentTime}] 🔍 CHUNK RECEIVED #${tracking.totalChunksReceived}: isPlaying=${isPlayingRef.current}, queueLength=${jitterBufferRef.current.length}, pendingQueue=${tracking.pendingGenerationQueue.length}`
          );
          
          // Handle audio chunks - could be for current turn or pending turn
          let targetTurnId = tracking.currentTurnId;
          
          // If we have a pending turn and no current audio playing, chunks might be for the pending turn
          if (tracking.pendingTurnId && jitterBufferRef.current.length === 0 && !isPlayingRef.current) {
            addLogEntryRef.current(
              "audio_chunk_routing",
              `📦 Audio chunk received during pending turn transition - routing to pending turn ${tracking.pendingTurnId}`
            );
            targetTurnId = tracking.pendingTurnId;
          } else {
            // Chunks for current turn
            tracking.chunksReceivedCurrentTurn++;
          }
          
          // Update turn data for the appropriate turn
          if (targetTurnId && tracking.turnChunkData[targetTurnId]) {
            tracking.turnChunkData[targetTurnId].received++;
            
            addLogEntryRef.current(
              "audio_chunk_received",
              `📦 Audio chunk received for turn ${targetTurnId}: ${tracking.turnChunkData[targetTurnId].received} total (queue: ${jitterBufferRef.current.length} chunks)`
            );
          } else if (targetTurnId) {
            // Initialize turn data if it doesn't exist
            tracking.turnChunkData[targetTurnId] = {
              received: 1,
              played: 0,
              startTime: Date.now(),
              endSignalReceived: false
            };
            
            addLogEntryRef.current(
              "audio_chunk_received",
              `📦 First audio chunk for new turn ${targetTurnId} (queue: ${jitterBufferRef.current.length} chunks)`
            );
          }
          
          // IMPROVED GENERATION SEPARATION LOGIC WITH TURN CONTEXT
          const currentlyPlaying = isPlayingRef.current;
          const hasQueuedAudio = jitterBufferRef.current.length > 0;
          const hasActiveTurn = tracking.currentTurnId && tracking.isExpectingMoreChunks;
          const hasPendingTurn = tracking.pendingTurnId;
          
          addLogEntryRef.current(
            "audio_generation_check",
            `[${currentTime}] 🎯 GENERATION CHECK: currentlyPlaying=${currentlyPlaying}, hasQueuedAudio=${hasQueuedAudio}, hasActiveTurn=${hasActiveTurn}, hasPendingTurn=${hasPendingTurn}, currentTurn=${tracking.currentTurnId}`
          );
          
          // Only treat as new generation if:
          // 1. Audio is playing AND queue is empty AND
          // 2. We don't have an active turn expecting more chunks AND  
          // 3. We don't have a pending turn transition
          // This prevents tool responses from being misclassified as new generations
          const shouldQueueAsNewGeneration = currentlyPlaying && 
                                           !hasQueuedAudio && 
                                           !hasActiveTurn && 
                                           !hasPendingTurn;
          
          addLogEntryRef.current(
            "diag_queueing_decision",
            `[DIAG] shouldQueueAsNewGeneration: ${shouldQueueAsNewGeneration}. State: { currentlyPlaying: ${currentlyPlaying}, hasQueuedAudio: ${hasQueuedAudio}, hasActiveTurn: ${hasActiveTurn}, hasPendingTurn: ${hasPendingTurn} }`
          );
          
          if (shouldQueueAsNewGeneration) {
            tracking.pendingGenerationQueue.push(event.data);
            addLogEntryRef.current(
              "audio_generation_detected",
              `[${currentTime}] 🚧 NEW GENERATION DETECTED: Audio playing with empty queue and no active turn - queuing chunk for later (queue size: ${tracking.pendingGenerationQueue.length})`
            );
            return;
          } else if (currentlyPlaying && !hasQueuedAudio && (hasActiveTurn || hasPendingTurn)) {
            // This is likely a tool response or continuation of current conversation
            addLogEntryRef.current(
              "audio_continuation_detected",
              `[${currentTime}] 🔄 TURN CONTINUATION: Audio playing but expecting more chunks for turn ${targetTurnId} - adding to main buffer`
            );
          }
          
          // Normal processing - add to main jitter buffer
          jitterBufferRef.current.push(event.data);
          addLogEntryRef.current(
            "audio_normal_processing",
            `[${currentTime}] ✅ NORMAL PROCESSING: Added chunk to main buffer (new queue size: ${jitterBufferRef.current.length})`
          );
          
          // Try to start playback if not already playing
          if (!isPlayingRef.current) {
            addLogEntryRef.current(
              "audio_playback_trigger",
              `[${currentTime}] 🎬 TRIGGERING PLAYBACK: Starting playAudioFromQueue with ${jitterBufferRef.current.length} chunks`
            );
            playAudioFromQueue();
          } else {
            addLogEntryRef.current(
              "audio_playback_skip",
              `[${currentTime}] ⏭️ SKIPPING PLAYBACK: Already playing, chunk added to queue (size: ${jitterBufferRef.current.length})`
            );
          }
        }
      };
    },
    [
      handleStartListening,
      playAudioFromQueue,
      networkResilienceManagerRef,
      isSessionActive,
      isRecording,
      language,
      checkForTruncationIssues,
      sendAudioChunkWithBackpressure, // Added dependency
    ]
  );

  return {
    isWebSocketConnected,
    webSocketStatus,
    transcriptionMessages,
    socketRef,
    connectWebSocket,
    setTranscriptionMessages,
    isWebSocketReady,
    isServerReady, // Expose new state
    resetAudioTrackingState,
  };
};
