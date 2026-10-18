FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Shanghai
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/tests ./tests
COPY evals /evals
COPY backend/knowledge_worker.py ./knowledge_worker.py
COPY infra/docker /opt/deploy
RUN mkdir -p /app/data/agent /app/data/knowledge /app/uploads
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
