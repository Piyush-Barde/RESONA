import React, { useState, useRef } from 'react';
import { Mic, Square, Keyboard, Send } from 'lucide-react';
import './App.css'; 

export default function App() {
  const [inputMode, setInputMode] = useState('voice'); // Default mode is voice-first
  const [isRecording, setIsRecording] = useState(false);
  const [inputText, setInputText] = useState('');
  const [isProcessingText, setIsProcessingText] = useState(false);
  
  // Clean initialization of your chat log
  const [messages, setMessages] = useState([
    { sender: 'resona', text: "Hey! Share what's going on..." }
  ]);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // ------------------------------------------------------------------------------
  // STREAM-COMPATIBLE TEXT ROUTE API HANDLING
  // ------------------------------------------------------------------------------
  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isProcessingText) return;

    const userMessage = { sender: 'user', text: inputText };
    // Optimistically insert user bubble AND an empty placeholder bubble for Resona's oncoming response stream
    setMessages(prev => [...prev, userMessage, { sender: 'resona', text: '' }]);
    
    const textToSend = inputText;
    setInputText('');
    setIsProcessingText(true);

    console.log("🚀 Frontend is initiating streaming fetch request with payload:", textToSend);

    try {
      const response = await fetch("http://localhost:8000/api/chat/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: textToSend }),
      });
      
      if (!response.ok) {
        throw new Error(`Server responded with status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        // Decode incoming binary packet into plain text string
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        
        // Retain the last slice in case it was chopped mid-transit
        buffer = lines.pop(); 

        for (const line of lines) {
          if (line.trim()) {
            try {
              const parsed = JSON.parse(line);
              if (parsed.reply) {
                // Find and append token directly to the end of the last array element
                setMessages(prev => {
                  const updated = [...prev];
                  const lastIndex = updated.length - 1;
                  if (updated[lastIndex] && updated[lastIndex].sender === 'resona') {
                    updated[lastIndex] = {
                      ...updated[lastIndex],
                      text: updated[lastIndex].text + parsed.reply
                    };
                  }
                  return updated;
                });
              }
            } catch (err) {
              // Gracefully bypass minor partial-chunk serialization errors
              console.debug("Skimming stream metadata lines...");
            }
          }
        }
      }
    } catch (error) {
      console.error("❌ Failed to parse or connect to the text backend API stream:", error);
      // Replace the loading bubble with a visual warning if everything crashes out
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex] && updated[lastIndex].text === '') {
          updated[lastIndex].text = "Ugh, my memory registers just glitched out. Say that to me again?";
        }
        return updated;
      });
    } finally {
      setIsProcessingText(false);
    }
  };

  // ------------------------------------------------------------------------------
  // VOICE ROUTE API HANDLING (Handles audio hardware recording)
  // ------------------------------------------------------------------------------
  const startRecording = async () => {
    audioChunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      
      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        await sendAudioToBackend(audioBlob);
        stream.getTracks().forEach(track => track.stop()); // Shuts off system mic hardware cleanly
      };

      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Microphone hardware access blocked:", err);
      alert("Please open this page in Chrome/Brave and allow microphone permission!");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const sendAudioToBackend = async (audioBlob) => {
    setIsProcessingText(true);
    const formData = new FormData();
    formData.append("file", audioBlob, "user_voice_input.wav");

    try {
      const response = await fetch("http://localhost:8000/api/chat/audio-transcribe", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      
      if (data.status === "success" && data.text.trim().length > 0) {
        setInputText(data.text);
        setInputMode('text'); // Hot-swaps right into text view so you can review your words
      }
    } catch (error) {
      console.error("Transcription backend endpoint disconnected:", error);
    } finally {
      setIsProcessingText(false);
    }
  };

  return (
    <div className="resona-container">
      {/* GLOBAL RUNTIME HEADER */}
      <header className="resona-header">
        <div className="logo-group">
          <div className="status-dot animate-pulse" />
          <h1 className="logo-text">RESONA</h1>
        </div>
        <span className="core-badge">99.5% Emotional Core</span>
      </header>

      {/* CHAT DISPLAY CONTAINER */}
      <div className="chat-display">
        {messages.map((msg, index) => (
          <div key={index} className={`message-bubble-row ${msg.sender}`}>
            <div className="message-content-text">{msg.text}</div>
          </div>
        ))}
      </div>

      {/* FOOTER CONTROLLER DOCK */}
      <footer className="resona-footer">
        <div className="input-wrapper">
          {inputMode === 'voice' ? (
            /* 🎙️ CHATGPT VOICE PANEL MODULE */
            <div className={`voice-panel ${isRecording ? 'recording-active' : ''}`}>
              <p className="status-message">
                {isRecording ? "Listening to you vent..." : isProcessingText ? "Processing your voice weights..." : "Tap to speak with Resona"}
              </p>
              <div className="voice-controls">
                <button type="button" onClick={() => setInputMode('text')} className="icon-button key-toggle" title="Switch to Typing">
                  <Keyboard size={20} />
                </button>
                <button type="button" onClick={isRecording ? stopRecording : startRecording} className={`mic-action-btn ${isRecording ? 'recording-pulse' : 'idle-mic'}`}>
                  {isRecording ? <Square size={24} fill="currentColor" /> : <Mic size={24} />}
                </button>
                <div className="spacer-node" />
                <div className="voice-wave-container" />
              </div>
            </div>
          ) : (
            /* ⌨️ DISCRETION TEXT PANEL MODULE */
            <form onSubmit={handleSendMessage} className="text-panel">
              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="Share what's going on..."
                className="text-input-field"
                disabled={isProcessingText}
              />
              <button type="button" onClick={() => setInputMode('voice')} className="icon-button mic-toggle" title="Switch to Voice Mode">
                <Mic size={18} />
              </button>
              <button type="submit" disabled={!inputText.trim() || isProcessingText} className={`send-action-btn ${inputText.trim() ? 'active-send' : 'disabled-send'}`}>
                <Send size={16} />
              </button>
            </form>
          )}
        </div>
      </footer>
    </div>
  );
}