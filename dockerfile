# Usamos Python 3.11 para evitar problemas de compatibilidad
FROM python:3.11-slim

# Ajustes básicos
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Crear directorio de la app
WORKDIR /app

# Paquetes del sistema necesarios para algunas wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Copiar el código
COPY . .

# Puerto (solo informativo)
EXPOSE 8000

# Arranque de la app (Render usa $PORT; local usará 8000 por defecto)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]