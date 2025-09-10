# ==== Node deps (opcional) ====
FROM node:20-alpine AS deps
WORKDIR /app

# Copia solo si existen; el patrón package*.json permite que falte package-lock.json
# Si NO hay package.json, el build fallaría; por eso copiamos y luego instalamos de forma condicional
COPY package*.json . 2>/dev/null || true
COPY pnpm-lock.yaml . 2>/dev/null || true
COPY yarn.lock . 2>/dev/null || true
COPY .npmrc . 2>/dev/null || true

# Instala solo si hay package.json
RUN if [ -f package.json ]; then npm i --no-audit --no-fund; fi

# ==== Python backend ====
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Si necesitas artefactos de Node (build) entonces:
# COPY --from=deps /app/node_modules ./node_modules
# COPY cualquier fuente Node necesaria y haz tu build si aplica

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]