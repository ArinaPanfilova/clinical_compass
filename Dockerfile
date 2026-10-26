# Компас: один образ — интерфейс + API. Запуск: docker run -p 8000:8000 kompas
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir pyyaml==6.0.3 fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1
COPY kompas_core/ kompas_core/
COPY server/ server/
COPY synthetic/ synthetic/
COPY --from=web /app/frontend/dist frontend/dist
ENV KOMPAS_DB=/data/kompas.db KOMPAS_WORKERS=4
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "server"]
