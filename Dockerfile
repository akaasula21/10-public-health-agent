FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOOGLE_GENAI_USE_VERTEXAI=True \
    GOOGLE_CLOUD_PROJECT=qwiklabs-gcp-03-c81d344a3430 \
    GOOGLE_CLOUD_LOCATION=us-central1 \
    ADK_PRO_MODEL=gemini-2.5-pro \
    ADK_FLYER_MODEL=gemini-2.5-flash \
    ADK_MODEL=gemini-2.5-flash \
    GCS_FLYER_BUCKET=qwiklabs-gcp-03-c81d344a3430-flyers

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY api/ ./api/
COPY db/ ./db/
COPY data/ ./data/
COPY static/ ./static/

EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
