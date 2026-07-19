"""
Общая частотная логика для лемм по произвольному набору текстов постов.

Используется в двух местах, которым нужна одна и та же токенизация/фильтрация,
чтобы они не разъезжались со временем:
  - use_case/clusters/_trending_common.py — "new_lemmas" на каждый трендовый
    кластер в /clusters/trending (простой список самых частых слов, без
    сопоставления по неделям);
  - use_case/analyze/lemma_trend_candidates.py — еженедельный поиск
    кандидатных лемм ("эмпирические леммы"), где top-N считается на каждую
    неделю отдельно, а затем недели сопоставляются друг с другом.
"""
from __future__ import annotations

import re
from collections import Counter

from app.application.services.content.lemma_scorer import LemmaLang, clean_lemma, is_blacklisted

_WORD_RE = re.compile(r"\w+")
# Отсекаем 1-2-буквенные "слова" (в основном предлоги/союзы: "и", "в", "на", "к")
# без отдельного словаря стоп-слов — более тонкая фильтрация делается через
# чёрный список лемм (см. /lemma/blacklist).
_MIN_WORD_LEN = 3


def word_frequency(texts: list[str]) -> Counter:
    """Частота слов (после _clean_lemma) по всем текстам, без фильтрации."""
    counts: Counter = Counter()
    for text in texts:
        if not text:
            continue
        for word in _WORD_RE.findall(text.lower()):
            if len(word) < _MIN_WORD_LEN:
                continue
            key = clean_lemma(word)
            if key:
                counts[key] += 1
    return counts


def top_frequent_lemmas(
    texts: list[str], lang: LemmaLang, top_n: int
) -> list[tuple[str, int]]:
    """
    (лемма, частота) по убыванию частоты (при равенстве — по алфавиту),
    леммы из чёрного словаря `lang` исключены целиком.
    """
    counts = word_frequency(texts)
    filtered = {word: cnt for word, cnt in counts.items() if not is_blacklisted(word, lang)}
    ranked = sorted(filtered.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:top_n]
