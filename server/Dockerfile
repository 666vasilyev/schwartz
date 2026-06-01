FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY server/requirements.txt .
RUN pip install --no-cache-dir pip -U && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY server/start.sh ./server/start.sh
COPY server/app ./server/app
COPY server/lemma ./server/lemma

RUN sed -i 's/\r$//' ./server/start.sh && chmod +x ./server/start.sh

EXPOSE 8000
CMD ["/app/server/start.sh"]
