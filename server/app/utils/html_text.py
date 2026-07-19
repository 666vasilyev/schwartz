"""
HTML → читаемый текст, страховка на сервере для полей из внешних источников
(RSS summary/content и т.п.).

Дублирует client/app/utils/html_text.py: клиент-сборщик уже прогоняет RSS через
такую же очистку перед отправкой на сервер, но это отдельный деплой (client —
намеренно лёгкий сервис без общих модулей с server), плюс сервер может получать
данные и из более старых версий клиента. Поэтому сервер подчищает текст ещё раз
перед сохранением поста — идемпотентно (на уже чистом тексте ничего не меняет).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "table", "ul", "ol",
}


class _TextExtractor(HTMLParser):
    """Собирает текстовые узлы; на границах блочных тегов вставляет перенос строки."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


# \xa0 — неразрывный пробел, часто встречается в HTML-вёрстке (&nbsp;),
# html.parser его не трогает при convert_charrefs, поэтому схлопываем сами.
_INLINE_WS_RE = re.compile(r"[ \t\xa0]+")


def strip_html(raw: str | None) -> str | None:
    """
    Убрать HTML-разметку, оставив читаемый текст с переносами строк на месте
    блочных элементов. Пустая строка/None → None.

    Если в строке нет ни одного '<' и '>' — она не похожа на HTML, возвращаем
    как есть без парсинга (чтобы не задеть обычный текст, где '<' встретился
    не как часть тега, например в математической записи).
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "<" not in text or ">" not in text:
        return text

    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        # Битая/нестандартная разметка — не роняем сохранение поста, отдаём исходный текст.
        return text

    extracted = parser.get_text()
    extracted = _INLINE_WS_RE.sub(" ", extracted)
    lines = [line.strip() for line in extracted.split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip() or None
