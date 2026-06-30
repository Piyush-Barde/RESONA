import os
import logging
from collections import deque
from dotenv import load_dotenv
from groq import AsyncGroq
from spellchecker import SpellChecker

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RESONA_BACKEND")

GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
GOOGLE_API_KEY     = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID      = os.getenv("GOOGLE_CSE_ID")

MODEL_NAME       = "llama-3.1-8b-instant"
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DB_PATH          = os.path.join(os.path.dirname(__file__), "data", "resona.db")
PROFILE_PATH     = os.path.join(os.path.dirname(__file__), "data", "user_profile.json")

GOOGLE_RATE_LIMIT_MAX    = int(os.getenv("GOOGLE_RATE_LIMIT_MAX", "80"))
GOOGLE_RATE_LIMIT_WINDOW = int(os.getenv("GOOGLE_RATE_LIMIT_WINDOW", "86400"))

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in environment variables")

client = AsyncGroq(api_key=GROQ_API_KEY)

# Spell-correction setup
_WHITELIST_ENV = [
    t.strip()
    for t in os.getenv(
        "SPELL_WHITELIST",
        "Resona,Llama,Clash of Clans,Electro Dragons,IAS,UPSC,MPSC,"
        "Maharashtra,Tukaram,Mundhe,Bollywood,WhatsApp,YouTube,Instagram"
    ).split(",")
    if t.strip()
]

class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls      = max_calls
        self.window_seconds = window_seconds
        self._timestamps = deque()

    def _prune(self):
        import time
        cutoff = time.monotonic() - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def is_allowed(self) -> bool:
        self._prune()
        import time
        if len(self._timestamps) < self.max_calls:
            self._timestamps.append(time.monotonic())
            return True
        return False

    @property
    def remaining(self) -> int:
        self._prune()
        return max(0, self.max_calls - len(self._timestamps))

google_limiter = SlidingWindowRateLimiter(GOOGLE_RATE_LIMIT_MAX, GOOGLE_RATE_LIMIT_WINDOW)

class UniversalTextCorrector:
    def __init__(self, whitelist: list[str] | None = None) -> None:
        import re
        self.spell = SpellChecker(distance=1)
        self._protected = set()
        self._shorthand = {
            "idk": "I don't know", "omg": "oh my god", "woth": "with", "nd": "and",
            "ur": "your", "u": "you", "r": "are", "pls": "please", "plz": "please",
            "ngl": "not gonna lie", "tbh": "to be honest", "imo": "in my opinion",
            "btw": "by the way", "rn": "right now", "fr": "for real", "bc": "because",
            "cuz": "because", "gonna": "going to", "wanna": "want to", "gotta": "got to"
        }
        self._punct_re = re.compile(r"^(.*?)([^\w]*)$", re.DOTALL)
        if whitelist: self._register(whitelist)

    def _register(self, terms: list[str]) -> None:
        for term in terms:
            for word in term.strip().lower().split():
                self._protected.add(word)
                self.spell.word_frequency.load_words([word])

    def _is_proper_noun(self, core: str) -> bool:
        if len(core) < 2: return False
        if core.isupper() or (core[0].isupper() and core[1:].islower()): return True
        if any(ch.isdigit() for ch in core) or any(ch.isupper() for ch in core[1:]): return True
        return False

    def clean_text_stream(self, raw: str) -> str:
        if not raw or not raw.strip(): return raw
        out = []
        for token in raw.split():
            m = self._punct_re.match(token)
            core, suffix = (m.group(1), m.group(2)) if m else (token, "")
            lower_core = core.lower()
            if len(lower_core) <= 1 or self._is_proper_noun(core):
                out.append(token)
                continue
            if lower_core in self._shorthand:
                rep = self._shorthand[lower_core]
                if core[0].isupper(): rep = rep.capitalize()
                out.append(rep + suffix)
                continue
            if lower_core in self._protected or lower_core in self.spell:
                out.append(token)
                continue
            sug = self.spell.correction(lower_core)
            if sug and sug != lower_core:
                if core[0].isupper(): sug = sug.capitalize()
                out.append(sug + suffix)
            else:
                out.append(token)
        return " ".join(out)

text_corrector = UniversalTextCorrector(whitelist=_WHITELIST_ENV)