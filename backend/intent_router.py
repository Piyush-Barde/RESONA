import re
from config import client, MODEL_NAME, logger

async def analyze_intent_and_query(user_message: str, chat_history: list) -> dict:
    history_lines = []
    for msg in chat_history[-3:]:
        role = "User" if msg.get("role") == "user" else "Resona"
        history_lines.append(f"{role}: {msg.get('content', '').strip()}")
    history_context = "\n".join(history_lines) or "No prior context."

    try:
        response = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intent classification engine. You MUST respond with exactly two lines and nothing else:\n"
                        "NEEDS_SEARCH: true or false\n"
                        "SEARCH_QUERY: 3-8 word Google search query (empty string if false)\n\n"
                        "Rules:\n"
                        "- true only when the message asks about a real person, place, event, live data, or current news.\n"
                        "- false for emotions, casual chat, opinions, or small talk.\n"
                        "- SEARCH_QUERY must be optimized search terms, not a sentence."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Conversation so far:\n{history_context}\n\nLatest message: {user_message}",
                },
            ],
            model=MODEL_NAME,
            temperature=0.0,
            max_tokens=50,
        )

        raw = response.choices[0].message.content.strip()
        needs_search = False
        query        = ""

        for line in raw.splitlines():
            line = line.strip()
            m = re.match(r"NEEDS_SEARCH\s*:\s*(true|false)", line, re.IGNORECASE)
            if m:
                needs_search = m.group(1).lower() == "true"
                continue
            m = re.match(r"SEARCH_QUERY\s*:\s*(.*)", line, re.IGNORECASE)
            if m:
                query = m.group(1).strip().strip('"').strip("'")

        return {"needs_search": needs_search, "query": query}
    except Exception as e:
        logger.error(f"❌ Intent router error: {e}")
        return {"needs_search": False, "query": ""}