import React, { useState, useEffect, useRef } from 'react';
import { Mic, Square, Keyboard, Send, Trash2, MessageSquare, Plus, Menu } from 'lucide-react';
import './App.css';

let globalAudioCtx = null;

// ── Time-aware context for greeting ───────────────────────────────────────────
const getTimeContext = () => {
  const hour = new Date().getHours();
  if (hour >= 0 && hour < 4)  return { label: 'middle of the night (12am–4am)', vibe: "night owl, restless, can't sleep, world is silent" };
  if (hour < 6)               return { label: 'very early morning (4am–6am)',    vibe: 'early riser, world is still quiet, everyone else is asleep' };
  if (hour < 12)              return { label: 'morning (6am–12pm)',               vibe: 'fresh start, morning energy, day just beginning' };
  if (hour < 17)              return { label: 'afternoon (12pm–5pm)',             vibe: 'midday, day is moving, possibly tired or busy' };
  if (hour < 21)              return { label: 'evening (5pm–9pm)',                vibe: 'winding down, end of day, decompressing' };
  return                             { label: 'late night (9pm–12am)',            vibe: 'late, reflective, quiet, world slowing down' };
};

// ── AI-generated greeting via Local Backend ──────────────────────────────────
const generateWelcomeMsg = async () => {
  const { label, vibe } = getTimeContext();
  try {
    const res = await fetch('http://localhost:8000/api/chat/greeting', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, vibe }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.greeting) {
        return { sender: 'resona', text: data.greeting, isGreeting: true };
      }
    }
  } catch (err) {
    console.error('Welcome msg generation failed:', err);
  }
  return { sender: 'resona', text: "hey... what's on your mind?", isGreeting: true };
};

export default function App() {
  const [inputMode, setInputMode] = useState('voice');
  const [isRecording, setIsRecording] = useState(false);
  const [inputText, setInputText] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  const [currentVoice, setCurrentVoice] = useState(
    () => localStorage.getItem('resona_voice_id') || 'EXAVITQu4vr4xnSDxMaL'
  );

  const [sessionsList, setSessionsList] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [messages, setMessages] = useState([]);

  const activeSessionRef = useRef(null);
  const isFirstMessageRef = useRef(true);

  const voiceOptions = [
    { name: '✨ Bella (Warm)', id: 'EXAVITQu4vr4xnSDxMaL' },
    { name: '🍃 Nicole (Whispery)', id: 'cQthpqGcbbtPoEMXj1AB' },
    { name: '🌊 Antoni (Smooth Male)', id: 'ErXwobaYiN019PkySvjV' },
  ];

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    activeSessionRef.current = activeSession;
  }, [activeSession]);

  // Bootstrap initial layout loads
  useEffect(() => {
    refreshSidebar();
    setMessages([{ sender: 'resona', text: '', isTyping: true }]);
    setActiveSession(null);
    activeSessionRef.current = null;
    isFirstMessageRef.current = true;

    generateWelcomeMsg().then(msg => {
      setMessages([msg]);
    });
  }, []);

  const refreshSidebar = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/chat/sessions');
      if (res.ok) setSessionsList(await res.json());
    } catch (err) {
      console.error('Sidebar refresh failed:', err);
    }
  };

  const loadSession = async (sessionId) => {
    setActiveSession(sessionId);
    activeSessionRef.current = sessionId;

    try {
      const res = await fetch(`http://localhost:8000/api/chat/history/${sessionId}`);
      if (!res.ok) return;

      const dbData = await res.json();
      const mapped = dbData
        .map(msg => ({ sender: msg.role === 'assistant' ? 'resona' : msg.role, text: msg.content }))
        .filter(m => m.text && m.text !== 'Conversation space initiated.');

      if (mapped.length === 0) {
        setMessages([{ sender: 'resona', text: '', isTyping: true }]);
        isFirstMessageRef.current = true;
        generateWelcomeMsg().then(msg => setMessages([msg]));
      } else {
        setMessages(mapped);
        isFirstMessageRef.current = false;
      }
    } catch (err) {
      console.error('Failed to load session:', err);
      setMessages([{ sender: 'resona', text: '', isTyping: true }]);
      isFirstMessageRef.current = true;
      generateWelcomeMsg().then(msg => setMessages([msg]));
    }
  };

  const createNewChatSession = () => {
    setActiveSession(null);
    activeSessionRef.current = null;
    setInputText('');
    isFirstMessageRef.current = true;
    setMessages([{ sender: 'resona', text: '', isTyping: true }]);

    generateWelcomeMsg().then(msg => {
      setMessages([msg]);
    });
  };

  const ensureSession = async () => {
    if (activeSessionRef.current) return activeSessionRef.current;
    try {
      const res = await fetch('http://localhost:8000/api/chat/create-session', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to create session');
      const data = await res.json();
      setActiveSession(data.session_id);
      activeSessionRef.current = data.session_id;
      return data.session_id;
    } catch (err) {
      console.error('Create session failed:', err);
      return null;
    }
  };

  const generateTitle = async (sessionId, firstMessage) => {
    try {
      await fetch('http://localhost:8000/api/chat/generate-title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, first_message: firstMessage }),
      });
      await refreshSidebar();
    } catch (err) {
      console.error('Title generation failed:', err);
    }
  };

  const parseStream = async (response, onPolished, onReply, onSentence) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let fullReply = '';
    let sentenceBuffer = '';

    const SENTENCE_END = /[.!?]+\s*$/;

    const flushSentence = (force = false) => {
      const trimmed = sentenceBuffer.trim();
      if (!trimmed) return;
      if (force || SENTENCE_END.test(trimmed)) {
        if (onSentence) onSentence(trimmed);
        sentenceBuffer = '';
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        if (buffer.trim()) {
          try {
            const parsed = JSON.parse(buffer.trim());
            if (parsed.polished_input && onPolished) onPolished(parsed.polished_input);
            if (parsed.reply) {
              fullReply += parsed.reply;
              onReply(parsed.reply);
              sentenceBuffer += parsed.reply;
            }
          } catch (_) {}
        }
        flushSentence(true);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const parsed = JSON.parse(line);
          if (parsed.polished_input && onPolished) onPolished(parsed.polished_input);
          if (parsed.reply) {
            fullReply += parsed.reply;
            onReply(parsed.reply);
            sentenceBuffer += parsed.reply;
            flushSentence();
          }
        } catch (_) {}
      }
    }
    return fullReply;
  };

  const appendUserMessage = (userText) => {
    setMessages(prev => {
      const base = prev.length === 1 && prev[0].sender === 'resona' ? [] : prev;
      return [...base, { sender: 'user', text: userText }, { sender: 'resona', text: '' }];
    });
  };

  const appendAssistantChunk = (chunk) => {
    setMessages(prev => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last && last.sender === 'resona') {
        updated[updated.length - 1] = { ...last, text: last.text + chunk };
      }
      return updated;
    });
  };

  const updateUserBubble = (polishedText) => {
    setMessages(prev => {
      const updated = [...prev];
      const userBubble = updated[updated.length - 2];
      if (userBubble && userBubble.sender === 'user') {
        updated[updated.length - 2] = { ...userBubble, text: polishedText };
      }
      return updated;
    });
  };

  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    const text = inputText.trim();
    if (!text || isProcessing) return;

    preWarmAudio();

    const sessionId = await ensureSession();
    if (!sessionId) return;

    const isFirst = isFirstMessageRef.current;

    setInputText('');
    setIsProcessing(true);
    appendUserMessage(text);

    if (isFirst) isFirstMessageRef.current = false;

    try {
      const res = await fetch('http://localhost:8000/api/chat/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const ttsPromise = startPipelinedTTS(currentVoice);

      const fullReply = await parseStream(
        res,
        updateUserBubble,
        appendAssistantChunk,
        (sentence) => ttsPromise.pushSentence(sentence)
      );

      ttsPromise.done();

      if (isFirst && fullReply.trim()) {
        generateTitle(sessionId, text);
      }

      await ttsPromise.finished;
    } catch (err) {
      console.error('Send message failed:', err);
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.sender === 'resona' && !last.text) {
          updated[updated.length - 1] = { ...last, text: 'Something went wrong. Please try again.' };
        }
        return updated;
      });
    } finally {
      setIsProcessing(false);
      refreshSidebar();
    }
  };

  const startRecording = async () => {
    preWarmAudio();
    audioChunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? { mimeType: 'audio/webm;codecs=opus' }
        : { mimeType: 'audio/webm' };
      mediaRecorderRef.current = new MediaRecorder(stream, options);
      mediaRecorderRef.current.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      mediaRecorderRef.current.onstop = async () => {
        const blob = new Blob(audioChunksRef.current, { type: mediaRecorderRef.current.mimeType });
        stream.getTracks().forEach(t => t.stop());
        await sendAudioToBackend(blob);
      };
      mediaRecorderRef.current.start(250);
      setIsRecording(true);
    } catch (err) {
      console.error('Mic init failed:', err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      try { mediaRecorderRef.current.requestData(); } catch (_) {}
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const sendAudioToBackend = async (blob) => {
    const sessionId = await ensureSession();
    if (!sessionId) return;

    const isFirst = isFirstMessageRef.current;
    setIsProcessing(true);

    const formData = new FormData();
    formData.append('file', blob, 'user_voice_input.webm');

    try {
      const transcribeRes = await fetch('http://localhost:8000/api/chat/audio-transcribe', {
        method: 'POST',
        body: formData,
      });
      const transcribeData = await transcribeRes.json();

      const transcribed = transcribeData.text?.trim();
      if (transcribeData.status !== 'success' || !transcribed || transcribed.length < 2) return;

      if (isFirst) isFirstMessageRef.current = false;
      appendUserMessage(transcribed);

      const chatRes = await fetch('http://localhost:8000/api/chat/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: transcribed, session_id: sessionId }),
      });

      const ttsPromise = startPipelinedTTS(currentVoice);

      const fullReply = await parseStream(
        chatRes,
        null,
        appendAssistantChunk,
        (sentence) => ttsPromise.pushSentence(sentence)
      );

      ttsPromise.done();

      if (isFirst && fullReply.trim()) {
        generateTitle(sessionId, transcribed);
      }

      await ttsPromise.finished;
    } catch (err) {
      console.error('Audio pipeline failed:', err);
    } finally {
      setIsProcessing(false);
      refreshSidebar();
    }
  };

  const handleClearHistory = async () => {
    if (!activeSessionRef.current) return;
    if (!window.confirm('Clear this chat session?')) return;
    try {
      await fetch(`http://localhost:8000/api/chat/clear/${activeSessionRef.current}`, { method: 'DELETE' });
      await refreshSidebar();
    } catch (err) {
      console.error('Clear history failed:', err);
    }
    createNewChatSession();
  };

  const preWarmAudio = () => {
    if (!globalAudioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      globalAudioCtx = new AC();
    }
    if (globalAudioCtx.state === 'suspended') globalAudioCtx.resume();
  };

  const startPipelinedTTS = (voiceId) => {
    preWarmAudio();

    let nextPlayTime = globalAudioCtx.currentTime;
    let resolveFinished;
    const finished = new Promise(res => { resolveFinished = res; });

    const fetchQueue = [];
    let isDone = false;

    const fetchSentenceAudio = async (sentence) => {
      const allChunks = [];
      try {
        const res = await fetch('http://localhost:8000/api/chat/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: sentence, voice_id: voiceId }),
        });
        if (!res.ok) return allChunks;

        const reader = res.body.getReader();
        const BATCH = 32 * 1024;
        let chunks = [], chunkLen = 0;

        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            if (chunkLen > 0) {
              const buf = new Uint8Array(chunkLen);
              let off = 0;
              for (const c of chunks) { buf.set(c, off); off += c.length; }
              allChunks.push(buf.buffer);
            }
            break;
          }
          chunks.push(value);
          chunkLen += value.length;
          if (chunkLen >= BATCH) {
            const buf = new Uint8Array(chunkLen);
            let off = 0;
            for (const c of chunks) { buf.set(c, off); off += c.length; }
            allChunks.push(buf.buffer);
            chunks = []; chunkLen = 0;
          }
        }
      } catch (err) {
        print('TTS fetch failed:', err);
      }
      return allChunks;
    };

    const scheduleBuffer = async (arrayBuffer) => {
      try {
        const audioBuf = await globalAudioCtx.decodeAudioData(arrayBuffer);
        const src = globalAudioCtx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(globalAudioCtx.destination);
        const startAt = Math.max(nextPlayTime, globalAudioCtx.currentTime);
        src.start(startAt);
        nextPlayTime = startAt + audioBuf.duration;
        await new Promise(r => setTimeout(r, audioBuf.duration * 1000));
      } catch (_) {}
    };

    const runPlaybackLoop = async () => {
      while (true) {
        if (fetchQueue.length === 0) {
          if (isDone) { resolveFinished(); break; }
          await new Promise(r => setTimeout(r, 20));
          continue;
        }
        const audioChunks = await fetchQueue.shift();
        for (const chunk of audioChunks) {
          await scheduleBuffer(chunk);
        }
      }
    };

    runPlaybackLoop();

    return {
      pushSentence(sentence) {
        const trimmed = sentence.trim();
        if (!trimmed) return;
        fetchQueue.push(fetchSentenceAudio(trimmed));
      },
      done() { isDone = true; },
      finished,
    };
  };

  const handleVoiceChange = (e) => {
    setCurrentVoice(e.target.value);
    localStorage.setItem('resona_voice_id', e.target.value);
  };

  return (
    <div className="app-layout-wrapper">
      {sidebarOpen && (
        <aside className="resona-sidebar">
          <button onClick={createNewChatSession}>
            <Plus size={16} /> New Chat Space
          </button>
          <div className="sidebar-feed-container">
            <span>Past Conversations</span>
            {sessionsList.map((session) => (
              <button
                key={session.session_id}
                onClick={() => loadSession(session.session_id)}
                className={activeSession === session.session_id ? 'active' : ''}
              >
                <MessageSquare size={14} style={{ opacity: 0.7, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{session.display_name}</span>
              </button>
            ))}
          </div>
        </aside>
      )}

      <div className="resona-container">
        <header className="resona-header">
          <div className="logo-group">
            <button onClick={() => setSidebarOpen(!sidebarOpen)}>
              <Menu size={20} />
            </button>
            <div className="status-dot animate-pulse" />
            <h1 className="logo-text">RESONA</h1>
          </div>
          <div className="header-controls">
            <select
              value={currentVoice}
              onChange={handleVoiceChange}
              className="voice-dropdown"
              disabled={isProcessing || isRecording}
            >
              {voiceOptions.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <button onClick={handleClearHistory} className="trash-reset-btn" title="Clear Chat">
              <Trash2 size={20} />
            </button>
          </div>
          <span className="core-badge">99.5% Emotional Core</span>
        </header>

        <div className="chat-display">
          {messages.map((msg, i) => (
            <div key={i} className={`message-bubble-row ${msg.sender}`}>
              <div className={`message-content-text${msg.isGreeting ? ' greeting-bubble' : ''}`}>
                {msg.isTyping ? (
                  <div className="typing-dots">
                    <span /><span /><span />
                  </div>
                ) : msg.text}
              </div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        <footer className="resona-footer">
          <div className="input-wrapper">
            {inputMode === 'voice' ? (
              <div className={`voice-panel${isRecording ? ' recording-active' : ''}`}>
                {isProcessing ? (
                  <div className="thinking-orb-container">
                    <div className="thinking-orb" />
                    <p className="status-message">Resona is translating thoughts...</p>
                  </div>
                ) : (
                  <p className="status-message">
                    {isRecording ? 'Listening to you vent...' : 'Tap to speak with Resona'}
                  </p>
                )}
                <div className="voice-controls">
                  <button
                    type="button"
                    onClick={() => setInputMode('text')}
                    className="icon-button key-toggle"
                    title="Switch to Typing"
                  >
                    <Keyboard size={20} />
                  </button>
                  <button
                    type="button"
                    onMouseEnter={preWarmAudio}
                    onFocus={preWarmAudio}
                    onClick={isRecording ? stopRecording : startRecording}
                    className={`mic-action-btn ${isRecording ? 'recording-pulse' : 'idle-mic'}`}
                  >
                    {isRecording ? <Square size={24} fill="currentColor" /> : <Mic size={24} />}
                  </button>
                  <div className="spacer-node" />
                </div>
              </div>
            ) : (
              <form onSubmit={handleSendMessage} className="text-panel">
                <input
                  type="text"
                  value={inputText}
                  onChange={e => setInputText(e.target.value)}
                  placeholder="Share what's going on..."
                  className="text-input-field"
                  disabled={isProcessing}
                />
                <button
                  type="button"
                  onClick={() => setInputMode('voice')}
                  className="icon-button mic-toggle"
                  title="Switch to Voice"
                >
                  <Mic size={18} />
                </button>
                <button
                  type="submit"
                  disabled={!inputText.trim() || isProcessing}
                  className={`send-action-btn ${inputText.trim() ? 'active-send' : 'disabled-send'}`}
                >
                  <Send size={16} />
                </button>
              </form>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}