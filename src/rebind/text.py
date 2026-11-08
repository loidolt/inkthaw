"""Text helpers shared by cleanup rules and quality checks."""

from __future__ import annotations

import re
import unicodedata
from functools import cache

PAGE_NUMBER_RE = re.compile(
    r"^\s*[\[(\-–—]?\s*(\d{1,4}|[ivxlcdm]{1,8})\s*[\])\-–—]?\s*$", re.IGNORECASE
)

# Paragraph ends: sentence punctuation, optionally followed by closing quotes or
# brackets; or an interrupting dash inside closing quotes.
_TERMINAL_RE = re.compile(r"([.!?…]|[—–]['\"”’»)])['\"”’»)\]]*$")
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)

ROMAN_RE = r"[ivxlcdm]+"
NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|first|second|"
    "third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last"
)
CHAPTER_RE = re.compile(
    rf"^\s*(chapter|book|part|section|letter|canto|stave)\s+"
    rf"(\d+|{ROMAN_RE}|{NUMBER_WORDS})\b[.:]?(\s.*)?$",
    re.IGNORECASE,
)


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER_RE.match(text))


def is_terminal(text: str) -> bool:
    """Does the text end the way a paragraph can end?"""
    return bool(_TERMINAL_RE.search(text.rstrip()))


def starts_lowercase(text: str) -> bool:
    """First letter (skipping quotes/punctuation) is lowercase."""
    for ch in text:
        if ch.isalpha():
            return ch.islower()
        if ch.isdigit():
            return False
    return False


def normalize_furniture(text: str) -> str:
    """Key for comparing running headers: case-folded, digits/roman folded, no punctuation."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"\d+", "#", t)
    t = re.sub(rf"^\s*{ROMAN_RE}\b\.?|\b{ROMAN_RE}\.?\s*$", "#", t)
    t = re.sub(r"[^\w#]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def base_language(lang: str | None) -> str:
    return (lang or "en").split("-")[0].split("_")[0].lower()


@cache
def _supported_languages() -> frozenset[str]:
    try:
        from wordfreq import available_languages
    except ImportError:  # pragma: no cover - wordfreq is a core dependency
        return frozenset()
    return frozenset(available_languages())


def dictionary_available(lang: str | None) -> bool:
    return base_language(lang) in _supported_languages()


@cache
def zipf(word: str, lang: str) -> float:
    """Zipf frequency (0 = unknown, ~7 = 'the'). 0 if the language is unsupported."""
    lang = base_language(lang)
    if lang not in _supported_languages():
        return 0.0
    from wordfreq import zipf_frequency

    return zipf_frequency(word, lang)


def is_known_word(word: str, lang: str, min_zipf: float = 1.0) -> bool:
    return zipf(word.lower(), lang) >= min_zipf
