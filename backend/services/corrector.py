import re
from spellchecker import SpellChecker

class UniversalTextCorrector:
    def __init__(self, custom_whitelist: list = None):
        # 1. Initialize a general-purpose Levenshtein English dictionary
        self.spell = SpellChecker(distance=1)
        
        # 2. Dynamic protective layer (Empty by default, fully general)
        self.protected_terms = set()
        if custom_whitelist:
            self.add_protected_terms(custom_whitelist)
            
        # 3. Common global internet text abbreviations / shorthand corrections
        self.global_shorthand_map = {
            "nd": "and",
            "woth": "with",
            "u": "you",
            "r": "are",
            "idk": "I don't know",
            "omg": "oh my god"
        }

    def add_protected_terms(self, terms: list):
        """Allows adding unique names or terms dynamically down the road."""
        for term in terms:
            normalized = term.strip().lower()
            self.protected_terms.add(normalized)
            # Load individual components of multi-word phrases so spellcheck accepts them
            for word in normalized.split():
                self.spell.word_frequency.load_words([word])

    def clean_text_stream(self, raw_input: str) -> str:
        """
        Takes ANY sentence, runs a global spell check, fixes shorthand/typos,
        and safely returns clean English.
        """
        if not raw_input or not raw_input.strip():
            return raw_input

        words = raw_input.split()
        corrected_words = []

        for word in words:
            # Isolate the core word from surrounding punctuation markers (e.g., "hello," -> "hello")
            clean_word = re.sub(r'[^\w\s]', '', word).lower()
            punctuation_suffix = word[len(clean_word):] if len(clean_word) < len(word) else ""

            # Rule A: Check global quick shorthand conversions first
            if clean_word in self.global_shorthand_map:
                corrected_words.append(self.global_shorthand_map[clean_word] + punctuation_suffix)
                continue

            # Rule B: Protect verified app terms or structurally correct dictionary words
            if clean_word in self.protected_terms or clean_word in self.spell:
                corrected_words.append(word)
                continue

            # Rule C: Detect unknown structural spelling anomalies and auto-correct
            misspelled = self.spell.unknown([clean_word])
            if misspelled:
                suggestion = self.spell.correction(clean_word)
                if suggestion:
                    # Keep original text capitalization style intact (e.g., "Thas" -> "That")
                    if word[0].isupper():
                        suggestion = suggestion.capitalize()
                    corrected_words.append(suggestion + punctuation_suffix)
                    continue

            corrected_words.append(word)

        return " ".join(corrected_words)

# Instantiate the general system engine
text_corrector = UniversalTextCorrector()

# Optional: You can explicitly inject names later in your app setup without hacking the class:
# text_corrector.add_protected_terms(["Resona", "Clash of Clans", "Llama"])