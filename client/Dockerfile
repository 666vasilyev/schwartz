FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY client/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir pip -U && pip install --no-cache-dir -r /tmp/requirements.txt

COPY client/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
