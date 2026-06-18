import requests

# 🔑 Hardcode your key right here temporarily
api_key = "sk_31b70985a0fabd7c7fc2d07d4d04dc2c99a4c8a38c699d1a"

print("🔍 Fetching your real account voice strings from ElevenLabs...")
url = "https://api.elevenlabs.io/v1/voices"
headers = {
    "xi-api-key": api_key,
    "Content-Type": "application/json"
}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        voices_data = response.json().get("voices", [])
        print("\n=== ✨ YOUR AVAILABLE VOICE ALLOCATIONS ===")
        for voice in voices_data:
            print(f"🎤 NAME: {voice.get('name')}")
            print(f"🆔 ID:   {voice.get('voice_id')}")
            print(f"📦 TYPE: {voice.get('category')}")
            print("-" * 45)
        print("===========================================")
    else:
        print(f"❌ Failed to fetch. Status code: {response.status_code}")
        print(f"📄 Error Details: {response.text}")
except Exception as e:
    print(f"❌ Error occurred: {str(e)}")