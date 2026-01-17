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

# Medios de Tamaulipas
MEDIOS_TAMAULIPAS = [
    "soldetampico.com.mx",
    "elsoldeltampico.com",
    "elsoldetampico.com.mx",
    "telediario.mx",
    "expreso.press",
    "expresopress.com",
    "hoytamaulipas.net",
    "laverdaddetamaulipas.com",
    "elpulsodetampico.com"
]

# Medios de Nuevo León
MEDIOS_NUEVO_LEON = [
    "elporvenir.mx",
    "milenio.com/monterrey",
    "abcnoticias.mx",
    "info7.mx",
    "elfinanciero.com.mx/monterrey",
    "multimedios.com",
    "elnorte.com",
    "noticiasya.com.mx"
]

# Medios de Querétaro
MEDIOS_QUERETARO = [
    "diariodequeretaro.com.mx",
    "amqueretaro.com",
    "tribunadequeretaro.com",
    "elsoldequeretaro.com.mx",
    "eluniversalqueretaro.mx",
    "rotativo.com.mx/queretaro",
    "plazadearmas.com.mx"
]

# Medios de Hidalgo
MEDIOS_HIDALGO = [
    "criteriohidalgo.com",
    "elindependientedehidalgo.com.mx",
    "elsolhidalgo.com.mx",
    "lasillarota.com/hidalgo",
    "milenio.com/politica/hidalgo",
    "hidalgo.milenio.com"
]

# Medios nacionales relevantes
MEDIOS_NACIONALES = [
    "milenio.com",
    "eluniversal.com.mx",
    "jornada.com.mx",
    "proceso.com.mx"
]

# Lista combinada de TODOS los medios locales
MEDIOS_LOCALES_TODOS = (
    MEDIOS_TAMAULIPAS + 
    MEDIOS_NUEVO_LEON + 
    MEDIOS_QUERETARO + 
    MEDIOS_HIDALGO
)

BOOST_MEDIOS_LOCALES = 1.5


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
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"⚠️ Error al obtener contenido de {url}: {e}")
        return ""


def es_medio_local(url: str) -> bool:
    """Determina si una URL pertenece a un medio local prioritario."""
    url_lower = url.lower()
    return any(medio in url_lower for medio in MEDIOS_LOCALES_TODOS)


def calcular_score_relevancia(result: Any, campaign_name: str, boost_local: bool = True) -> float:
    """
    Calcula un score de relevancia basado en:
    - Presencia del campaign_name en título/snippet
    - Si es medio local (boost)
    """
    score = 0.0
    campaign_lower = campaign_name.lower()
    
    # Extraer palabras clave del campaign_name
    keywords = campaign_lower.split()
    
    # Boost por keywords en título
    title_lower = result.title.lower()
    for keyword in keywords:
        if len(keyword) > 3 and keyword in title_lower:
            score += 1.0
    
    # Boost por keywords en snippet
    if hasattr(result, 'snippet') and result.snippet:
        snippet_lower = result.snippet.lower()
        for keyword in keywords:
            if len(keyword) > 3 and keyword in snippet_lower:
                score += 0.5
    
    # BOOST ADICIONAL para medios locales
    if boost_local and es_medio_local(result.url):
        score *= BOOST_MEDIOS_LOCALES
        print(f"🏠 MEDIO LOCAL: {result.url[:80]}... | Score: {score:.2f}")
    
    return score


def crear_analisis_fallback(title: str, url: str, relevance_score: float, es_local: bool) -> Dict[str, Any]:
    """
    Crea un análisis básico cuando la API no responde.
    Usado como FALLBACK cuando el análisis JSON falla.
    """
    return {
        "title": title,
        "url": url,
        "publishedAt": None,
        "summary": f"Artículo sobre el tema analizado. Título: {title[:100]}",
        "sentiment_label": "Neutral",
        "sentiment_score": 0.0,
        "topics": ["política", "noticias"],
        "key_points": ["Ver artículo completo en la fuente"],
        "relevance_score": relevance_score,
        "es_medio_local": es_local,
        "_fallback": True  # Marca que fue creado con fallback
    }

def _clean_json_content(content: str) -> str:
        """Limpia el contenido para asegurar JSON válido."""
        if not content:
            return "{}"
        
        # Eliminar caracteres no ASCII y espacios al inicio/fin
        content = content.strip()
        
        # Buscar el primer '{' y último '}'
        start = content.find('{')
        end = content.rfind('}')
        
        if start >= 0 and end > start:
            return content[start:end + 1]
        return "{}"

def fecha_larga_es(date_input: Optional[Any] = None) -> str:
    """
    Devuelve la fecha en formato '6 de noviembre de 2025'.
    date_input puede ser:
      - None (usa la fecha actual)
      - datetime
      - str en formatos: 'YYYY-MM-DD', 'MM/DD/YYYY', 'DD/MM/YYYY' o ISO
    """
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]

    dt = None
    if date_input is None:
        dt = datetime.now()
    elif isinstance(date_input, datetime):
        dt = date_input
    else:
        s = str(date_input).strip()
        # Intentar formatos comunes
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
        # Intentar ISO como última opción
        if dt is None:
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                print(f"Formato de fecha no reconocido: '{s}', usando fecha actual")
                dt = datetime.now()

    return f"{dt.day} de {meses[dt.month - 1]} de {dt.year}"

class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def _analizar_articulo_con_fallback(
        self, 
        result: Any, 
        campaign_name: str, 
        content: str, 
        relevance_score: float
    ) -> Optional[Dict[str, Any]]:
        """
        Intenta analizar un artículo con múltiples estrategias:
        1. Análisis completo con JSON schema
        2. Análisis simple sin schema (si falla el primero)
        3. Fallback con datos básicos (si todo falla)
        """
        es_local = es_medio_local(result.url)
        
        # ========== INTENTO 1: Análisis con JSON Schema ==========
        try:
            analysis_prompt = f"""
Analiza este artículo sobre '{campaign_name}'.

Responde SOLO con JSON válido:
{{
  "summary": "Resumen en 2-3 frases",
  "sentiment_label": "Positivo|Negativo|Neutral",
  "sentiment_score": 0.5,
  "topics": ["tema1", "tema2"],
  "key_points": ["punto1", "punto2"]
}}

Artículo:
{content[:3000]}
"""

            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista de medios. Respondes SOLO con JSON válido."},
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
            
            # Validar que no esté vacío
            if not analysis_content or analysis_content.strip() == "":
                print(f"   ⚠️ Respuesta vacía, intentando método alternativo...")
                raise ValueError("Respuesta vacía")
            
            analysis_json = json.loads(analysis_content)
            
            # Validar que tenga contenido útil
            if not analysis_json.get("summary") or len(analysis_json.get("summary", "")) < 10:
                print(f"   ⚠️ Análisis sin contenido útil, intentando método alternativo...")
                raise ValueError("Análisis vacío")
            
            # ✅ ÉXITO: Análisis completo
            return {
                "title": result.title,
                "url": result.url,
                "publishedAt": getattr(result, 'published_date', None),
                "summary": analysis_json.get("summary", ""),
                "sentiment_label": analysis_json.get("sentiment_label", "Neutral"),
                "sentiment_score": analysis_json.get("sentiment_score", 0.0),
                "topics": analysis_json.get("topics", []),
                "key_points": analysis_json.get("key_points", []),
                "relevance_score": relevance_score,
                "es_medio_local": es_local,
                "_fallback": False
            }
            
        except (json.JSONDecodeError, ValueError) as e:
            print(f"   ⚠️ Intento 1 falló: {e}")
            pass  # Continuar al intento 2
        except Exception as e:
            print(f"   ⚠️ Error inesperado en intento 1: {e}")
            pass

        # ========== INTENTO 2: Análisis Simple SIN Schema ==========
        try:
            print(f"   🔄 Intentando análisis simple...")
            
            simple_prompt = f"""
Analiza brevemente este artículo sobre '{campaign_name}'.

Responde en formato JSON simple:
{{"summary": "resumen breve", "sentiment": "positivo/negativo/neutral"}}

Texto: {content[:2000]}
"""

            simple_response = await self.client.chat.completions.create(
                model="sonar",  # Modelo más simple
                messages=[
                    {"role": "user", "content": simple_prompt},
                ],
            )
            
            simple_content = simple_response.choices[0].message.content
            
            if simple_content and simple_content.strip():
                # Intentar parsear el JSON
                simple_json = json.loads(simple_content)
                
                # ✅ ÉXITO: Análisis simple
                print(f"   ✅ Análisis simple exitoso")
                return {
                    "title": result.title,
                    "url": result.url,
                    "publishedAt": getattr(result, 'published_date', None),
                    "summary": simple_json.get("summary", f"Artículo sobre {campaign_name}"),
                    "sentiment_label": simple_json.get("sentiment", "Neutral").capitalize(),
                    "sentiment_score": 0.0,
                    "topics": [campaign_name, "política"],
                    "key_points": ["Ver fuente original"],
                    "relevance_score": relevance_score,
                    "es_medio_local": es_local,
                    "_fallback": "simple"
                }
        except Exception as e:
            print(f"   ⚠️ Intento 2 falló: {e}")
            pass

        # ========== INTENTO 3: FALLBACK - Datos Básicos ==========
        print(f"   ⚙️ Usando datos básicos (fallback)")
        return crear_analisis_fallback(result.title, result.url, relevance_score, es_local)

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
        ULTRA ROBUSTA con múltiples estrategias de análisis.
        """
        print(f"\n{'='*70}")
        print(f"🔍 BÚSQUEDA ITERATIVA ULTRA ROBUSTA")
        print(f"   Campaña: {campaign_name}")
        print(f"   Query: {query[:100]}...")
        print(f"   Medios locales: {'✅ PRIORIZADOS' if priorizar_medios_locales else '❌ No'}")
        print(f"{'='*70}\n")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        analyzed_articles = []
        
        intentos = [
            {"max_results": 20, "threshold": 1.5, "nombre": "ESTRICTO"},
            {"max_results": 20, "threshold": 1.0, "nombre": "MEDIO"},
            {"max_results": 20, "threshold": 0.5, "nombre": "RELAJADO"}
        ]

        for i, config in enumerate(intentos, 1):
            print(f"\n{'─'*70}")
            print(f"🔄 INTENTO {i}/3 - Modo {config['nombre']}")
            print(f"   Max resultados: {config['max_results']}, Umbral: {config['threshold']}")
            print(f"{'─'*70}")

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
                
                print(f"\n📊 Resultados:")
                print(f"   Total encontrados: {len(search_results.results)}")
                print(f"   ✅ Relevantes (>= {config['threshold']}): {len(filtered_results)}")
                
                if priorizar_medios_locales:
                    medios_locales_count = sum(1 for result, _ in filtered_results if es_medio_local(result.url))
                    print(f"   🏠 Medios locales: {medios_locales_count}")

                # Analizar artículos filtrados
                for result, score in filtered_results[:15]:
                    print(f"\n📄 Analizando: {result.title[:70]}...")
                    print(f"   URL: {result.url[:80]}...")
                    print(f"   Score: {score:.2f} {'🏠' if es_medio_local(result.url) else '🌐'}")

                    content = await _get_url_content(result.url)
                    if not content:
                        print(f"   ⚠️ Sin contenido, usando fallback básico")
                        # Aún así agregamos el artículo con datos básicos
                        article = crear_analisis_fallback(
                            result.title, 
                            result.url, 
                            score, 
                            es_medio_local(result.url)
                        )
                        analyzed_articles.append(article)
                        print(f"   ✅ Agregado con datos básicos (Total: {len(analyzed_articles)})")
                        continue

                    # ✅ Intentar análisis con fallback automático
                    article = await self._analizar_articulo_con_fallback(
                        result, campaign_name, content, score
                    )
                    
                    if article:
                        analyzed_articles.append(article)
                        fallback_type = article.get("_fallback", False)
                        if fallback_type == True:
                            print(f"   ✅ Agregado con fallback básico (Total: {len(analyzed_articles)})")
                        elif fallback_type == "simple":
                            print(f"   ✅ Agregado con análisis simple (Total: {len(analyzed_articles)})")
                        else:
                            print(f"   ✅ Agregado con análisis completo (Total: {len(analyzed_articles)})")

                # Verificar si ya tenemos suficientes resultados
                if len(analyzed_articles) >= 3:
                    print(f"\n✅ ÉXITO: {len(analyzed_articles)} artículos encontrados")
                    break

            except PerplexityError as e:
                print(f"❌ Error en API de Perplexity (intento {i}): {e}")
                if i == len(intentos):
                    print(f"⚠️ Agotados todos los intentos, retornando {len(analyzed_articles)} artículos")
                    break
                continue

        # Ordenar resultados finales: medios locales primero
        if priorizar_medios_locales and analyzed_articles:
            analyzed_articles.sort(key=lambda x: (not x["es_medio_local"], -x["relevance_score"]))

        print(f"\n{'='*70}")
        print(f"📊 RESUMEN FINAL:")
        print(f"   Total artículos: {len(analyzed_articles)}")
        if priorizar_medios_locales and analyzed_articles:
            locales = sum(1 for art in analyzed_articles if art["es_medio_local"])
            fallbacks = sum(1 for art in analyzed_articles if art.get("_fallback"))
            print(f"   🏠 Medios locales: {locales}")
            print(f"   ⚙️ Con fallback: {fallbacks}")
        print(f"{'='*70}\n")

        return analyzed_articles
    
    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Resumen diario con énfasis en medios locales de múltiples estados."""
        print(f"\n📰 Generando resumen diario para: {actor_name}")

        hoy = fecha_larga_es()
        # print(hoy) 

        medios_ejemplos = "Sol de Tampico, Milenio, El Porvenir, Diario de Querétaro, Criterio Hidalgo"
        
        analysis_prompt = f"""Busca información sobre "{actor_name}" EXCLUSIVAMENTE en publicaciones de HOY ({hoy}) en estos medios digitales locales:
TAMAULIPAS: Sol de Tampico, Telediario, Expreso, Hoy Tamaulipas
NUEVO LEÓN: El Porvenir, Info7, Milenio Monterrey, Multimedios
QUERÉTARO: Diario de Querétaro, AM Querétaro, El Sol de Querétaro
HIDALGO: Criterio Hidalgo, El Independiente, El Sol Hidalgo

INSTRUCCIÓN CRÍTICA: Responde ÚNICAMENTE con JSON válido. Sin explicaciones, sin texto adicional, solo JSON.

Si no hay publicaciones de hoy, devuelve un JSON vacío en la estructura solicitada.

FORMATO REQUERIDO - Responde SOLO esto:
{{
  "resumen_diario_express": "máximo 3 líneas describiendo hallazgos",
  "registro_de_evidencia": [
    {{
      "descripcion": "texto de la publicación",
      "fecha": "YYYY-MM-DD",
      "link": "URL completa",
      "medio": "nombre exacto del medio",
      "es_local": true
    }}
  ]
}}
"""
        
        # print(analysis_prompt)

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Analista de medios. Respondes SOLO con JSON válido. NUNCA incluyas texto antes o después del JSON."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "daily_summary",
                        "strict": True,
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
                                            "link": {"type": "string"},
                                            "medio": {"type": "string"},
                                            "es_local": {"type": "boolean"}
                                        },
                                        "required": ["descripcion", "fecha", "link", "medio"]
                                    }
                                }
                            },
                            "required": ["resumen_diario_express", "registro_de_evidencia"],
                            "additionalProperties": False
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            
            # Validación robusta
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API para resumen diario")
                # NUNCA retornar con clave "error", siempre con las claves correctas
                return {
                    "resumen_diario_express": f"Resumen no disponible para {actor_name} en este momento.",
                    "registro_de_evidencia": []
                }
            
            try:
                # print("analysis_content: ")
                # print(analysis_content)
                # analysis_json = json.loads(analysis_content)
                # Limpiar y validar el contenido JSON
                cleaned_content = _clean_json_content(analysis_content)
                print(f"🔍 Contenido JSON limpio:\n{cleaned_content}")
            
                analysis_json = json.loads(cleaned_content)
            except json.JSONDecodeError as je:
                print(f"⚠️ Error decodificando JSON en resumen diario: {je}")
                # NUNCA retornar con clave "error"
                return {
                    "resumen_diario_express": f"Análisis en proceso para {actor_name}. Intenta de nuevo en unos momentos.",
                    "registro_de_evidencia": []
                }
            
            # Validar que sea un diccionario
            if not isinstance(analysis_json, dict):
                print(f"⚠️ Respuesta no es un diccionario válido")
                return {
                    "resumen_diario_express": f"Recopilando información sobre {actor_name}.",
                    "registro_de_evidencia": []
                }
            
            # Asegurar que tenga las claves requeridas
            if "resumen_diario_express" not in analysis_json:
                analysis_json["resumen_diario_express"] = f"Información sobre {actor_name}"
            if "registro_de_evidencia" not in analysis_json:
                analysis_json["registro_de_evidencia"] = []
            
            # Ordenar evidencias: medios locales primero
            if isinstance(analysis_json.get("registro_de_evidencia"), list):
                analysis_json["registro_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_local", False), x.get("fecha", ""))
                )
            
            evidencias_count = len(analysis_json.get("registro_de_evidencia", []))
            locales_count = sum(1 for ev in analysis_json.get("registro_de_evidencia", []) if ev.get("es_local", False))
            print(f"✅ Resumen diario generado: {evidencias_count} evidencias ({locales_count} locales)")
            return analysis_json

        except Exception as e:
            print(f"❌ Error inesperado en resumen diario: {e}")
            # NUNCA retornar con clave "error", siempre estructura correcta
            return {
                "resumen_diario_express": f"Información sobre {actor_name} temporalmente no disponible.",
                "registro_de_evidencia": []
            }

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Reporte semanal con énfasis en medios locales de múltiples estados."""
        print(f"\n📊 Generando reporte semanal para: {actor_name}")

        analysis_prompt = f"""
Análisis semanal integral de "{actor_name}", priorizando medios locales de:
- Tamaulipas: Sol de Tampico, Telediario, Expreso, Hoy Tamaulipas
- Nuevo León: El Porvenir, Info7, Milenio Monterrey, Multimedios
- Querétaro: Diario de Querétaro, AM Querétaro, El Sol de Querétaro
- Hidalgo: Criterio Hidalgo, El Independiente, El Sol Hidalgo

Responde SOLO con JSON válido (sin texto antes o después):
{{
  "resumen_ejecutivo": "Texto con hechos, tendencias y métricas",
  "analisis_estrategico": "Texto con FODA y análisis político",
  "log_de_evidencia": [
    {{
      "descripcion": "Descripción",
      "fecha": "YYYY-MM-DD",
      "tipo_medio": "Tipo",
      "link": "https://...",
      "es_medio_local": true
    }}
  ]
}}
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Analista político. Respondes SOLO con JSON válido. NUNCA incluyas texto antes o después del JSON."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "weekly_report",
                        "strict": True,
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
                            "required": ["resumen_ejecutivo", "analisis_estrategico", "log_de_evidencia"],
                            "additionalProperties": False
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            
            # Validación robusta
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API para reporte semanal")
                # NUNCA retornar con clave "error", siempre con las claves correctas
                return {
                    "resumen_ejecutivo": f"Reporte para {actor_name} en proceso de generación.",
                    "analisis_estrategico": "Información en recopilación. Intenta de nuevo en unos momentos.",
                    "log_de_evidencia": []
                }
            
            try:
                analysis_json = json.loads(analysis_content)
            except json.JSONDecodeError as je:
                print(f"⚠️ Error decodificando JSON en reporte semanal: {je}")
                # NUNCA retornar con clave "error"
                return {
                    "resumen_ejecutivo": f"Análisis de {actor_name} en curso.",
                    "analisis_estrategico": "Datos en proceso de análisis.",
                    "log_de_evidencia": []
                }
            
            # Validar que sea un diccionario
            if not isinstance(analysis_json, dict):
                print(f"⚠️ Respuesta no es un diccionario válido")
                return {
                    "resumen_ejecutivo": f"Información sobre {actor_name}.",
                    "analisis_estrategico": "Análisis en progreso.",
                    "log_de_evidencia": []
                }
            
            # Asegurar que tenga todas las claves requeridas
            if "resumen_ejecutivo" not in analysis_json:
                analysis_json["resumen_ejecutivo"] = f"Resumen ejecutivo para {actor_name}"
            if "analisis_estrategico" not in analysis_json:
                analysis_json["analisis_estrategico"] = "Análisis estratégico en proceso"
            if "log_de_evidencia" not in analysis_json:
                analysis_json["log_de_evidencia"] = []
            
            # Ordenar evidencias: medios locales primero
            if isinstance(analysis_json.get("log_de_evidencia"), list):
                analysis_json["log_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_medio_local", False), x.get("fecha", ""))
                )
            
            evidencias_count = len(analysis_json.get("log_de_evidencia", []))
            locales_count = sum(1 for ev in analysis_json.get("log_de_evidencia", []) if ev.get("es_medio_local", False))
            print(f"✅ Reporte semanal generado: {evidencias_count} evidencias ({locales_count} locales)")
            return analysis_json

        except Exception as e:
            print(f"❌ Error inesperado en reporte semanal: {e}")
            # NUNCA retornar con clave "error", siempre estructura correcta
            return {
                "resumen_ejecutivo": f"Reporte para {actor_name} temporalmente no disponible.",
                "analisis_estrategico": "Se está trabajando en recopilar la información.",
                "log_de_evidencia": []
            }

    async def analyze_collected_data(
        self,
        actor_name: str,
        data: List[Dict[str, Any]],
        metricas: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analiza datos recopilados de MonitoringSources con IA.
        Recibe posts de redes sociales y noticias, y genera un análisis inteligente.
        """
        print(f"\n🤖 Analizando {len(data)} items para: {actor_name}")

        # Preparar resumen de datos para el prompt
        redes_data = [d for d in data if d.get("tipo") == "red_social"]
        noticias_data = [d for d in data if d.get("tipo") == "noticia"]

        # Construir contexto de contenido
        contenido_redes = "\n".join([
            f"- [{d.get('plataforma', 'red')}] {d.get('autor', 'Anónimo')}: {d.get('contenido', '')[:150]}"
            for d in redes_data[:15]
        ])

        contenido_noticias = "\n".join([
            f"- {d.get('titulo', 'Sin título')}: {d.get('resumen', '')[:100] if d.get('resumen') else 'Sin resumen'}"
            for d in noticias_data[:10]
        ])

        analysis_prompt = f"""
Analiza los siguientes datos recopilados sobre "{actor_name}" de nuestras fuentes de monitoreo:

📊 MÉTRICAS GENERALES:
- Total menciones: {metricas.get('total', 0)}
- Redes sociales: {metricas.get('redes', 0)}
- Noticias: {metricas.get('noticias', 0)}
- Sentimiento: Positivo {metricas.get('sentimiento', {}).get('positive', 0)}, Negativo {metricas.get('sentimiento', {}).get('negative', 0)}, Neutral {metricas.get('sentimiento', {}).get('neutral', 0)}
- Engagement total: Likes {metricas.get('engagement', {}).get('likes', 0)}, Shares {metricas.get('engagement', {}).get('shares', 0)}, Comentarios {metricas.get('engagement', {}).get('comments', 0)}
- Plataformas: {metricas.get('plataformas', {})}
- Temas detectados: {', '.join(metricas.get('temas', [])) if metricas.get('temas') else 'Ninguno'}

📱 CONTENIDO DE REDES SOCIALES:
{contenido_redes if contenido_redes else 'Sin contenido de redes sociales'}

📰 NOTICIAS:
{contenido_noticias if contenido_noticias else 'Sin noticias'}

Responde SOLO con JSON válido (sin texto antes o después):
{{
  "resumen_ejecutivo": "Resumen ejecutivo de 2-3 párrafos analizando la situación actual, tendencias y percepción pública basándose en los datos proporcionados",
  "analisis_estrategico": "Análisis FODA basado en los datos: Fortalezas, Debilidades, Oportunidades y Amenazas detectadas",
  "recomendaciones": ["Recomendación 1 basada en datos", "Recomendación 2", "Recomendación 3"],
  "narrativas_detectadas": ["Narrativa principal 1", "Narrativa 2"],
  "alertas": ["Alerta si hay contenido de riesgo"]
}}
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un analista político experto. Analizas datos de monitoreo de redes sociales y noticias para generar insights estratégicos. Respondes SOLO con JSON válido."
                    },
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "analysis_report",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_ejecutivo": {"type": "string"},
                                "analisis_estrategico": {"type": "string"},
                                "recomendaciones": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "narrativas_detectadas": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "alertas": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["resumen_ejecutivo", "analisis_estrategico", "recomendaciones"],
                            "additionalProperties": False
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content

            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de Perplexity")
                return self._default_analysis(actor_name, metricas)

            try:
                analysis_json = json.loads(analysis_content)
                print(f"✅ Análisis completado para {actor_name}")
                return analysis_json
            except json.JSONDecodeError as je:
                print(f"⚠️ Error decodificando JSON: {je}")
                return self._default_analysis(actor_name, metricas)

        except Exception as e:
            print(f"❌ Error en análisis con Perplexity: {e}")
            return self._default_analysis(actor_name, metricas)

    def _default_analysis(self, actor_name: str, metricas: Dict[str, Any]) -> Dict[str, Any]:
        """Genera un análisis por defecto cuando Perplexity falla"""
        total = metricas.get('total', 0)
        sentimiento = metricas.get('sentimiento', {})
        max_sent = max(sentimiento, key=sentimiento.get) if sentimiento else "neutral"

        return {
            "resumen_ejecutivo": f"Análisis de {actor_name}: Se detectaron {total} menciones en el período analizado. "
                                 f"El sentimiento predominante es {max_sent} con {sentimiento.get(max_sent, 0)} menciones.",
            "analisis_estrategico": f"Basado en los datos recopilados, se observa una presencia "
                                    f"{'activa' if total > 20 else 'moderada'} en medios y redes sociales.",
            "recomendaciones": [
                "Continuar monitoreando las fuentes configuradas",
                "Analizar contenido de alto engagement para identificar temas clave",
                "Responder a menciones negativas de manera oportuna"
            ],
            "narrativas_detectadas": metricas.get('temas', [])[:3],
            "alertas": []
        }


# Instancia global del servicio
perplexity_service = PerplexityService()