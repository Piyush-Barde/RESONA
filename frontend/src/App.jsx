import React, { useState, useEffect, useRef } from 'react';
import { Mic, Square, Keyboard, Send, Trash2, MessageSquare, Plus, Menu } from 'lucide-react';
import './App.css'; 

let globalAudioCtx = null;

export default function App() {
  const [inputMode, setInputMode] = useState('voice'); 
  const [isRecording, setIsRecording] = useState(false);
  const [inputText, setInputText] = useState('');
  const [isProcessingText, setIsProcessingText] = useState(false);
  
  // 🗄️ PERSISTENT LOCAL STORAGE VOICE SYNC LOCK
  const [currentVoice, setCurrentVoice] = useState(() => {
    return localStorage.getItem("resona_voice_id") || "EXAVITQu4vr4xnSDxMaL";
  });
  
  // Sidebar Feed Tracking States
  const [sessionsList, setSessionsList] = useState([]);
  const [activeSession, setActiveSession] = useState('default_session');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const voiceOptions = [
    { name: "✨ Bella (Warm)", id: "EXAVITQu4vr4xnSDxMaL" },   
    { name: "🍃 Nicole (Whispery)", id: "cQthpqGcbbtPoEMXj1AB" }, 
    { name: "🌊 Antoni (Smooth Male)", id: "ErXwobaYiN019PkySvjV" } 
  ];

  const [messages, setMessages] = useState([
    { sender: 'resona', text: "Hey! Share what's going on..." }
  ]);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const chatEndRef = useRef(null);

  // Sync auto-scrolling on bubble addition
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Fetch sidebar list items on initial startup or context mutations
  useEffect(() => {
    loadSessionsList();
  }, [messages, activeSession]);

  const loadSessionsList = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/chat/sessions");
      if (response.ok) {
        const data = await response.json();
        setSessionsList(data);
      }
    } catch (err) {
      console.error("Sidebar background session stream sync failure:", err);
    }
  };

  // Explicit voice change interceptor to lock settings dynamically
  const handleVoiceChange = (e) => {
    const selectedVoiceId = e.target.value;
    setCurrentVoice(selectedVoiceId);
    localStorage.setItem("resona_voice_id", selectedVoiceId);
    console.log(`🔒 Voice state preference locked in localStorage: ${selectedVoiceId}`);
  };

  const selectActiveThread = async (sessionId) => {
    setActiveSession(sessionId);
    try {
      const response = await fetch(`http://localhost:8000/api/chat/history/${sessionId}`);
      if (response.ok) {
        const data = await response.json();
        if (data.length === 0) {
          setMessages([{ sender: 'resona', text: "Hey! This is a blank conversation space. Share what's up..." }]);
        } else {
          setMessages(data);
        }
      }
    } catch (err) {
      console.error("Failed to load thread timeline:", err);
    }
  };

  const createNewChatSession = () => {
    const randomHexId = "chat_" + Math.random().toString(36).substring(2, 9);
    setActiveSession(randomHexId);
    setMessages([{ sender: 'resona', text: "Brand new canvas! I'm listening, tell me everything..." }]);
  };

  const preWarmAudioHardware = () => {
    if (!globalAudioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      globalAudioCtx = new AudioContext();
    }
    if (globalAudioCtx.state === "suspended") globalAudioCtx.resume();
  };

  const handleClearHistory = async () => {
    if (!window.confirm("Are you sure you want to completely clear this specific chat session?")) return;

    try {
      const response = await fetch(`http://localhost:8000/api/chat/clear/${activeSession}`, {
        method: "DELETE"
      });
      if (response.ok) {
        setMessages([{ sender: 'resona', text: "Memory wiped clean. Let's start fresh! What's on your mind?" }]);
        loadSessionsList();
      }
    } catch (err) {
      console.error("Deletion sync failure:", err);
    }
  };

  // ------------------------------------------------------------------------------
  // TEXT DATA PIPELINE LOOP
  // ------------------------------------------------------------------------------
  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isProcessingText) return;

    preWarmAudioHardware();
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
        body: JSON.stringify({ message: textToSend, session_id: activeSession }),
      });
      
      if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);

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
              
              if (parsed.polished_input) {
                setMessages(prev => {
                  const updated = [...prev];
                  if (updated[updated.length - 2]) updated[updated.length - 2].text = parsed.polished_input;
                  return updated;
                });
              }

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

      if (full_reply.trim()) await executeVoiceSynthesis(full_reply);

    } catch (error) {
      console.error("❌ Failed text pipeline iteration:", error);
    } finally {
      setIsProcessingText(false);
    }
  };

  // ------------------------------------------------------------------------------
  // MIC AUDIO LOGIC LAYER
  // ------------------------------------------------------------------------------
  const startRecording = async () => {
    preWarmAudioHardware();
    audioChunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      let options = { mimeType: 'audio/webm' };
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        options = { mimeType: 'audio/webm;codecs=opus' };
      }

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
      console.error("Mic initialization block trace:", err);
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
    formData.append("file", audioBlob, "user_voice_input.webm");

    try {
      const response = await fetch("http://localhost:8000/api/chat/audio-transcribe", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      
      if (data.status === "success" && data.text.trim().length > 0) {
        const userMessage = { sender: 'user', text: data.text };
        setMessages(prev => [...prev, userMessage, { sender: 'resona', text: '' }]);
        
        let full_reply = "";

        const chatResponse = await fetch("http://localhost:8000/api/chat/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: data.text, session_id: activeSession }),
        });
        
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

        if (full_reply.trim()) await executeVoiceSynthesis(full_reply);
      }
    } catch (error) {
      console.error("Transcription execution loop failed:", error);
    } finally {
      setIsProcessingText(false);
    }
  };

  // ------------------------------------------------------------------------------
  // MULTI-BUFFER SPEECH STREAMING BACKBONE
  // ------------------------------------------------------------------------------
  const executeVoiceSynthesis = async (textString) => {
    try {
      preWarmAudioHardware();
      const response = await fetch("http://localhost:8000/api/chat/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: textString, voice_id: currentVoice }),
      });
      
      if (!response.ok) throw new Error("Vocalization stream failed");

      const reader = response.body.getReader();
      let audioQueue = [];
      let isPlayingQueue = false;
      let nextStartTime = globalAudioCtx.currentTime;
      
      const PREBUFFER_THRESHOLD = 2; 
      let totalChunksReceived = 0;

      const playQueue = async () => {
        if (isPlayingQueue || audioQueue.length < (totalChunksReceived === 0 ? PREBUFFER_THRESHOLD : 1)) return;
        isPlayingQueue = true;

        while (audioQueue.length > 0) {
          const rawBuffer = audioQueue.shift();
          try {
            const audioBuffer = await globalAudioCtx.decodeAudioData(rawBuffer);
            const source = globalAudioCtx.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(globalAudioCtx.destination);

            const startTime = Math.max(nextStartTime, globalAudioCtx.currentTime);
            source.start(startTime);
            nextStartTime = startTime + audioBuffer.duration;

            await new Promise(resolve => setTimeout(resolve, audioBuffer.duration * 1000));
          } catch (e) {}
        }
        isPlayingQueue = false;
      };

      let accumulatedChunks = [];
      let accumulatedLength = 0;
      const BATCH_SIZE = 48 * 1024; 

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          if (accumulatedChunks.length > 0) {
            const finalBuffer = new Uint8Array(accumulatedLength);
            let offset = 0;
            for (const c of accumulatedChunks) {
              finalBuffer.set(c, offset);
              offset += c.length;
            }
            audioQueue.push(finalBuffer.buffer);
            totalChunksReceived++;
            await playQueue();
          }
          break;
        }

        accumulatedChunks.push(value);
        accumulatedLength += value.length;

        if (accumulatedLength >= BATCH_SIZE) {
          const mergedBuffer = new Uint8Array(accumulatedLength);
          let offset = 0;
          for (const c of accumulatedChunks) {
            mergedBuffer.set(c, offset);
            offset += c.length;
          }
          audioQueue.push(mergedBuffer.buffer);
          totalChunksReceived++;
          accumulatedChunks = [];
          accumulatedLength = 0;
          playQueue();
        }
      }

    } catch (ttsErr) {
      console.error("Audio engine context boundary track exception:", ttsErr);
    }
  };

  return (
    <div className="app-layout-wrapper" style={{ display: 'flex', width: '100vw', height: '100vh', background: '#0B0F17', overflow: 'hidden' }}>
      
      {/* 🧭 PREMIUM CHATGPT-STYLE CONVERSATION HISTORY SIDEBAR */}
      {sidebarOpen && (
        <aside className="resona-sidebar" style={{ width: '260px', background: '#0D131F', borderRight: '1px solid #1F2937', display: 'flex', flexDirection: 'column', padding: '12px', boxSizing: 'border-box' }}>
          <button 
            onClick={createNewChatSession}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '10px 14px', background: 'transparent', border: '1px dashed #4B5563', borderRadius: '6px', color: '#E5E7EB', cursor: 'pointer', textAlign: 'left', fontWeight: '500', fontSize: '14px', marginBottom: '16px' }}
          >
            <Plus size={16} /> New Chat Space
          </button>

          <div className="sidebar-feed-container" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '11px', color: '#6B7280', fontWeight: '600', textTransform: 'uppercase', tracking: '0.05em', paddingLeft: '4px', marginBottom: '6px' }}>Past Conversations</span>
            {sessionsList.map((session) => (
              <button
                key={session.session_id}
                onClick={() => selectActiveThread(session.session_id)}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%', padding: '10px', background: activeSession === session.session_id ? '#1E293B' : 'transparent', border: 'none', borderRadius: '6px', color: activeSession === session.session_id ? '#38BDF8' : '#9CA3AF', cursor: 'pointer', textAlign: 'left', fontSize: '13.5px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}
              >
                <MessageSquare size={14} style={{ opacity: 0.7, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{session.display_name}</span>
              </button>
            ))}
          </div>
        </aside>
      )}

      {/* 💻 MAIN CONVERSATION SCREEN WRAPPER CONTAINER */}
      <div className="resona-container" style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <header className="resona-header">
          <div className="logo-group" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{ background: 'none', border: 'none', color: '#9CA3AF', cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
              <Menu size={20} />
            </button>
            <div className="status-dot animate-pulse" />
            <h1 className="logo-text">RESONA</h1>
          </div>
          
          <div className="header-controls" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div className="voice-selector-wrapper">
              <select 
                value={currentVoice} 
                onChange={handleVoiceChange} // ⚡ Persistent choice tracker
                className="voice-dropdown"
                disabled={isProcessingText || isRecording}
              >
                {voiceOptions.map((voice) => (
                  <option key={voice.id} value={voice.id}>{voice.name}</option>
                ))}
              </select>
            </div>

            <button onClick={handleClearHistory} className="trash-reset-btn" title="Clear Chat Session History" style={{ background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', padding: '4px' }}>
              <Trash2 size={20} className="hover:text-red-400 transition-colors" />
            </button>
          </div>
          <span className="core-badge">99.5% Emotional Core</span>
        </header>

        <div className="chat-display" style={{ flex: 1, overflowY: 'auto' }}>
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
                {isProcessingText ? (
                  <div className="thinking-orb-container">
                    <div className="thinking-orb" />
                    <p className="status-message" style={{ color: '#9CA3AF' }}>Resona is translating thoughts...</p>
                  </div>
                ) : (
                  <p className="status-message">{isRecording ? "Listening to you vent..." : "Tap to speak with Resona"}</p>
                )}

                <div className="voice-controls">
                  <button type="button" onClick={() => setInputMode('text')} className="icon-button key-toggle" title="Switch to Typing"><Keyboard size={20} /></button>
                  <button type="button" onMouseEnter={preWarmAudioHardware} onFocus={preWarmAudioHardware} onClick={isRecording ? stopRecording : startRecording} className={`mic-action-btn ${isRecording ? 'recording-pulse' : 'idle-mic'}`}>
                    {isRecording ? <Square size={24} fill="currentColor" /> : <Mic size={24} />}
                  </button>
                  <div className="spacer-node" />
                  <div className="voice-wave-container" />
                </div>
              </div>
            ) : (
              <form onSubmit={handleSendMessage} className="text-panel">
                <input type="text" value={inputText} onChange={(e) => setInputText(e.target.value)} placeholder="Share what's going on..." className="text-input-field" disabled={isProcessingText} />
                <button type="button" onClick={() => setInputMode('voice')} className="icon-button mic-toggle" title="Switch to Voice Mode"><Mic size={18} /></button>
                <button type="submit" disabled={!inputText.trim() || isProcessingText} className={`send-action-btn ${inputText.trim() ? 'active-send' : 'disabled-send'}`}><Send size={16} /></button>
              </form>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}