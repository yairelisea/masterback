#!/usr/bin/env bash
set -e

# Corre las migraciones de la base de datos
echo "Corriendo migraciones de la base de datos..."
alembic upgrade head
echo "Migraciones completadas."

# Inicia la aplicación
export $(grep -v '^#' .env | xargs) || true
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
