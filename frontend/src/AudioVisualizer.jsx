import React, { useEffect, useRef } from "react";

export const AudioVisualizer = ({ audioContext, audioSource, isStreaming }) => {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);

  useEffect(() => {
    if (!audioContext || !canvasRef.current) return;

    // 1. Create an AnalyserNode to extract real-time frequency/amplitude data
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256; // Smaller fftSize gives a smoother, less jagged waveform line
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    // 2. Route the active audio source into our analyser engine
    let connectedSource = null;
    if (audioSource) {
      connectedSource = audioSource;
      connectedSource.connect(analyser);
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");

    // 3. High-performance 60FPS animation loop
    const renderWaveform = () => {
      animationRef.current = requestAnimationFrame(renderWaveform);

      const width = canvas.width;
      const height = canvas.height;

      // Pull the current time-domain amplitude data
      analyser.getByteTimeDomainData(dataArray);

      // Deep premium dark background signature matching your UI
      ctx.fillStyle = "#0B0F17"; 
      ctx.fillRect(0, 0, width, height);

      ctx.lineWidth = 3;
      // Vibrant custom cyan glow palette matching RESONA branding
      ctx.strokeStyle = isStreaming ? "#38BDF8" : "#818CF8"; 
      ctx.beginPath();

      const sliceWidth = width / bufferLength;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        // Normalize 0-255 byte domain value down to normal wave range
        const v = dataArray[i] / 128.0; 
        let y = (v * height) / 2;

        // Flatten the visual lines subtly if there's complete silence
        if (!isStreaming && (v > 0.99 && v < 1.01)) {
          y = height / 2 + Math.sin(i * 0.1 + Date.now() * 0.005) * 2;
        }

        if (i === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }

        x += sliceWidth;
      }

      ctx.lineTo(width, height / 2);
      ctx.stroke();
    };

    renderWaveform();

    // Cleanup loop frames on dismount
    return () => {
      cancelAnimationFrame(animationRef.current);
      if (connectedSource && audioSource) {
        try {
          connectedSource.disconnect(analyser);
        } catch (e) {
          // Prevent race conditions on stream terminations
        }
      }
    };
  }, [audioContext, audioSource, isStreaming]);

  return (
    <canvas
      ref={canvasRef}
      width={400}
      height={80}
      className="rounded-xl border border-gray-800 bg-[#0B0F17] shadow-inner"
    />
  );
};