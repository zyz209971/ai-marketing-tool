FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_SKIP_DOTENV=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app /app/backend/app
COPY backend/scripts /app/backend/scripts
COPY frontend/agent.html frontend/index.html frontend/login.html /app/frontend/
COPY frontend/src /app/frontend/src
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/brand-files && chown -R appuser:appuser /data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python","backend/scripts/run_deployment.py"]
