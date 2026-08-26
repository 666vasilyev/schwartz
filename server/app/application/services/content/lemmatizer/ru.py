"""Лемматизация русского — spaCy ru_core_news_sm, без доп. словарей (см. lemmatizer/__init__.py)."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from spacy.language import Language

_nlp: "Language | None" = None
_lock = threading.Lock()


def _get_nlp() -> "Language":
    global _nlp
    if _nlp is not None:
        return _nlp
    with _lock:
        if _nlp is not None:
            return _nlp
        import spacy

        _nlp = spacy.load("ru_core_news_sm")
        return _nlp


def lemmatize_ru(text: str) -> str:
    nlp = _get_nlp()
    doc = nlp(text)
    lemmas = [token.lemma_ for token in doc if not token.is_space]
    return " ".join(lemmas) if lemmas else text
