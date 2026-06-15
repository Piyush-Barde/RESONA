# services/cognition.py
import os
import sys
from openai import AsyncOpenAI

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config import settings  # Ensure settings configuration parameters are mapped

class CognitionService:
    def __init__(self):
        # Dynamically pulls endpoint targets and keys from settings to prevent raw hardcoding
        # For Groq: base_url="https://api.groq.com/openai/v1", api_key="gsk_..."
        # For Ollama: base_url="http://127.0.0.1:11434/v1", api_key="ollama"
        self.client = AsyncOpenAI(
            base_url=getattr(settings, "LLM_BASE_URL", "https://api.openai.com/v1"), 
            api_key=getattr(settings, "LLM_API_KEY", "YOUR_API_KEY_HERE")
        )
        # Fallback model selection from settings template or default mini specs
        self.model_name = getattr(settings, "LLM_MODEL", "gpt-4o-mini")
        print(f"🧠 Cognition AI client mapped and ready. Target Engine: {self.model_name}")

    async def stream_response(self, user_prompt: str):
        """
        Asynchronously streams text tokens in real-time back to the main WebSocket pipeline.
        Matches the exact naming requirement called by the main.py runtime task.
        """
        try:
            response_stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are Resona, an empathetic, supportive, and concise voice assistant. Keep answers short."
                    },
                    {"role": "user", "content": user_prompt}
                ],
                stream=True
            )
            
            # Iterate through the stream chunks asynchronously as they arrive from the network matrix
            async for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            print(f"⚠️ Cognition Model Streaming Error: {str(e)}")
            yield f"[Cognition Error: Please check your API configuration or endpoint mapping - {str(e)}]"