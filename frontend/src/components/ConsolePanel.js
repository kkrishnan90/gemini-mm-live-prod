import React, { useEffect, useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPaperPlane, faTrash } from '@fortawesome/free-solid-svg-icons';

export const ConsolePanel = ({ 
  messages, 
  isLoading, 
  textInputValue, 
  setTextInputValue, 
  handleSendTextMessage, 
  isSessionActive,
  onClearLogs 
}) => {
  const logsAreaRef = useRef(null);

  useEffect(() => {
    if (logsAreaRef.current)
      logsAreaRef.current.scrollTop = logsAreaRef.current.scrollHeight;
  }, [messages]);

  return (
    <div className="console-panel">
      <div className="console-header">
        <h2>Console</h2>
        <div className="console-header-controls">
          <button
            onClick={onClearLogs}
            className="clear-logs-button"
            title="Clear all logs"
            style={{
              backgroundColor: '#ff4444',
              color: 'white',
              border: 'none',
              padding: '4px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              marginRight: '8px',
              fontSize: '12px'
            }}>
            <FontAwesomeIcon icon={faTrash} /> Clear
          </button>
          <select
            className="console-dropdown"
            defaultValue="conversations">
            <option value="conversations">Conversations</option>
          </select>
        </div>
      </div>
      <div
        className="logs-area"
        ref={logsAreaRef}>
        {isLoading && <p className="loading-indicator">Loading...</p>}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`log-entry log-entry-${msg.type} ${ 
              msg.type === "toolcall" ? "log-entry-toolcall" : ""
            }`}>
            <span className="log-timestamp">[{msg.timestamp}] </span>
            <span className="log-prefix">{msg.type.toUpperCase()}: </span>
            <span className="log-message" dangerouslySetInnerHTML={{ __html: msg.content }}></span>
          </div>
        ))}
      </div>
      <div className="text-input-area console-text-input-area">
        <input
          type="text"
          className="text-input"
          value={textInputValue}
          onChange={(e) => setTextInputValue(e.target.value)}
          onKeyPress={(e) => e.key === "Enter" && handleSendTextMessage()}
          placeholder="Type something..."
          disabled={!isSessionActive}
        />
        <button
          onClick={handleSendTextMessage}
          className="control-button send-button"
          disabled={!textInputValue.trim() || !isSessionActive}>
          <FontAwesomeIcon icon={faPaperPlane} />
        </button>
      </div>
    </div>
  );
};