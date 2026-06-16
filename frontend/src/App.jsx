import React, { useState, useRef, useEffect } from "react";

export default function App() {
  const [messages, setMessages] = useState([
    { sender: "resona", text: "Hey there. I'm here if you need to talk. What's on your mind?" }
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const chatEndRef = useRef(null);

  // Auto-scroll to the bottom when new messages stream in
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSendMessage = async (e) => {
    e.preventDefault();
    const userMessage = input.trim();
    if (!userMessage || isLoading) return;

    // 1. Update UI with User Message
    setMessages((prev) => [...prev, { sender: "user", text: userMessage }]);
    setInput("");
    setIsLoading(true);

    try {
      // 2. Hit your local FastAPI backend server gateway
      const response = await fetch("http://127.0.0.1:8000/api/chat/text", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message: userMessage }),
      });

      if (!response.ok) {
        throw new Error("Backend gateway connection dropped.");
      }

      const data = await response.json();
      
      // 3. Mount Resona's validating emotional response to the screen
      setMessages((prev) => [...prev, { sender: "resona", text: data.response }]);
    } catch (error) {
      console.error("Error communicating with Resona:", error);
      setMessages((prev) => [
        ...prev,
        { sender: "resona", text: "I'm having trouble connecting to my core engine right now. Make sure the backend server is active." }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* Top Header Navigation bar */}
      <header className="app-header">
        <div className="status-indicator"></div>
        <h1>RESONA AI</h1>
        <p>Core Intelligence Operational</p>
      </header>

      {/* Main Messaging Interface viewport */}
      <main className="chat-viewport">
        {messages.map((msg, index) => (
          <div key={index} className={`message-wrapper ${msg.sender}`}>
            <div className="message-bubble">
              <p>{msg.text}</p>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="message-wrapper resona loading">
            <div className="message-bubble">
              <div className="typing-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </main>

      {/* Message Entry controls area */}
      <form onSubmit={handleSendMessage} className="input-control-panel">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Share what's going on..."
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading || !input.trim()}>
          {isLoading ? "Thinking..." : "Send"}
        </button>
      </form>
    </div>
  );
}