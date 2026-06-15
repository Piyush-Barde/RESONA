# backend/main.py
import os
import sys
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import numpy as np  # ◄── FIX: Moved to the top level so it's accessible inside the routes!

# ==============================================================================
# 1. CRITICAL PATH & ENVIRONMENT ANCHORING (Must run before ANY ML imports)
# ==============================================================================
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Purge any Anaconda paths leaking into Python's module search indices
sys.path = [path for path in sys.path if not ("anaconda3" in path.lower() and "site-packages" in path.lower())]

# 🛑 CRITICAL WINDOWS FIXES FOR C++ SUBSYSTEM CRASHES
if sys.platform == "win32":
    # 1. Restrict torchaudio from crawling global Anaconda paths
    current_env_path = os.environ.get("PATH", "")
    purged_env_path = ";".join([p for p in current_env_path.split(";") if "anaconda3" not in p.lower()])
    os.environ["PATH"] = purged_env_path
    
    # 2. Force Hugging Face to drop symlinks to prevent C++ file-lock segfaults
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    
    # 3. Handle thread contention overrides for Intel OpenMP runtimes
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

    # 4. ◄── NEW EXPLICIT DLL INJECTION GUARD: Resolves WinError 1114 / c10.dll load blockages
    # Tells the Windows OS handler to allow loading internal venv site-package binaries natively
    venv_lib_dir = os.path.join(backend_dir, "venv", "Lib", "site-packages", "torch", "lib")
    if os.path.exists(venv_lib_dir):
        os.add_dll_directory(venv_lib_dir)

# Safe Local Imports after path stabilization
from config import settings
from services.perception import PerceptionService
from services.cognition import CognitionService

# Global runtime state references
perception_service = None
cognition_service = None

# ==============================================================================
# 2. MODERN FASTAPI LIFESPAN ENGINE
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles professional initialization and thread allocation of ML services."""
    global perception_service, cognition_service
    print("\n⚡🚀 Starting Resona AI Subsystems via Lifespan Engine...")
    
    # Instantiate memory allocations for AI perception and core cognition
    perception_service = PerceptionService()
    cognition_service = CognitionService()
    
    print("✨ Core components loaded cleanly. Pipeline operational.\n")
    yield  # Active execution handoff to routes
    
    print("\n🛑 Shutting down AI engines safely...")

# Initialize master FastAPI framework app
app = FastAPI(title="Resona AI Streaming Engine", lifespan=lifespan)

# ==============================================================================
# 3. REAL-TIME BIDIRECTIONAL WEBSOCKET ROUTER
# ==============================================================================
@app.websocket("/stream")
async def stream_endpoint(websocket: WebSocket):
    """
    Manages low-latency audio byte ingestion, neural VAD parsing, 
    and handles asynchronous concurrency guard drops for user interruptions.
    """
    await websocket.accept()
    print(f"🔌 Client connected successfully: {websocket.client}")

    # Initialize frame tracking metrics
    audio_buffer = bytearray()
    silence_accumulator = 0.0
    is_speaking = False
    active_response_task = None

    # Calculate local loop parameters from centralized settings
    frame_duration = settings.CHUNK_SIZE / 16000.0  # 32ms frame steps at 16kHz
    bytes_per_sample = 2                           # 16-bit PCM Linear
    target_frame_bytes = settings.CHUNK_SIZE * bytes_per_sample

    try:
        while True:
            # Receive raw binary payload over the persistent socket connection
            data = await websocket.receive_bytes()
            audio_buffer.extend(data)

            # Process slices once the buffer fills up to a uniform chunk frame size
            while len(audio_buffer) >= target_frame_bytes:
                # Isolate target frame array chunk
                frame_bytes = bytes(audio_buffer[:target_frame_bytes])
                del audio_buffer[:target_frame_bytes]

                # Cast raw 16-bit PCM buffer to Float32 normalization spectrum [-1.0, 1.0]
                audio_np = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0

                # Execute Neural VAD calculation pass via PyTorch / Silero VAD wrapper
                speech_prob = perception_service.calculate_speech_probability(audio_np)

                if speech_prob >= settings.VAD_THRESHOLD:
                    # User speech boundary hit
                    silence_accumulator = 0.0
                    if not is_speaking:
                        print("🎙️ User vocal entry detected (Neural VAD validation high).")
                        is_speaking = True

                        # ======================================================
                        # BARGE-IN CONCURRENCY GUARD (Claude Interruption Spec)
                        # ======================================================
                        if active_response_task and not active_response_task.done():
                            print("↩️ User Interruption (Barge-In) Intercepted! Cancelling generation task...")
                            active_response_task.cancel()
                            try:
                                await active_response_task
                            except asyncio.CancelledError:
                                print("🧼 In-flight response tasks flushed cleanly. Thread state reset.")
                            
                            # Alert frontend client to instantly halt local hardware audio buffers
                            await websocket.send_json({"event": "interrupted"})
                else:
                    # User is silent during this time block slice
                    if is_speaking:
                        silence_accumulator += frame_duration
                        
                        # Check if silence crosses our timeout gate boundary
                        if silence_accumulator >= settings.SILENCE_TIMEOUT:
                            print(f"🛑 User completed utterance. Transitioning processing to STT pipeline.")
                            is_speaking = False
                            silence_accumulator = 0.0

                            # Fork background task for transcription and streaming LLM generation
                            active_response_task = asyncio.create_task(
                                run_generation_pipeline(websocket)
                            )

    except WebSocketDisconnect:
        print(f"🔌 Client connection dropped smoothly: {websocket.client}")
    except Exception as e:
        print(f"⚠️ Exception intercepted on WebSocket handler loop: {str(e)}")
    finally:
        if active_response_task and not active_response_task.done():
            active_response_task.cancel()


async def run_generation_pipeline(websocket: WebSocket):
    """Asynchronous worker context that coordinates STT extraction and pushes text data out."""
    try:
        # 1. Fetch raw utterance frame dump from memory
        # (For this baseline, passing a short silent wave chunk as placeholder data alignment)
        test_audio = np.zeros(16000 * 2, dtype=np.float32)
        
        # 2. Run Greedy Native Whisper Text Extraction
        user_transcript = perception_service.transcribe_audio_buffer(test_audio)
        if not user_transcript:
            return

        print(f"📝 User Transcript: '{user_transcript}'")
        await websocket.send_json({"event": "transcript", "text": user_transcript})

        # 3. Stream generated LLM response data chunks directly over the WebSocket
        print("🤖 Instantiating Cognition Layer Stream Interface...")
        async for text_token in cognition_service.stream_response(user_transcript):
            await websocket.send_json({"event": "text_chunk", "text": text_token})
            await asyncio.sleep(0.01) # Yield core event loop frame clock

        print("🏁 LLM Stream task finished writing tokens to channel.")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"⚠️ Generation subtask failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    # Start production local server engine using unified configuration paths
    print("🚀 Initializing Uvicorn Gateway...")
    # ◄── FIX: Changed "main.py:app" to "main:app" for clean ASGI importing
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)