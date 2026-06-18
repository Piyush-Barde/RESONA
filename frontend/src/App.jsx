import React, { useState, useEffect, useRef } from 'react';
import { Mic, Square, Keyboard, Send } from 'lucide-react';
import './App.css'; 

export default function App() {
  const [inputMode, setInputMode] = useState('voice'); 
  const [isRecording, setIsRecording] = useState(false);
  const [inputText, setInputText] = useState('');
  const [isProcessingText, setIsProcessingText] = useState(false);
  
  // 🎛️ Voice Menu State Configuration
  const [currentVoice, setCurrentVoice] = useState('EXAVITQu4vr4xnSDxMaL'); // Default to Bella
  
  const voiceOptions = [
    { name: "✨ Bella (Warm)", id: "EXAVITQu4vr4xnSDxMaL" },   // Unrestricted Female
    { name: "🍃 Nicole (Whispery)", id: "cQthpqGcbbtPoEMXj1AB" }, // Unrestricted Female 
    { name: "🌊 Antoni (Smooth Male)", id: "ErXwobaYiN019PkySvjV" } // Unrestricted Male
  ];

  const [messages, setMessages] = useState([
    { sender: 'resona', text: "Hey! Share what's going on..." }
  ]);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ------------------------------------------------------------------------------
  // TEXT SUBMISSION ROUTE (Handles Text Streaming & TTS Playback)
  // ------------------------------------------------------------------------------
  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isProcessingText) return;

    const userMessage = { sender: 'user', text: inputText };
    setMessages(prev => [...prev, userMessage, { sender: 'resona', text: '' }]);
    
    const textToSend = inputText;
    setInputText('');
    setIsProcessingText(true);

    let full_reply = ""; 

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

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); 

        for (const line of lines) {
          if (line.trim()) {
            try {
              const parsed = JSON.parse(line);
              if (parsed.reply) {
                full_reply += parsed.reply; 
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
              console.debug("Skimming stream metadata lines...");
            }
          }
        }
      }

      // --- DYNAMIC AUDIO SYNTHESIS EXECUTION ---
      if (full_reply.trim()) {
        await executeVoiceSynthesis(full_reply);
      }

    } catch (error) {
      console.error("❌ Failed to parse text stream:", error);
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
  // VOICE HARDWARE RECORDING ENGINE
  // ------------------------------------------------------------------------------
  const startRecording = async () => {
    audioChunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      let options = { mimeType: 'audio/webm' };
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        options = { mimeType: 'audio/webm;codecs=opus' };
      }

      console.log(`🎙️ Recording container type locked: ${options.mimeType}`);
      mediaRecorderRef.current = new MediaRecorder(stream, options);
      
      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mediaRecorderRef.current.mimeType });
        await sendAudioToBackend(audioBlob);
        stream.getTracks().forEach(track => track.stop()); 
      };

      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Microphone hardware access blocked:", err);
      alert("Microphone hardware disconnected or authorization denied. Double check site permissions!");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  // ------------------------------------------------------------------------------
  // VOICE PROCESSING & AUTO-SUBMISSION PIPELINE
  // ------------------------------------------------------------------------------
  const sendAudioToBackend = async (audioBlob) => {
    setIsProcessingText(true);
    const formData = new FormData();
    formData.append("file", audioBlob, "user_voice_input.webm");

    try {
      const response = await fetch("http://localhost:8000/api/chat/audio-transcribe", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      
      if (data.status === "success" && data.text.trim().length > 0) {
        console.log(`🗣️ Transcribed text payload: "${data.text}". Triggering live auto-forwarding...`);
        
        const userMessage = { sender: 'user', text: data.text };
        setMessages(prev => [...prev, userMessage, { sender: 'resona', text: '' }]);
        
        let full_reply = "";

        const chatResponse = await fetch("http://localhost:8000/api/chat/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: data.text }),
        });
        
        if (!chatResponse.ok) throw new Error("Text processing system unresolvable");

        const reader = chatResponse.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop(); 

          for (const line of lines) {
            if (line.trim()) {
              try {
                const parsed = JSON.parse(line);
                if (parsed.reply) {
                  full_reply += parsed.reply;
                  setMessages(prev => {
                    const updated = [...prev];
                    const lastIndex = updated.length - 1;
                    if (updated[lastIndex] && updated[lastIndex].sender === 'resona') {
                      updated[lastIndex] = { ...updated[lastIndex], text: updated[lastIndex].text + parsed.reply };
                    }
                    return updated;
                  });
                }
              } catch (err) {}
            }
          }
        }

        if (full_reply.trim()) {
          await executeVoiceSynthesis(full_reply);
        }
      }
    } catch (error) {
      console.error("Transcription execution loop failed:", error);
    } finally {
      setInputText(''); 
      setIsProcessingText(false);
    }
  };

  // Shared Helper Layer to manage Speech execution
  const executeVoiceSynthesis = async (textString) => {
    console.log(`🔊 Dispatching vocal payload via active voice state: ${currentVoice}`);
    try {
      const ttsResponse = await fetch("http://localhost:8000/api/chat/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          message: textString,
          voice_id: currentVoice // 🌟 Dynamically matching payload choice selection state
        }),
      });
      
      if (ttsResponse.ok) {
        const audioBlob = await ttsResponse.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = new Audio(audioUrl);
        await audio.play();
        console.log("🎉 Audio binary active across local sound card!");
      }
    } catch (ttsErr) {
      console.error("❌ Vocalization audio context generation failed:", ttsErr);
    }
  };

  return (
    <div className="resona-container">
      <header className="resona-header">
        <div className="logo-group">
          <div className="status-dot animate-pulse" />
          <h1 className="logo-text">RESONA</h1>
        </div>
        
        {/* 🎛️ NEW: Styled Voice Selector Interface Dropdown Container */}
        <div className="voice-selector-wrapper">
          <select 
            value={currentVoice} 
            onChange={(e) => setCurrentVoice(e.target.value)}
            className="voice-dropdown"
            disabled={isProcessingText || isRecording}
          >
            {voiceOptions.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name}
              </option>
            ))}
          </select>
        </div>

        <span className="core-badge">99.5% Emotional Core</span>
      </header>

      <div className="chat-display">
        {messages.map((msg, index) => (
          <div key={index} className={`message-bubble-row ${msg.sender}`}>
            <div className="message-content-text">{msg.text}</div>
          </div>
        ))}
        <div ref={chatEndRef} />
      </div>

      <footer className="resona-footer">
        <div className="input-wrapper">
          {inputMode === 'voice' ? (
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