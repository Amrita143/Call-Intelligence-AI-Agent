FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code
COPY backend ./backend
COPY frontend ./frontend

EXPOSE 8000
# .env is passed at runtime via docker-compose / --env-file (never baked into the image).
# Shell form so ${PORT} is honored — hosts like Render / Railway / HF Spaces inject a port.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir backend
