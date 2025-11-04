from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from perplexity import AsyncPerplexity, PerplexityError

# ============================================================================
# CONFIGURACIÓN DE MEDIOS LOCALES PRIORITARIOS
# ============================================================================
MEDIOS_LOCALES_TAMPICO = [
    "soldetampico.com.mx",
    "elsoldeltampico.com",
    "milenio.com",
    "telediario.mx",
    "expreso.press",
    "expresopress.com",
    "hoytamaulipas.net",
    "laverdaddetamaulipas.com",
    "elpulsodetampico.com"
]

BOOST_MEDIOS_LOCALES = 1.5  # Multiplicador de score para medios locales


def to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
    """Convierte fechas al formato MM/DD/YYYY requerido por Perplexity."""
    if not date_str:
        return None
    if re.match(r"\d{2}/\d{2}/\d{4}$", date_str):
        return date_str
    if re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
        except Exception as e:
            print(f"Error formateando la fecha '{date_str}': {e}")
            return None
    print(f"Formato de fecha no reconocido: '{date_str}'")
    return None


async def _get_url_content(url: str) -> str:
    """Obtiene el contenido de texto de una URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"Error al obtener contenido de {url}: {e}")
        return ""


def es_medio_local(url: str) -> bool:
    """Determina si una URL pertenece a un medio local prioritario."""
    url_lower = url.lower()
    return any(medio in url_lower for medio in MEDIOS_LOCALES_TAMPICO)


def calcular_score_relevancia(result: Any, campaign_name: str, boost_local: bool = True) -> float:
    """
    Calcula un score de relevancia basado en:
    - Presencia del campaign_name en título/snippet
    - Si es medio local (boost)
    """
    score = 0.0
    
    # Boost por campaign_name en título
    if campaign_name.lower() in result.title.lower():
        score += 2.0
    
    # Boost por campaign_name en snippet
    if hasattr(result, 'snippet') and result.snippet:
        if campaign_name.lower() in result.snippet.lower():
            score += 1.0
    
    # BOOST ADICIONAL para medios locales
    if boost_local and es_medio_local(result.url):
        score *= BOOST_MEDIOS_LOCALES
        print(f"✅ MEDIO LOCAL detectado: {result.url} - Score boosted!")
    
    return score


class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        priorizar_medios_locales: bool = True
    ) -> List[Dict[str, Any]]:
        """
        BÚSQUEDA ITERATIVA con priorización de medios locales.
        
        Estrategia:
        1. Búsqueda general con scoring
        2. Si pocos resultados, búsqueda adicional EN medios locales específicos
        3. Intenta hasta encontrar mínimo 3 resultados relevantes
        """
        print(f"🔍 Búsqueda ITERATIVA con MEDIOS LOCALES para: {campaign_name}")
        print(f"   Query: {query}")
        print(f"   Priorizar medios locales: {priorizar_medios_locales}")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        analyzed_articles = []
        intentos = [
            {"max_results": 20, "threshold": 2.0, "nombre": "ESTRICTO"},
            {"max_results": 30, "threshold": 1.5, "nombre": "MEDIO"},
            {"max_results": 50, "threshold": 1.0, "nombre": "RELAJADO"}
        ]

        for i, config in enumerate(intentos, 1):
            print(f"\n{'='*60}")
            print(f"🔄 INTENTO {i}/3 - Modo {config['nombre']}")
            print(f"   Max resultados: {config['max_results']}, Umbral: {config['threshold']}")
            print(f"{'='*60}\n")

            try:
                # === BÚSQUEDA GENERAL ===
                search_params = {
                    "query": query,
                    "max_results": config["max_results"],
                }
                if formatted_start:
                    search_params["search_after_date_filter"] = formatted_start
                if formatted_end:
                    search_params["search_before_date_filter"] = formatted_end

                search_results = await self.client.search.create(**search_params)
                
                # Calcular scores y filtrar
                scored_results = []
                for result in search_results.results:
                    score = calcular_score_relevancia(result, campaign_name, boost_local=priorizar_medios_locales)
                    scored_results.append((result, score))
                
                # Ordenar por score descendente
                scored_results.sort(key=lambda x: x[1], reverse=True)
                
                # Filtrar por umbral
                filtered_results = [
                    (result, score) for result, score in scored_results 
                    if score >= config["threshold"]
                ]
                
                print(f"📊 Resultados encontrados: {len(search_results.results)}")
                print(f"✅ Resultados relevantes (score >= {config['threshold']}): {len(filtered_results)}")
                
                if priorizar_medios_locales:
                    medios_locales_count = sum(1 for result, _ in filtered_results if es_medio_local(result.url))
                    print(f"🏠 De medios locales: {medios_locales_count}")

                # Analizar artículos filtrados
                for result, score in filtered_results[:15]:  # Máximo 15 para no saturar
                    print(f"\n📄 Analizando: {result.title[:80]}...")
                    print(f"   URL: {result.url}")
                    print(f"   Score: {score:.2f}")
                    if es_medio_local(result.url):
                        print(f"   🏠 MEDIO LOCAL ⭐")

                    content = await _get_url_content(result.url)
                    if not content:
                        continue

                    analysis_prompt = f"""
Analiza el siguiente texto sobre política mexicana.
Si '{campaign_name}' NO tiene relevancia, responde solo {{}}
Si SÍ es relevante, responde con este objeto JSON:
- summary: resumen conciso (2-3 frases)
- sentiment_label: 'Positivo', 'Negativo' o 'Neutral'
- sentiment_score: de -1.0 a 1.0
- topics: 3-5 temas principales
- key_points: 2-3 citas o puntos clave

Texto:
{content[:4000]}

Responde solo con el objeto JSON.
"""

                    try:
                        chat_response = await self.client.chat.completions.create(
                            model="sonar-reasoning",
                            messages=[
                                {"role": "system", "content": "Eres un analista de medios que responde solo con objetos JSON definidos por el usuario."},
                                {"role": "user", "content": analysis_prompt},
                            ],
                            response_format={
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "news_analysis",
                                    "strict": True,
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "summary": {"type": "string"},
                                            "sentiment_label": {"type": "string"},
                                            "sentiment_score": {"type": "number"},
                                            "topics": {"type": "array", "items": {"type": "string"}},
                                            "key_points": {"type": "array", "items": {"type": "string"}},
                                        },
                                        "required": ["summary", "sentiment_label", "sentiment_score", "topics", "key_points"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                        )

                        analysis_content = chat_response.choices[0].message.content
                        analysis_json = json.loads(analysis_content)

                        # Solo agregar si tiene contenido relevante
                        if analysis_json and analysis_json.get("summary"):
                            analyzed_articles.append({
                                "title": result.title,
                                "url": result.url,
                                "publishedAt": getattr(result, 'published_date', None),
                                "summary": analysis_json.get("summary", ""),
                                "sentiment_label": analysis_json.get("sentiment_label", "Neutral"),
                                "sentiment_score": analysis_json.get("sentiment_score", 0.0),
                                "topics": analysis_json.get("topics", []),
                                "key_points": analysis_json.get("key_points", []),
                                "relevance_score": score,
                                "es_medio_local": es_medio_local(result.url)
                            })
                            print(f"   ✅ Artículo relevante agregado (Total: {len(analyzed_articles)})")

                    except Exception as e:
                        print(f"   ❌ Error al analizar: {e}")
                        continue

                # === BÚSQUEDA ADICIONAL EN MEDIOS LOCALES ===
                if priorizar_medios_locales and len(analyzed_articles) < 3 and i == 1:
                    print(f"\n🏠 Búsqueda ADICIONAL en medios locales específicos...")
                    
                    for medio in MEDIOS_LOCALES_TAMPICO[:3]:  # Primeros 3 medios
                        query_local = f"{query} site:{medio}"
                        print(f"   Buscando en: {medio}")
                        
                        try:
                            local_search = await self.client.search.create(
                                query=query_local,
                                max_results=10,
                                **{k: v for k, v in search_params.items() if k.startswith("search_")}
                            )
                            
                            for result in local_search.results[:3]:  # Máximo 3 por medio
                                if any(art["url"] == result.url for art in analyzed_articles):
                                    continue  # Evitar duplicados
                                
                                score = calcular_score_relevancia(result, campaign_name, boost_local=True)
                                if score >= 1.0:  # Umbral más bajo para medios locales
                                    print(f"   ✅ Encontrado en {medio}: {result.title[:60]}...")
                                    # Analizar igual que antes...
                                    # (código similar al bloque de análisis anterior)
                        
                        except Exception as e:
                            print(f"   ❌ Error en búsqueda de {medio}: {e}")

                # Verificar si ya tenemos suficientes resultados
                if len(analyzed_articles) >= 3:
                    print(f"\n✅ ÉXITO: {len(analyzed_articles)} artículos relevantes encontrados")
                    break

            except PerplexityError as e:
                print(f"❌ Error en API de Perplexity (intento {i}): {e}")
                if i == len(intentos):
                    return []
                continue

        # Ordenar resultados finales: medios locales primero
        if priorizar_medios_locales:
            analyzed_articles.sort(key=lambda x: (not x["es_medio_local"], -x["relevance_score"]))

        print(f"\n{'='*60}")
        print(f"📊 RESUMEN FINAL:")
        print(f"   Total artículos: {len(analyzed_articles)}")
        if priorizar_medios_locales:
            locales = sum(1 for art in analyzed_articles if art["es_medio_local"])
            print(f"   De medios locales: {locales}")
        print(f"{'='*60}\n")

        return analyzed_articles

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Resumen diario con énfasis en medios locales."""
        print(f"📰 Resumen diario para: {actor_name} (priorizando medios locales)")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO[:4])
        
        analysis_prompt = f"""
Realiza una búsqueda automatizada sobre el actor político "{actor_name}" en medios digitales, prensa y redes sociales, 
priorizando ESPECIALMENTE medios locales de Tampico como: {medios_str}.

Limítate a las 5-10 notas más relevantes de las últimas 24 horas.

Formato JSON:
1. **Resumen Diario Express:** Síntesis en máximo 3 líneas
2. **Registro de Evidencia (5-10 entradas):** 
   - Descripción
   - Fecha
   - Link
   - Medio (identificar si es local)

Prioriza velocidad y relevancia de medios LOCALES.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista de medios especializado en prensa local de Tampico."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_diario_express": {"type": "string"},
                                "registro_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "link": {"type": "string", "format": "uri"},
                                            "medio": {"type": "string"},
                                            "es_local": {"type": "boolean"}
                                        },
                                        "required": ["descripcion", "fecha", "link", "medio"]
                                    }
                                }
                            },
                            "required": ["resumen_diario_express", "registro_de_evidencia"]
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            analysis_json = json.loads(analysis_content)
            
            # Ordenar evidencias: medios locales primero
            if "registro_de_evidencia" in analysis_json:
                analysis_json["registro_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_local", False), x.get("fecha", ""))
                )
            
            return analysis_json

        except Exception as e:
            print(f"❌ Error en resumen diario: {e}")
            return {"error": str(e)}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Reporte semanal con énfasis en medios locales."""
        print(f"📊 Reporte semanal para: {actor_name} (priorizando medios locales)")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO)
        
        analysis_prompt = f"""
Realiza un análisis semanal integral sobre "{actor_name}", priorizando ESPECIALMENTE 
medios locales de Tampico: {medios_str}.

Formato JSON con 3 secciones:
1. **Resumen Ejecutivo:** Hechos, tendencias, métricas (menciones, cobertura LOCAL)
2. **Análisis Político y FODA:** Narrativas, controversias, alianzas, FODA estratégico
3. **Log de Evidencia (20 registros mixtos):** 
   - Priorizar medios LOCALES
   - Descripción, fecha, tipo de medio, enlace
   - Marcar si es medio local

Prioriza extracción de prensa LOCAL de Tampico.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista político especializado en medios locales de Tampico."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_ejecutivo": {"type": "string"},
                                "analisis_estrategico": {"type": "string"},
                                "log_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "tipo_medio": {"type": "string"},
                                            "link": {"type": "string"},
                                            "es_medio_local": {"type": "boolean"}
                                        },
                                        "required": ["descripcion", "fecha", "tipo_medio", "link"]
                                    }
                                }
                            },
                            "required": ["resumen_ejecutivo", "analisis_estrategico", "log_de_evidencia"]
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            analysis_json = json.loads(analysis_content)
            
            # Ordenar evidencias: medios locales primero
            if "log_de_evidencia" in analysis_json:
                analysis_json["log_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_medio_local", False), x.get("fecha", ""))
                )
            
            return analysis_json

        except Exception as e:
            print(f"❌ Error en reporte semanal: {e}")
            return {"error": str(e)}


# Instancia global del servicio
perplexity_service = PerplexityService()