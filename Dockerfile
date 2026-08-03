FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    freetds-dev \
    freetds-bin \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV DB_LOGIN_TIMEOUT=15
ENV DB_QUERY_TIMEOUT=30

# Fail fast with a clear import error in Cloud Run logs if bootstrapping crashes.
CMD ["sh", "-c", "python -c 'import main; print(\"main import ok\")' && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --log-level info"]
