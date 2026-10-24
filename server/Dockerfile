FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# fonts-dejavu-core — кириллический TTF-шрифт для генерации PDF-отчётов
# (reportlab, см. app/application/services/content/report_pdf.py); встроенные
# PDF-шрифты reportlab кириллицу не поддерживают вообще.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir pip -U && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY server/start.sh ./server/start.sh
COPY server/app ./server/app
COPY server/lemma ./server/lemma
COPY server/prompts ./server/prompts

RUN sed -i 's/\r$//' ./server/start.sh && chmod +x ./server/start.sh

EXPOSE 8000
CMD ["/app/server/start.sh"]
