import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Mic, Square, Keyboard, Send, Trash2, MessageSquare, Plus, Menu } from 'lucide-react';
import './App.css';

let globalAudioCtx = null;

const WELCOME_MSG = { sender: 'resona', text: "Brand new canvas space! I'm listening, tell me everything..." };

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

  // Refs to avoid stale closures in async handlers
  const activeSessionRef = useRef(null);
  const isFirstMessageRef = useRef(true); // tracks if current session has had its first real message

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

  // Keep ref in sync with state so async functions always see latest session
  useEffect(() => {
    activeSessionRef.current = activeSession;
  }, [activeSession]);

  // Bootstrap: load sessions on mount
  useEffect(() => {
    const init = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/chat/sessions');
        if (!res.ok) return;
        const data = await res.json();
        setSessionsList(data);
        if (data.length > 0) {
          await loadSession(data[0].session_id);
        } else {
          await createNewChatSession();
        }
      } catch (err) {
        console.error('Init failed:', err);
      }
    };
    init();
  }, []);

  // ─── Load sessions list (sidebar refresh) ────────────────────────────────────
  const refreshSidebar = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/chat/sessions');
      if (res.ok) setSessionsList(await res.json());
    } catch (err) {
      console.error('Sidebar refresh failed:', err);
    }
  };

  // ─── Load a specific session's messages ──────────────────────────────────────
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
        setMessages([WELCOME_MSG]);
        isFirstMessageRef.current = true;
      } else {
        setMessages(mapped);
        isFirstMessageRef.current = false;
      }
    } catch (err) {
      console.error('Failed to load session:', err);
      setMessages([WELCOME_MSG]);
      isFirstMessageRef.current = true;
    }
  };

  // ─── Create new session ───────────────────────────────────────────────────────
  const createNewChatSession = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/chat/create-session', { method: 'POST' });
      if (!res.ok) return;
      const data = await res.json();
      setActiveSession(data.session_id);
      activeSessionRef.current = data.session_id;
      setMessages([WELCOME_MSG]);
      isFirstMessageRef.current = true;
      await refreshSidebar();
    } catch (err) {
      console.error('Create session failed:', err);
    }
  };

  // ─── Generate title after FIRST real message ──────────────────────────────────
  // Uses the ref so it always sees the correct sessionId even inside async flows
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

  // ─── Parse streaming NDJSON + fire TTS as soon as first sentence is ready ────
  // sentenceCallback is called with each complete sentence as it arrives,
  // so TTS can start in parallel with the remaining text stream.
  const parseStream = async (response, onPolished, onReply, onSentence) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let fullReply = '';
    let sentenceBuffer = '';       // accumulates tokens until a sentence boundary
    let firstSentenceFired = false;

    const SENTENCE_END = /[.!?]+\s*$/;

    const flushSentence = (force = false) => {
      const trimmed = sentenceBuffer.trim();
      if (!trimmed) return;
      if (force || SENTENCE_END.test(trimmed)) {
        if (onSentence) onSentence(trimmed);
        sentenceBuffer = '';
        firstSentenceFired = true;
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
        // Flush any remaining sentence text at end of stream
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

  // ─── Append user + empty assistant bubble ────────────────────────────────────
  const appendUserMessage = (userText) => {
    setMessages(prev => {
      const filtered = prev.filter(m => m.text !== WELCOME_MSG.text);
      return [...filtered, { sender: 'user', text: userText }, { sender: 'resona', text: '' }];
    });
  };

  // ─── Update last assistant bubble (streaming) ────────────────────────────────
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

  // ─── Update user bubble with polished text ───────────────────────────────────
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

  // ─── Send text message ────────────────────────────────────────────────────────
  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    const text = inputText.trim();
    if (!text || isProcessing || !activeSessionRef.current) return;

    preWarmAudio();
    const sessionId = activeSessionRef.current; // capture to avoid closure issues
    const isFirst = isFirstMessageRef.current;

    setInputText('');
    setIsProcessing(true);
    appendUserMessage(text);

    // Mark that first message has been sent BEFORE the async call
    if (isFirst) isFirstMessageRef.current = false;

    try {
      const res = await fetch('http://localhost:8000/api/chat/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Start TTS as soon as the first complete sentence arrives — runs in
      // parallel with the rest of the text stream so audio begins immediately.
      const ttsPromise = startPipelinedTTS(currentVoice);

      const fullReply = await parseStream(
        res,
        updateUserBubble,
        appendAssistantChunk,
        (sentence) => ttsPromise.pushSentence(sentence)
      );

      ttsPromise.done(); // signal no more sentences coming

      // Generate title only on the very first message of a session
      if (isFirst && fullReply.trim()) {
        generateTitle(sessionId, text); // fire-and-forget, non-blocking
      }

      await ttsPromise.finished; // wait for all audio to finish playing
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

  // ─── Voice recording ──────────────────────────────────────────────────────────
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
      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Mic init failed:', err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const sendAudioToBackend = async (blob) => {
    const sessionId = activeSessionRef.current;
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

      if (transcribeData.status !== 'success' || !transcribeData.text.trim()) return;

      const transcribed = transcribeData.text.trim();
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

  // ─── Clear history ────────────────────────────────────────────────────────────
  const handleClearHistory = async () => {
    if (!window.confirm('Clear this chat session?')) return;
    try {
      await fetch(`http://localhost:8000/api/chat/clear/${activeSessionRef.current}`, { method: 'DELETE' });
      await createNewChatSession();
    } catch (err) {
      console.error('Clear history failed:', err);
    }
  };

  // ─── Audio helpers ────────────────────────────────────────────────────────────
  const preWarmAudio = () => {
    if (!globalAudioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      globalAudioCtx = new AC();
    }
    if (globalAudioCtx.state === 'suspended') globalAudioCtx.resume();
  };

  // ─── Pipelined TTS engine (ordered) ──────────────────────────────────────────
  // Sentences are fetched in parallel but PLAYED in strict arrival order.
  //
  // How it works:
  //   - pushSentence() immediately fires a TTS fetch for each sentence (parallel network)
  //   - Each fetch stores its result as a Promise in an ordered array
  //   - The playback loop awaits them in order — sentence 1 always plays before sentence 2
  //     regardless of which ElevenLabs response arrives first
  //
  // This gives us:
  //   ✅ Low latency  — fetches overlap with LLM streaming
  //   ✅ Correct order — playback is sequential, never scrambled
  const startPipelinedTTS = (voiceId) => {
    preWarmAudio();

    let nextPlayTime = globalAudioCtx.currentTime;
    let resolveFinished;
    const finished = new Promise(res => { resolveFinished = res; });

    // Each entry is a Promise<ArrayBuffer[]> — resolves to the ordered list
    // of audio chunks for that sentence, fetched in parallel.
    const fetchQueue = [];
    let isDone = false;

    // Fetch one sentence → resolve with its collected audio chunks in order
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
        console.error('TTS fetch failed:', err);
      }
      return allChunks;
    };

    // Schedule one ArrayBuffer on the Web Audio clock
    const scheduleBuffer = async (arrayBuffer) => {
      try {
        const audioBuf = await globalAudioCtx.decodeAudioData(arrayBuffer);
        const src = globalAudioCtx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(globalAudioCtx.destination);
        const startAt = Math.max(nextPlayTime, globalAudioCtx.currentTime);
        src.start(startAt);
        nextPlayTime = startAt + audioBuf.duration;
        // Wait for this chunk to finish before scheduling the next
        await new Promise(r => setTimeout(r, audioBuf.duration * 1000));
      } catch (_) {}
    };

    // Playback loop — drains fetchQueue in strict order
    const runPlaybackLoop = async () => {
      while (true) {
        if (fetchQueue.length === 0) {
          if (isDone) { resolveFinished(); break; }
          // Wait briefly for next sentence to be pushed
          await new Promise(r => setTimeout(r, 20));
          continue;
        }
        // Await the next sentence's fetch (it may already be resolved)
        const audioChunks = await fetchQueue.shift();
        for (const chunk of audioChunks) {
          await scheduleBuffer(chunk);
        }
      }
    };

    // Start the playback loop immediately
    runPlaybackLoop();

    return {
      pushSentence(sentence) {
        const trimmed = sentence.trim();
        if (!trimmed) return;
        // Fire fetch immediately (parallel), store the Promise in order
        fetchQueue.push(fetchSentenceAudio(trimmed));
      },
      done() {
        isDone = true;
      },
      finished,
    };
  };

  const handleVoiceChange = (e) => {
    setCurrentVoice(e.target.value);
    localStorage.setItem('resona_voice_id', e.target.value);
  };

  // ─── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="app-layout-wrapper" style={{ display: 'flex', width: '100vw', height: '100vh', background: '#0B0F17', overflow: 'hidden' }}>
      {sidebarOpen && (
        <aside className="resona-sidebar" style={{ width: '260px', background: '#0D131F', borderRight: '1px solid #1F2937', display: 'flex', flexDirection: 'column', padding: '12px', boxSizing: 'border-box' }}>
          <button
            onClick={createNewChatSession}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '10px 14px', background: 'transparent', border: '1px dashed #4B5563', borderRadius: '6px', color: '#E5E7EB', cursor: 'pointer', textAlign: 'left', fontWeight: '500', fontSize: '14px', marginBottom: '16px' }}
          >
            <Plus size={16} /> New Chat Space
          </button>
          <div className="sidebar-feed-container" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '11px', color: '#6B7280', fontWeight: '600', textTransform: 'uppercase', paddingLeft: '4px', marginBottom: '6px' }}>Past Conversations</span>
            {sessionsList.map((session) => (
              <button
                key={session.session_id}
                onClick={() => loadSession(session.session_id)}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%', padding: '10px', background: activeSession === session.session_id ? '#1E293B' : 'transparent', border: 'none', borderRadius: '6px', color: activeSession === session.session_id ? '#38BDF8' : '#9CA3AF', cursor: 'pointer', textAlign: 'left', fontSize: '13.5px', overflow: 'hidden', whiteSpace: 'nowrap' }}
              >
                <MessageSquare size={14} style={{ opacity: 0.7, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{session.display_name}</span>
              </button>
            ))}
          </div>
        </aside>
      )}

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
            <select value={currentVoice} onChange={handleVoiceChange} className="voice-dropdown" disabled={isProcessing || isRecording}>
              {voiceOptions.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <button onClick={handleClearHistory} className="trash-reset-btn" title="Clear Chat" style={{ background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', padding: '4px' }}>
              <Trash2 size={20} />
            </button>
          </div>
          <span className="core-badge">99.5% Emotional Core</span>
        </header>

        <div className="chat-display" style={{ flex: 1, overflowY: 'auto' }}>
          {messages.map((msg, i) => (
            <div key={i} className={`message-bubble-row ${msg.sender}`}>
              <div className="message-content-text">{msg.text}</div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        <footer className="resona-footer">
          <div className="input-wrapper">
            {inputMode === 'voice' ? (
              <div className={`voice-panel ${isRecording ? 'recording-active' : ''}`}>
                {isProcessing ? (
                  <div className="thinking-orb-container">
                    <div className="thinking-orb" />
                    <p className="status-message" style={{ color: '#9CA3AF' }}>Resona is translating thoughts...</p>
                  </div>
                ) : (
                  <p className="status-message">{isRecording ? 'Listening to you vent...' : 'Tap to speak with Resona'}</p>
                )}
                <div className="voice-controls">
                  <button type="button" onClick={() => setInputMode('text')} className="icon-button key-toggle" title="Switch to Typing">
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
                  disabled={isProcessing || !activeSession}
                />
                <button type="button" onClick={() => setInputMode('voice')} className="icon-button mic-toggle" title="Switch to Voice">
                  <Mic size={18} />
                </button>
                <button
                  type="submit"
                  disabled={!inputText.trim() || isProcessing || !activeSession}
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