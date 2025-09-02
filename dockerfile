# Usamos Python 3.11 para evitar problemas de compatibilidad
FROM python:3.11-slim

# No escribir .pyc y logs line-buffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Carpeta de trabajo
WORKDIR /app

# Paquetes mínimos para algunas wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Instalar deps
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Copiar el código de la app
COPY . .

# Puerto interno
EXPOSE 8000

# Comando de arranque (Render inyecta $PORT; local usará 8000)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]