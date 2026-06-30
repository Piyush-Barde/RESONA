import asyncio
from googleapiclient.discovery import build
from config import GOOGLE_API_KEY, GOOGLE_CSE_ID, google_limiter, logger

async def get_live_world_knowledge(query: str, num_results: int = 3) -> str:
    if not query or len(query.strip()) < 3 or not GOOGLE_API_KEY or not GOOGLE_CSE_ID or not google_limiter.is_allowed():
        return ""
    try:
        def _run_search():
            service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
            return service.cse().list(q=query, cx=GOOGLE_CSE_ID, num=num_results).execute()

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, _run_search)
        items = res.get("items", [])
        if not items: return ""

        chunks = []
        for item in items:
            title   = item.get("title", "").strip()
            snippet = item.get("snippet", "").strip().replace("\n", " ")
            if title and snippet: chunks.append(f"• {title}: {snippet}")
        return "\n".join(chunks)[:900]
    except Exception as e:
        logger.error(f"❌ Google grounding error: {e}")
        return ""