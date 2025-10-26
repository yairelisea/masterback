#!/usr/bin/env bash

echo "--- DEBUGGING DATABASE_URL ---"
echo "La DATABASE_URL que la aplicación está usando es: $DATABASE_URL"
echo "--- FIN DEL DEBUG ---"

# Salimos con un error para detener el despliegue y poder revisar los logs.
exit 1