FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Paquetes del SO necesarios (incluye fuentes correctas en Debian)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential \
    # Fuentes y libs que Playwright necesita
    fonts-unifont fonts-ubuntu fonts-liberation \
    libnss3 libxss1 libatk-bridge2.0-0 libgtk-3-0 libdrm2 libxkbcommon0 \
    libasound2 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 libxshmfence1 libx11-xcb1 \
    libxcb-dri3-0 libxfixes3 libxrender1 libxi6 libxext6 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Instala dependencias Python (incluye playwright en requirements.txt)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Descarga Chromium para la versión instalada de Playwright
RUN python -m playwright install chromium

# Copia el código
COPY . .

EXPOSE 8000
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]