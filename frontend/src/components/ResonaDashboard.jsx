import React, { useState, useEffect, useRef } from 'react';

export default function ResonaDashboard() {
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [systemStatus, setSystemStatus] = useState("🔴 Offline. Connect to Resona Server.");
  const [dialogue, setDialogue] = useState([]);
  
  const socketRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const audioSourceRef = useRef(null);
  const activeTokenRef = useRef("");
  const chatBottomRef = useRef(null);

  // Auto-scrolls the chat window when text streams in
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [dialogue]);

  const connectToResona = () => {
    if (socketRef.current) return;

    socketRef.current = new WebSocket("ws://127.0.0.1:8000/stream");
    socketRef.current.binaryType = "arraybuffer";

    socketRef.current.onopen = () => {
      setSystemStatus("✨ Connected to Resona. Click 'Start Speaking'.");
      setIsConnected(true);
    };

    socketRef.current.onmessage = (event) => {
      const packet = JSON.parse(event.data);

      if (packet.event === "status") {
        setSystemStatus(packet.text);
      } else if (packet.event === "user_text") {
        setDialogue((prev) => [...prev, { sender: 'user', text: packet.text }]);
        activeTokenRef.current = ""; 
      } else if (packet.event === "resona_token") {
        activeTokenRef.current += packet.text;
        setDialogue((prev) => {
          const updated = [...prev];
          if (updated.length > 0 && updated[updated.length - 1].sender === 'resona') {
            updated[updated.length - 1].text = activeTokenRef.current;
          } else {
            updated.push({ sender: 'resona', text: activeTokenRef.current });
          }
          return updated;
        });
      }
    };

    socketRef.current.onclose = () => {
      setSystemStatus("🔌 Connection Lost. Verify Backend Server.");
      setIsConnected(false);
      stopMicrophoneStream();
    };
  };

  const startMicrophoneStream = async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      
      audioSourceRef.current = audioContextRef.current.createMediaStreamSource(mediaStream);
      processorRef.current = audioContextRef.current.createScriptProcessor(512, 1, 1);

      processorRef.current.onaudioprocess = (audioEvent) => {
        if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
        const float32Buffer = audioEvent.inputBuffer.getChannelData(0);
        
        const int16FrameArray = new Int16Array(float32Buffer.length);
        for (let i = 0; i < float32Buffer.length; i++) {
          let sample = Math.max(-1, Math.min(1, float32Buffer[i]));
          int16FrameArray[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        socketRef.current.send(int16FrameArray.buffer);
      };

      audioSourceRef.current.connect(processorRef.current);
      processorRef.current.connect(audioContextRef.current.destination);
      setIsRecording(true);
    } catch (err) {
      setSystemStatus("⚠️ Microphone blocked. Check browser settings.");
    }
  };

  const stopMicrophoneStream = () => {
    if (processorRef.current) processorRef.current.disconnect();
    if (audioSourceRef.current) audioSourceRef.current.disconnect();
    if (audioContextRef.current) audioContextRef.current.close();
    audioContextRef.current = null;
    setIsRecording(false);
    setSystemStatus("✨ Transmission stopped.");
  };

  return (
    <div className="resona-container">
      <div className="resona-card">
        <h1>Resona</h1>
        <p className="subtitle">A safe space to sit with your expressions</p>

        <div className={`status-badge ${isConnected ? 'connected' : ''}`}>
          {systemStatus}
        </div>

        <div className="chat-window">
          {dialogue.map((msg, i) => (
            <div key={i} className={`message ${msg.sender}`}>
              {msg.text}
            </div>
          ))}
          <div ref={chatBottomRef} />
        </div>

        <div className="controls">
          {!isConnected ? (
            <button onClick={connectToResona} className="btn btn-primary">
              Connect to Resona
            </button>
          ) : (
            <button 
              onClick={isRecording ? stopMicrophoneStream : startMicrophoneStream} 
              className={`btn ${isRecording ? 'btn-recording' : 'btn-primary'}`}
            >
              {isRecording ? "Stop Streaming" : "Start Speaking"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}