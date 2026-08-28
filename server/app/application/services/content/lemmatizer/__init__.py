"""
Лемматизация новых лемм перед сохранением в словарь — приводит слово/фразу к
начальной форме тем же стеком, что и в референсных ноутбуках (без словарей
исключений и без учёта синтаксического контекста предложения — работаем на
изолированном слове/словосочетании, как оно приходит в append/extract/
trend-candidates, а не на целом тексте):

  - ru, ru_un, ru_ch — spaCy ru_core_news_sm (см. lemmatizer/ru.py)
  - usa, usa_un, usa_ch — Stanza (en) (см. lemmatizer/en.py)
  - frg — spaCy de_core_news_sm + germalemma (см. lemmatizer/de.py)

ru_merged/usa_merged — вычисляемые словари, лемм в них напрямую не пишут
(см. MergedLangNotWritableError в lemma_scorer.append_lemmas), поэтому для
них лемматизация не требуется — текст возвращается как есть.

Модели грузятся лениво, синглтоном на процесс — тот же паттерн, что и в
embedder.py для sentence-transformers.
"""
from __future__ import annotations

from app.application.services.content.lemma_scorer import LemmaLang


def lemmatize(text: str, lang: LemmaLang) -> str:
    """Лемматизировать слово/словосочетание для словаря `lang`. Пустая строка/None — без изменений."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text

    if lang in (LemmaLang.ru, LemmaLang.ru_un, LemmaLang.ru_ch):
        from app.application.services.content.lemmatizer.ru import lemmatize_ru

        return lemmatize_ru(stripped)
    if lang in (LemmaLang.usa, LemmaLang.usa_un, LemmaLang.usa_ch):
        from app.application.services.content.lemmatizer.en import lemmatize_en

        return lemmatize_en(stripped)
    if lang == LemmaLang.frg:
        from app.application.services.content.lemmatizer.de import lemmatize_de

        return lemmatize_de(stripped)

    # ru_merged / usa_merged — вычисляемые, не пишутся напрямую
    return stripped
