# Dockerfile (backend)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Paquetes base útiles (build + certificados + algunas fuentes legibles en PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    fonts-liberation \
    fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

# ---- Dependencias Python ----
# (1) Copiamos SOLO requirements y los instalamos
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# (2) Instalar Chromium de Playwright (usa la versión instalada por pip)
#     --with-deps trae todas las libs del SO necesarias
RUN python -m playwright install --with-deps chromium

# ---- Copia del proyecto ----
COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]