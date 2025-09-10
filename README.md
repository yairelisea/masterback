# BBX Backend (Express + TypeScript + Prisma + SQLite)

Backend listo para conectarse con el FrontEnd de BBX. Incluye:
- Campañas con búsqueda de noticias (Google News RSS)
- Agregar enlaces de redes sociales/manuales y analizarlos
- Análisis con OpenAI (opcional; tiene fallback básico)
- Programador diario para refrescar campañas
- SQLite + Prisma
- Dockerfile y docker-compose
- Rutas con JSON limpias para consumir desde el front

## Endpoints

- `GET /api/health` – ping
- `GET /api/campaigns?q=&page=&limit=` – listar campañas
- `POST /api/campaigns` – crear campaña y poblarla con noticias
```json
{
  "name": "Olga Sosa",
  "query": "Olga Sosa senadora",
  "socials": ["https://twitter.com/...", "https://facebook.com/..."]
}
```
- `GET /api/campaigns/:id` – detalle (artículos y enlaces)
- `POST /api/campaigns/:id/refresh` – volver a buscar y analizar
- `POST /api/search` – buscar noticias sin guardar
```json
{ "query": "Ricardo Monreal", "maxResults": 25, "days": 7 }
```
- `POST /api/links/add` – agregar y analizar URLs a una campaña
```json
{ "campaignId": "<id>", "urls": ["https://x.com/..."] }
```

## Variables de entorno
Copia `.env.example` a `.env` y ajusta:
```
DATABASE_URL="file:./dev.db"
PORT=8080
CORS_ORIGIN=http://localhost:5173
OPENAI_API_KEY=sk-...  # opcional
NEWS_MAX_RESULTS=35
DEFAULT_NEWS_WINDOW_DAYS=7
TIMEZONE=America/Monterrey
```

## Desarrollo
```bash
npm i
npx prisma generate
npx prisma migrate dev --name init
npm run dev
```

## Docker
```bash
docker build -t bbx-backend .
docker run -p 8080:8080 --env-file .env bbx-backend
# o
docker compose up --build
```

## Despliegue rápido en Render
1. Nuevo servicio Web → Runtime Node 20
2. Build command: `npx prisma generate && npm run build`
3. Start command: `node dist/index.js`
4. Agregar variables del archivo `.env`

## Notas legales / scraping
Se usa **solo** el feed público de Google News (RSS). Para redes sociales y otros enlaces, se hace *fetch* del HTML para leer metadatos OpenGraph/Twitter (título/descripcion/imagen); evita scraping de datos personales o secciones que violen TOS. Ajusta según tus políticas.

## Adaptar al Front
Si tu front apunta a `/api/campaigns`, `/api/links/add` y `/api/search`, no necesitas cambios. Si usas rutas distintas, edítalas en `src/index.ts` y `src/routes/*`.

## Licencia
MIT
