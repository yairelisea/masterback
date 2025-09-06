# Python 3.11 slim (Debian)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ---- Dependencias del SO necesarias para Playwright/Chromium y fuentes ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    # Fuentes (equivalentes válidas en Debian)
    fonts-unifont fonts-dejavu-core fonts-liberation \
    # Libs de runtime que exige Chromium/Playwright
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxdamage1 libxfixes3 libxcomposite1 libxrandr2 \
    libgbm1 libxkbcommon0 libasound2 libxshmfence1 libx11-6 libx11-xcb1 \
    libxcb1 libxext6 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---- Python deps ----
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# ---- Instalar navegadores de Playwright ----
# Ya instalaste las dependencias del SO arriba, así que basta con:
RUN playwright install chromium

# ---- Copia código ----
COPY . .

# ---- Exponer puerto y arrancar ----
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]