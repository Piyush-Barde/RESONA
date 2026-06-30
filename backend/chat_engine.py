import json
import asyncio
from fastapi.responses import StreamingResponse
from config import client, MODEL_NAME, logger
from database import get_db_context, append_to_db, get_user_profile
from intent_router import analyze_intent_and_query
from search_engine import get_live_world_knowledge
from memory_engine import lookup_past_reference, extract_and_save_session_indices
from prompt_builder import build_system_prompt
from learning_engine import trigger_background_reflection

FEW_SHOT_EXAMPLES = [
    {"role": "user", "content": "i'm so tired today"},
    {"role": "assistant", "content": "ugh same, did you sleep bad or just one of those days?"},
    {"role": "user", "content": "who is Tukaram Mundhe"},
    {"role": "assistant", "content": "he's a 2005-batch IAS officer in Maharashtra — got transferred 24 times for refusing political pressure. total legend honestly"}
]

async def stream_chat_response(polished: str, safe_session: str) -> StreamingResponse:
    history = get_db_context(session_id=safe_session, limit=12)
    routing = await analyze_intent_and_query(polished, history)
    past_memory_context = lookup_past_reference(polished)

    google_context = ""
    if routing["needs_search"] and routing["query"]:
        try:
            google_context = await asyncio.wait_for(get_live_world_knowledge(routing["query"]), timeout=4.0)
        except asyncio.TimeoutError:
            logger.warning("⏳ Google search timed out.")

    append_to_db("user", polished, safe_session)
    updated_history = get_db_context(session_id=safe_session, limit=12)
    profile = get_user_profile()

    system_content = build_system_prompt(profile, google_context)
    if past_memory_context:
        system_content += (
            "\n\n━━ RECALLED MEMORY REFERENCE (Highest Priority Context) ━━\n"
            "You found a match in your historical logs regarding this. State the reference explicitly "
            "to the user, mentioning the specific room title it was pulled from.\n"
            f"{past_memory_context}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    messages_payload = [{"role": "system", "content": system_content}] + FEW_SHOT_EXAMPLES + updated_history
    token_budget = 1200 if routing["needs_search"] else 150

    async def response_generator():
        full_reply = ""
        first_chunk = True
        try:
            stream = await client.chat.completions.create(
                messages=messages_payload, model=MODEL_NAME, temperature=0.75, max_tokens=token_budget, stream=True
            )
            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    full_reply += token
                    data = {"reply": token}
                    if first_chunk:
                        data["polished_input"] = polished
                        data["search_used"]    = bool(google_context)
                        data["intent_query"]   = routing.get("query", "")
                        first_chunk = False
                    yield json.dumps(data) + "\n"

            if full_reply.strip():
                append_to_db("assistant", full_reply.strip(), safe_session)
                asyncio.create_task(trigger_background_reflection(safe_session))
                asyncio.create_task(extract_and_save_session_indices(safe_session, updated_history))
        except Exception as e:
            logger.error(f"Stream failure: {e}")
            yield json.dumps({"reply": "something went wrong on my end, try again?"}) + "\n"

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")