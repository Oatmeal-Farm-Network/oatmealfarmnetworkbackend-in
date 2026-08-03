# Dockerfile for HITL-AG-AGENT-BACKEND
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./

# Expose port (Cloud Run injects PORT at runtime, defaulting to 8080; falls
# back to 8000 for local `docker run` without -e PORT=...)
EXPOSE 8080
ENV PORT=8080

# Command to run the application — must bind to $PORT for Cloud Run, since
# Cloud Run always routes traffic to whatever port it assigns via $PORT.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]

