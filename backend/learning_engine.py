import os
import json
from database import get_db_context, get_user_profile
from config import client, MODEL_NAME, PROFILE_PATH, logger

async def trigger_background_reflection(session_id: str):
    history = get_db_context(session_id=session_id, limit=6)
    if len(history) < 4: return
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    current_profile = get_user_profile()

    try:
        completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a user-preference extraction engine. "
                        f"Current profile:\n{json.dumps(current_profile)}\n\n"
                        "Return ONLY valid JSON with exactly these three keys: 'likes', 'dislikes', 'topics_discussed'."
                    ),
                },
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
            model=MODEL_NAME, temperature=0.2, response_format={"type": "json_object"},
        )
        updated = json.loads(completion.choices[0].message.content.strip())
        for key in ("likes", "dislikes", "topics_discussed"):
            merged = list(dict.fromkeys(current_profile.get(key, []) + updated.get(key, [])))
            updated[key] = merged[:30]

        os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
        with open(PROFILE_PATH, "w") as f: json.dump(updated, f, indent=4)
    except Exception as e:
        logger.error(f"Self-learning reflection failed: {e}")