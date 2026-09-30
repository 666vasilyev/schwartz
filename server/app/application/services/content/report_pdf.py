"""
Рендер отчёта по выборке постов (PostReportData) в PDF через reportlab — см.
post_report.py (данные) и use_case/posts/summary_report.py (вызывающая ручка,
POST /api/v1/posts/summary/report?fmt=pdf).

ВАЖНО про кириллицу: встроенные 14 PDF-шрифтов reportlab (Helvetica и т.п.)
кириллицу не поддерживают вообще — без регистрации TTF-шрифта текст будет
пустым/битым. Шрифт DejaVu Sans (есть кириллица, свободная лицензия) ставится
в образ через apt (см. server/Dockerfile: fonts-dejavu-core) и регистрируется
здесь по стандартному пути Debian. Если файла почему-то нет на диске —
откатываемся на Helvetica с предупреждением в логах (кириллица не отобразится,
но PDF хотя бы сгенерируется, а не упадёт с ошибкой).
"""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.application.services.content.post_report import PostReportData
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEJAVU_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_DEJAVU_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_SOURCE_TYPE_LABELS = {"vk": "VK", "rss": "RSS", "telegram": "Telegram"}

_registered = False


def _ensure_fonts() -> tuple[str, str]:
    global _registered
    if _registered:
        return "DejaVuSans", "DejaVuSans-Bold"
    if _DEJAVU_REGULAR.is_file() and _DEJAVU_BOLD.is_file():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(_DEJAVU_REGULAR)))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(_DEJAVU_BOLD)))
        _registered = True
        return "DejaVuSans", "DejaVuSans-Bold"
    logger.warning("dejavu_font_missing", path=str(_DEJAVU_REGULAR))
    return "Helvetica", "Helvetica-Bold"


def _table(rows: list[list], font: str, font_bold: str, *, col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                ("FONTNAME", (0, 1), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def render_report_pdf(data: PostReportData) -> bytes:
    font, font_bold = _ensure_fonts()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCyr", parent=styles["Title"], fontName=font_bold)
    h1 = ParagraphStyle("H1Cyr", parent=styles["Heading1"], fontName=font_bold)
    normal = ParagraphStyle("NormalCyr", parent=styles["Normal"], fontName=font, fontSize=10, leading=14)
    small = ParagraphStyle("SmallCyr", parent=normal, fontSize=8, textColor=colors.grey)

    story = []
    story.append(Paragraph(_esc(data.title or "Отчёт по выборке новостей"), title_style))

    meta_text = (
        f"Сгенерировано: {data.generated_at:%d.%m.%Y %H:%M} UTC &#183; "
        f"Постов в выборке: {data.posts_requested} &#183; "
        f"Учтено в аналитике (с текстом): {data.posts_used} &#183; "
        f"Словарь ЦКМ: {_esc(data.lang.value)}"
    )
    story.append(Paragraph(meta_text, small))
    if data.missing_post_ids:
        story.append(
            Paragraph("Не найдены в базе: " + _esc(", ".join(str(i) for i in data.missing_post_ids)), small)
        )
    story.append(Spacer(1, 0.5 * cm))

    if data.summary:
        story.append(Paragraph("Саммари", h1))
        story.append(Paragraph(_esc(data.summary), normal))
        if data.topics:
            story.append(Paragraph("<b>Темы:</b> " + _esc(", ".join(data.topics)), normal))
        story.append(Spacer(1, 0.5 * cm))

    if data.schwartz:
        story.append(Paragraph("ЦКМ-аналитика (агрегат по выборке)", h1))
        rows: list[list] = [["Параметр", "Доля"]]
        for param, value in sorted(data.schwartz.items(), key=lambda kv: -kv[1]):
            rows.append([param, f"{value * 100:.1f}%"])
        story.append(_table(rows, font, font_bold, col_widths=[11 * cm, 3 * cm]))
        story.append(Spacer(1, 0.5 * cm))

    if data.categories:
        story.append(Paragraph("Категории лемм (топ по выборке)", h1))
        rows = [["Категория", "Доля"]]
        for cat, value in list(data.categories.items())[:10]:
            rows.append([cat, f"{value * 100:.1f}%"])
        story.append(_table(rows, font, font_bold, col_widths=[11 * cm, 3 * cm]))
        story.append(Spacer(1, 0.5 * cm))

    if data.posts:
        story.append(Paragraph("Посты в выборке", h1))
        rows = [["ID", "Источник", "Тип", "Дата", "Текст / ссылка"]]
        for item in data.posts:
            date_str = f"{item.published_at:%d.%m.%Y %H:%M}" if item.published_at else "—"
            text_html = _esc(item.text_snippet or "(текст отсутствует)")
            if item.url:
                text_html += f'<br/><font size="7" color="grey">{_esc(item.url)}</font>'
            rows.append(
                [
                    str(item.id),
                    item.source_name or "—",
                    _SOURCE_TYPE_LABELS.get(item.source_type or "", item.source_type or "—"),
                    date_str,
                    Paragraph(text_html, normal),
                ]
            )
        story.append(
            _table(rows, font, font_bold, col_widths=[1.3 * cm, 3 * cm, 1.8 * cm, 2.6 * cm, 5.3 * cm])
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    doc.build(story)
    return buf.getvalue()
