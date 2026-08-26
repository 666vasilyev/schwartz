"""
Лемматизация немецкого — spaCy de_core_news_sm + germalemma, тот же стек, что
и в референсном ноутбуке (POS_MAP оттуда же). Без custom-словарей исключений
и без учёта отделяемых приставок глаголов по синтаксическому контексту — в
ноутбуке это работало на целых предложениях, а здесь на входе изолированное
слово/словосочетание без контекста (см. lemmatizer/__init__.py).
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from spacy.language import Language

_nlp: "Language | None" = None
_lemmatizer: Any = None
_lock = threading.Lock()

# Маппинг POS-тегов spaCy в теги GermaLemma — как в референсном ноутбуке.
_POS_MAP = {
    "VERB": "V",
    "NOUN": "N",
    "ADJ": "ADJ",
    "ADV": "ADV",
    "DET": "ART",
    "PRON": "PRO",
    "PROPN": "N",
    "AUX": "V",
}


def _get_pipeline() -> tuple["Language", Any]:
    global _nlp, _lemmatizer
    if _nlp is not None:
        return _nlp, _lemmatizer
    with _lock:
        if _nlp is not None:
            return _nlp, _lemmatizer
        import germalemma
        import spacy

        _nlp = spacy.load("de_core_news_sm")
        _lemmatizer = germalemma.GermaLemma()
        return _nlp, _lemmatizer


def _find_lemma(word: str, pos: str | None, lemmatizer: Any) -> str:
    def _try(w: str, p: str | None) -> str | None:
        try:
            return lemmatizer.find_lemma(w, p) or None
        except ValueError:
            return None
        except Exception:
            return None

    if pos is None:
        return _try(word, None) or word

    result = _try(word, pos)
    if result is not None:
        return result

    mapped = _POS_MAP.get(pos)
    if mapped:
        result = _try(word, mapped)
        if result is not None:
            return result
    return word


def lemmatize_de(text: str) -> str:
    nlp, lemmatizer = _get_pipeline()
    doc = nlp(text)
    lemmas = [_find_lemma(token.text, token.pos_, lemmatizer) for token in doc if not token.is_space]
    return " ".join(lemmas) if lemmas else text
