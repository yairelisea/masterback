# URL Analyzer - Analizador de Percepción Digital

## Descripción

El URL Analyzer es un módulo integrado que permite analizar URLs de campañas políticas para evaluar:
- Sentimiento (positivo, neutral, negativo)
- Toxicidad (0-100)
- Postura (a favor, neutral, en contra, ninguna)
- Temas y subtemas
- Entidades mencionadas
- Oportunidades políticas

## Características

✅ **Implementado:**
- Router `/url-analyzer` con endpoints de análisis
- Schemas para requests y responses
- Restricción de acceso solo para admins
- Endpoint para obtener URLs de una campaña
- Endpoint para analizar URLs con detección de plataforma

⚠️ **Pendiente de integración:**
- Servicios de `fetcher` para extraer contenido de URLs
- Servicios de `perplexity` para análisis de IA
- Generación de PDFs con reportes
- Cache de análisis previos

## Endpoints disponibles

### 1. Health Check
```
GET /url-analyzer/health
```
Verifica el estado del servicio.

**Response:**
```json
{
  "ok": true,
  "service": "URL Analyzer",
  "status": "active"
}
```

### 2. Obtener URLs de una campaña
```
GET /url-analyzer/campaign/{campaign_id}/urls
```
Obtiene todas las URLs asociadas a una campaña para análisis.

**Requiere:** Admin access

**Response:**
```json
{
  "campaign_id": "abc123",
  "campaign_name": "Campaña Electoral 2024",
  "total_urls": 45,
  "urls": [
    {
      "url": "https://example.com/noticia1",
      "title": "Título de la noticia"
    }
  ]
}
```

### 3. Analizar URLs
```
POST /url-analyzer/analyze
```
Analiza un conjunto de URLs para percepción política.

**Requiere:** Admin access

**Request Body:**
```json
{
  "urls": [
    "https://facebook.com/post1",
    "https://twitter.com/user/status/123",
    "https://news.com/article"
  ],
  "politician": {
    "name": "Juan Pérez",
    "office": "Alcalde"
  }
}
```

**Response:**
```json
{
  "politician": {
    "name": "Juan Pérez",
    "office": "Alcalde"
  },
  "results": [
    {
      "meta": {
        "platform": "facebook",
        "url": "https://facebook.com/post1",
        "title": "Post title",
        "description": "Post description",
        "author_name": "Usuario",
        "published_at": "2024-01-15",
        "likes": 150,
        "shares": 20,
        "comments": 10
      },
      "ai": {
        "summary": "Resumen del contenido",
        "topic": "Tema principal",
        "subtopics": ["subtema1", "subtema2"],
        "sentiment": "positive",
        "stance": "favor",
        "entities": ["Juan Pérez", "Partido X"],
        "toxicity": 15,
        "risk_note": "Nota sobre riesgos",
        "opportunities": ["Oportunidad 1", "Oportunidad 2"]
      }
    }
  ],
  "summary": {
    "total": 3,
    "sentiments": {
      "positive": 2,
      "negative": 1
    },
    "predominant": "positive",
    "stances": {
      "favor": 2,
      "neutral": 1
    },
    "top_entities": [
      "Juan Pérez (3)",
      "Partido X (2)"
    ],
    "short_text": "Resumen ejecutivo narrativo..."
  },
  "metadata": {
    "total_urls": 3,
    "successful_analyses": 3
  }
}
```

## Configuración

Variables de entorno disponibles:

```env
MAX_CONCURRENCY=5          # Número máximo de URLs a procesar en paralelo
PER_URL_DEADLINE=20        # Timeout en segundos por URL
MIN_URLS=5                 # Número mínimo de URLs requeridas para análisis
```

## Integración con Frontend

### En el listado de campañas (Admin Layout):

1. Agregar un botón "Analizar URLs" en cada tarjeta de campaña
2. Al hacer clic, navegar a `/analizador?campaign_id={id}`
3. En la página del analizador:
   - Cargar las URLs disponibles: `GET /url-analyzer/campaign/{id}/urls`
   - Mostrar formulario para seleccionar URLs y nombre del político
   - Enviar análisis: `POST /url-analyzer/analyze`
   - Mostrar resultados con gráficas de sentimiento, toxicidad, etc.

### Ejemplo de implementación React:

```jsx
// En el componente de listado de campañas
<Button
  onClick={() => navigate(`/analizador?campaign_id=${campaign.id}`)}
  disabled={!user?.isAdmin}
>
  Analizar URLs
</Button>

// En la página del analizador
const { campaign_id } = useParams();

// Cargar URLs
const { data: urlsData } = useQuery(
  ['campaign-urls', campaign_id],
  () => api.get(`/url-analyzer/campaign/${campaign_id}/urls`)
);

// Analizar
const analyzeMutation = useMutation(
  (data) => api.post('/url-analyzer/analyze', data),
  {
    onSuccess: (result) => {
      // Mostrar resultados con gráficas
    }
  }
);
```

## Próximos pasos de desarrollo

### 1. Integrar servicios de extracción de contenido

Necesitas crear o integrar el servicio `fetcher` que extraiga contenido de URLs:

```python
# app/services/fetcher.py
async def fetch_page(url: str) -> dict:
    """
    Extrae contenido de una URL.
    Returns:
        {
            "url": str,
            "title": str,
            "description": str,
            "text": str,
            "image": str,
            "author_name": str,
            "published_at": str,
            "engagement": {
                "likes": int,
                "shares": int,
                "comments": int
            }
        }
    """
    # Implementar extracción con:
    # - BeautifulSoup para HTML
    # - Playwright para JavaScript rendering
    # - APIs oficiales para redes sociales (Facebook, Twitter, etc.)
    pass
```

### 2. Integrar análisis con IA

El código del FastAPI externo usa Perplexity. Necesitas integrar:

```python
# app/services/perplexity.py o similar
def analyze_text(text: str) -> dict:
    """
    Analiza texto con IA.
    Returns:
        {
            "summary": str,
            "topic": str,
            "subtopics": List[str],
            "sentiment": int,  # -1, 0, 1
            "stance": str,  # "against", "neutral", "favor", "none"
            "entities": List[str],
            "toxicity": int,  # 0-100
            "risk_note": str,
            "opportunities": List[str]
        }
    """
    pass

def analyze_facebook_url(url: str, politician_name: str, basic_info: dict) -> dict:
    """Análisis específico para URLs de Facebook usando búsqueda"""
    pass
```

### 3. Agregar generación de PDFs

```python
# En url_analyzer.py
@router.post("/analyze-pdf")
async def analyze_urls_pdf(req: AnalyzeURLRequest, ...):
    """Genera PDF con el análisis"""
    results = await _analyze_all(req)
    # Generar HTML y convertir a PDF con WeasyPrint
    # ...
```

### 4. Implementar cache en base de datos

Guardar resultados de análisis para evitar reprocesar:

```python
# Crear modelo AnalysisCache
class URLAnalysisCache(Base):
    __tablename__ = "url_analysis_cache"

    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    politician_name: Mapped[str] = mapped_column(String(200))
    analysis_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
```

## Seguridad

- ✅ Todos los endpoints requieren autenticación
- ✅ Solo usuarios con `isAdmin=true` pueden acceder
- ✅ URLs sanitizadas antes de procesar
- ✅ Límite de URLs procesadas simultáneamente
- ✅ Timeout por URL para evitar bloqueos

## Testing

Para probar el endpoint:

```bash
# Health check
curl http://localhost:8000/url-analyzer/health

# Obtener URLs de campaña (requiere token de admin)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/url-analyzer/campaign/abc123/urls

# Analizar URLs (requiere token de admin)
curl -X POST http://localhost:8000/url-analyzer/analyze \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com/news1", "https://example.com/news2"],
    "politician": {"name": "Juan Pérez", "office": "Alcalde"}
  }'
```

## Notas

- El analizador actualmente retorna datos simulados hasta que se integren los servicios reales
- Se recomienda implementar rate limiting para evitar abuso
- Considerar costos de APIs de IA (Perplexity, OpenAI, etc.)
- Para Facebook/Instagram, se requieren APIs oficiales o scraping autorizado
