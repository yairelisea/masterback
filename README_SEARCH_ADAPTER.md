# Search Adapter

Servicio unificado de búsqueda que utiliza Google Programmable Search (Custom Search JSON API) como fuente principal y un stub opcional para Facebook.

## Variables de entorno

Definir en tu entorno (ej. .env local, Render, etc.):

- `GOOGLE_SEARCH_API_KEY` Clave de la API de Google Custom Search JSON.
- `GOOGLE_SEARCH_CX` ID (cx) del motor de búsqueda programable.
- `FACEBOOK_GRAPH_TOKEN` (Opcional) Token para futuras integraciones con Facebook Graph.

Si faltan `GOOGLE_SEARCH_API_KEY` o `GOOGLE_SEARCH_CX`, el servicio simplemente devolverá resultados vacíos para Google y mostrará un warning.

## Archivo de configuración
`src/config/searchConfig.js` centraliza la lectura de variables de entorno y valores por defecto.

## API del servicio

```
const { unifiedSearch } = require('./src/services/searchAdapter');

const results = await unifiedSearch('open source ai', {
  sources: ['google', 'facebook'], // default ['google']
  timeoutMs: 8000,                 // default 10000
});
```

Cada elemento del array devuelto tiene la forma:
```
{
  source: 'google' | 'facebook',
  title: string,
  url: string,
  snippet: string,
  publishedAt: ISODateString
}
```

La deduplicación se realiza por URL (case-insensitive) conservando la primera aparición. El orden final es descendente por `publishedAt`.

## Tests

Archivo: `tests/searchAdapter.test.js` (Jest). Mockea `node-fetch` para simular la respuesta de Google y verifica:
- Normalización
- Deduplicación por URL
- Manejo de fuentes opcionales

## Extender Facebook
Reemplazar el stub `facebookSearch` en `src/services/searchAdapter.js` con llamadas reales al Graph API y normalizar al mismo formato.

## Notas
- Asegúrate de instalar `node-fetch` (v2.x si usas CommonJS) y Jest en el proyecto si aún no están presentes.
- Limitar uso de la API de Google para evitar sobrepasar cuotas.
