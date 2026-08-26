"""
Лемматизация английского — Stanza (en), тот же стек, что и в референсном
ноутбуке. Без словаря исключений и без склейки дефисов/апострофов —
изолированное слово/словосочетание без контекста предложения (см.
lemmatizer/__init__.py).

Ресурсы модели живут в settings.stanza_resources_dir (смонтированный volume,
см. docker-compose.yml) — качаются один раз при первом обращении, дальше
пайплайн грузится offline с диска, без сети.
"""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    import stanza

_nlp: "stanza.Pipeline | None" = None
_lock = threading.Lock()


def _get_pipeline() -> "stanza.Pipeline":
    global _nlp
    if _nlp is not None:
        return _nlp
    with _lock:
        if _nlp is not None:
            return _nlp
        import stanza

        resources_dir = get_settings().stanza_resources_dir
        os.makedirs(resources_dir, exist_ok=True)

        if not os.path.exists(os.path.join(resources_dir, "en")):
            # Первый запуск на этом volume — модели ещё нет, качаем один раз.
            stanza.download("en", model_dir=resources_dir)

        _nlp = stanza.Pipeline(
            "en",
            processors="tokenize,mwt,pos,lemma",
            tokenize_no_ssplit=True,
            model_dir=resources_dir,
            download_method=None,
        )
        return _nlp


def lemmatize_en(text: str) -> str:
    nlp = _get_pipeline()
    doc = nlp(text)
    lemmas = [word.lemma or word.text for sentence in doc.sentences for word in sentence.words]
    return " ".join(lemmas) if lemmas else text
