# services/cognition.py
from openai import AsyncOpenAI

class CognitionService:
    def __init__(self):
        # Pointing to a standard local/remote inference server setup
        # Modify the base_url or api_key here if you are using Groq, Ollama, or LM Studio!
        self.client = AsyncOpenAI(
            base_url="https://api.openai.com/v1", 
            api_key="YOUR_OPENAI_OR_LLAMA_API_KEY"
        )
        print("🧠 Cognition AI client mapped and ready.")

    async def fetch_empathetic_stream(self, user_prompt: str):
        """Streams text chunks in real-time from the LLM back to the WebSocket."""
        try:
            response_stream = await self.client.chat.completions.create(
                model="gpt-4o-mini", # Switch to your local model name if running locally (e.g., "llama3")
                messages=[
                    {"role": "system", "content": "You are Resona, an empathetic and supportive voice assistant."},
                    {"role": "user", "content": user_prompt}
                ],
                stream=True
            )
            return response_stream
        except Exception as e:
            print(f"⚠️ Cognition Model Error: {str(e)}")
            raise e