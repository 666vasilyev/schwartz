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


_nlp_light: "Language | None" = None


def _get_nlp_light() -> "Language":
    """Облегчённый конвейер (без parser/ner) для массовой лемматизации отдельных слов."""
    global _nlp_light
    if _nlp_light is not None:
        return _nlp_light
    with _lock:
        if _nlp_light is not None:
            return _nlp_light
        import spacy

        _nlp_light = spacy.load("ru_core_news_sm", exclude=["parser", "ner"])
        return _nlp_light


def lemmatize_ru_batch(tokens: list[str]) -> list[str]:
    """Лемма для каждого слова из списка (порядок и длина сохраняются)."""
    if not tokens:
        return []
    nlp = _get_nlp_light()
    out: list[str] = []
    for tok, doc in zip(tokens, nlp.pipe(tokens, batch_size=1000)):
        lemmas = [t.lemma_ for t in doc if not t.is_space]
        out.append(" ".join(lemmas) if lemmas else tok)
    return out
