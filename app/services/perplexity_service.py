# app/services/perplexity_service.py
# VERSIÓN MEJORADA - Con filtro de relevancia estricto

from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from perplexity import AsyncPerplexity, PerplexityError

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

def to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
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

# ============================================
# NUEVA FUNCIÓN: VERIFICAR RELEVANCIA
# ============================================
def _check_actor_relevance(text: str, actor_name: str, title: str = "") -> tuple[bool, float]:
    """
    Verifica si el texto es realmente sobre el actor político.
    Retorna (es_relevante, score_relevancia)
    """
    if not text or not actor_name:
        return False, 0.0
    
    text_lower = text.lower()
    title_lower = title.lower()
    combined = f"{title_lower} {text_lower}"
    
    # Extraer nombres del actor
    actor_parts = actor_name.strip().lower().split()
    
    # Filtrar palabras muy comunes que no son nombres
    common_words = {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'e', 'o', 'u'}
    actor_keywords = [part for part in actor_parts if part not in common_words and len(part) > 2]
    
    if not actor_keywords:
        return False, 0.0
    
    # Score basado en presencia de palabras clave
    score = 0.0
    
    # 1. Nombre completo (peso alto)
    if actor_name.lower() in combined:
        score += 3.0
    
    # 2. Primer y último nombre juntos (peso medio-alto)
    if len(actor_keywords) >= 2:
        first_last = f"{actor_keywords[0]}.*{actor_keywords[-1]}"
        if re.search(first_last, combined, re.IGNORECASE):
            score += 2.0
    
    # 3. Al menos 2 keywords del nombre (peso medio)
    keywords_found = sum(1 for kw in actor_keywords if kw in combined)
    if keywords_found >= 2:
        score += 1.5
    elif keywords_found == 1:
        score += 0.5
    
    # 4. En el título (bonus)
    if any(kw in title_lower for kw in actor_keywords):
        score += 1.0
    
    # 5. Penalizar si hay demasiados otros nombres políticos comunes
    other_politicians = ['lopez obrador', 'claudia sheinbaum', 'andres manuel', 'amlo']
    other_count = sum(1 for pol in other_politicians if pol in combined and pol not in actor_name.lower())
    if other_count > 2:
        score -= 1.0
    
    # Umbral: necesita al menos score de 2.0 para ser relevante
    is_relevant = score >= 2.0
    
    return is_relevant, score


class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Resumen diario sobre un actor político."""
        print(f"Iniciando resumen diario para el actor: {actor_name}")

        analysis_prompt = f"""
Realiza una búsqueda automatizada enfocada EXCLUSIVAMENTE sobre el actor político "{actor_name}".

IMPORTANTE: Solo incluye información que mencione EXPLÍCITAMENTE a "{actor_name}". 
NO incluyas noticias genéricas sobre política o sobre otros actores.

Extrae las 5-10 notas más relevantes de las últimas 24 horas donde "{actor_name}" sea el protagonista o tema principal.

Responde en formato JSON con:
1. **Resumen Diario Express:** Máximo 3 líneas sobre "{actor_name}"
2. **Registro de Evidencia:** 5-10 publicaciones donde "{actor_name}" sea mencionado directamente

Descarta cualquier nota donde "{actor_name}" no sea el tema principal.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[{"role": "user", "content": analysis_prompt}],
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
                                            "enlace": {"type": "string"}
                                        },
                                        "required": ["descripcion", "fecha"],
                                        "additionalProperties": False
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
            print(f"\n==RESPUESTA IA PARA {actor_name}==\n{analysis_content}\n")
            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            print(f"Error en la API de Perplexity para el actor '{actor_name}': {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            print(f"Error al decodificar JSON para el actor '{actor_name}': {e}")
            return {"error": "Error decodificando la respuesta JSON."}
        except Exception as e:
            print(f"Error inesperado durante el resumen para '{actor_name}': {e}")
            return {"error": "Ocurrió un error inesperado."}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Reporte semanal sobre un actor político."""
        print(f"Iniciando reporte semanal para el actor: {actor_name}")

        analysis_prompt = f"""
Realiza un análisis EXCLUSIVAMENTE sobre el actor político "{actor_name}".

CRÍTICO: Solo incluye información que mencione EXPLÍCITAMENTE y de forma PRINCIPAL a "{actor_name}".
NO incluyas noticias genéricas sobre política mexicana o sobre otros actores políticos.

Busca contenido de los últimos 30 días donde "{actor_name}" sea el protagonista.

Responde en formato JSON con:
1. **Resumen Ejecutivo:** Sobre "{actor_name}" específicamente
2. **Análisis FODA:** De "{actor_name}" únicamente
3. **Log de Evidencia:** 20 publicaciones donde "{actor_name}" sea el tema central

Descarta cualquier contenido donde "{actor_name}" no sea mencionado o no sea el foco principal.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[{"role": "user", "content": analysis_prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "weekly_report",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_ejecutivo": {
                                    "type": "object",
                                    "properties": {
                                        "sintesis": {"type": "string"},
                                        "metricas_clave": {"type": "string"}
                                    },
                                    "required": ["sintesis", "metricas_clave"],
                                    "additionalProperties": False
                                },
                                "analisis_estrategico": {
                                    "type": "object",
                                    "properties": {
                                        "analisis_foda": {
                                            "type": "object",
                                            "properties": {
                                                "fortalezas": {"type": "array", "items": {"type": "string"}},
                                                "oportunidades": {"type": "array", "items": {"type": "string"}},
                                                "debilidades": {"type": "array", "items": {"type": "string"}},
                                                "amenazas": {"type": "array", "items": {"type": "string"}}
                                            },
                                            "required": ["fortalezas", "oportunidades", "debilidades", "amenazas"],
                                            "additionalProperties": False
                                        }
                                    },
                                    "required": ["analisis_foda"],
                                    "additionalProperties": False
                                },
                                "log_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "tipo": {"type": "string"},
                                            "enlace": {"type": "string"}
                                        },
                                        "required": ["descripcion", "fecha", "tipo"],
                                        "additionalProperties": False
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
            print(f"\n==REPORTE SEMANAL IA PARA {actor_name}==\n{analysis_content}\n")
            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            print(f"Error en la API de Perplexity para el reporte semanal de '{actor_name}': {e}")
            return {"error": str(e)}
        except Exception as e:
            print(f"Error inesperado durante el reporte semanal para '{actor_name}': {e}")
            return {"error": "Ocurrió un error inesperado."}

    # ============================================
    # MÉTODO MEJORADO: search_and_analyze
    # ============================================
    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca y analiza noticias con FILTRO DE RELEVANCIA ESTRICTO.
        Solo retorna artículos que realmente mencionen al actor.
        """
        print(f"🔍 Búsqueda para: {campaign_name} | Query: {query}")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        try:
            search_params = {
                "query": query,
                "max_results": 20,  # Aumentado porque filtraremos después
            }
            if formatted_start:
                search_params["search_after_date_filter"] = formatted_start
            if formatted_end:
                search_params["search_before_date_filter"] = formatted_end

            search_results = await self.client.search.create(**search_params)
            print(f"📊 Resultados de búsqueda: {len(search_results.results)}")
        except PerplexityError as e:
            print(f"❌ Error en búsqueda de Perplexity: {e}")
            return []

        analyzed_articles = []
        filtered_count = 0

        for idx, result in enumerate(search_results.results, 1):
            try:
                print(f"\n🔎 Analizando [{idx}/{len(search_results.results)}]: {result.url}")
                
                content = await _get_url_content(result.url)
                if not content or len(content) < 200:
                    print(f"⚠️  Contenido muy corto o vacío, omitiendo")
                    continue

                # ============================================
                # FILTRO DE RELEVANCIA PRE-ANÁLISIS
                # ============================================
                title = getattr(result, 'title', '')
                is_relevant, relevance_score = _check_actor_relevance(
                    content[:5000],  # Primeros 5000 caracteres
                    campaign_name,
                    title
                )
                
                print(f"📈 Score de relevancia: {relevance_score:.2f}")
                
                if not is_relevant:
                    print(f"❌ DESCARTADO - No menciona suficientemente a '{campaign_name}'")
                    filtered_count += 1
                    continue
                
                print(f"✅ RELEVANTE - Procesando análisis...")

                # ============================================
                # PROMPT DE ANÁLISIS MEJORADO
                # ============================================
                analysis_prompt = f"""
Analiza el siguiente artículo SOLO SI trata PRINCIPALMENTE sobre "{campaign_name}".

REGLAS ESTRICTAS:
1. Si "{campaign_name}" NO es el tema principal → responde SOLO: {{"relevante": false}}
2. Si "{campaign_name}" es mencionado apenas de paso → responde SOLO: {{"relevante": false}}
3. Si el artículo trata sobre otro político y solo menciona a "{campaign_name}" brevialmentemente → responde {{"relevante": false}}
4. SOLO si "{campaign_name}" ES el tema central → responde el análisis completo

Texto (primeros 4000 caracteres):
{content[:4000]}

Si ES relevante para "{campaign_name}", responde con:
{{
  "relevante": true,
  "summary": "resumen conciso (2-3 frases) enfocado en {campaign_name}",
  "sentiment_label": "Positivo" | "Negativo" | "Neutral",
  "sentiment_score": número de -1.0 a 1.0,
  "topics": ["tema1", "tema2", "tema3"],
  "key_points": ["punto clave 1", "punto clave 2"]
}}

Si NO es relevante:
{{
  "relevante": false
}}
"""

                chat_response = await self.client.chat.completions.create(
                    model="sonar-reasoning",
                    messages=[
                        {
                            "role": "system", 
                            "content": f"Eres un analista político MUY estricto. Solo consideras relevante un artículo si {campaign_name} es el tema PRINCIPAL."
                        },
                        {
                            "role": "user",
                            "content": analysis_prompt
                        }
                    ],
                    temperature=0.1,  # Más determinista
                    max_tokens=500,
                )

                response_text = chat_response.choices[0].message.content.strip()
                
                # Parsear respuesta
                try:
                    analysis = json.loads(response_text)
                except json.JSONDecodeError:
                    # Intentar extraer JSON si viene con texto adicional
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        analysis = json.loads(json_match.group())
                    else:
                        print(f"⚠️  No se pudo parsear respuesta, omitiendo")
                        continue

                # ============================================
                # VERIFICACIÓN FINAL DE RELEVANCIA
                # ============================================
                if not analysis.get("relevante", False):
                    print(f"❌ IA confirmó NO RELEVANTE")
                    filtered_count += 1
                    continue

                print(f"✅ IA confirmó RELEVANTE - Agregando a resultados")

                # Construir artículo analizado
                analyzed_article = {
                    "title": title or f"Artículo sobre {campaign_name}",
                    "url": result.url,
                    "publishedAt": getattr(result, 'published_date', None),
                    "summary": analysis.get("summary", ""),
                    "sentiment_label": analysis.get("sentiment_label", "Neutral"),
                    "sentiment_score": analysis.get("sentiment_score", 0.0),
                    "topics": analysis.get("topics", []),
                    "key_points": analysis.get("key_points", []),
                    "relevance_score": relevance_score,  # Agregar score
                }

                analyzed_articles.append(analyzed_article)

            except Exception as e:
                print(f"⚠️  Error analizando {result.url}: {e}")
                continue

        # ============================================
        # RESUMEN DEL FILTRADO
        # ============================================
        print(f"\n📊 RESUMEN DEL FILTRADO:")
        print(f"   Artículos encontrados: {len(search_results.results)}")
        print(f"   Artículos descartados: {filtered_count}")
        print(f"   Artículos relevantes: {len(analyzed_articles)}")
        print(f"   Tasa de relevancia: {len(analyzed_articles)/max(len(search_results.results), 1)*100:.1f}%")

        # Ordenar por relevancia
        analyzed_articles.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

        return analyzed_articles


# Instancia global
perplexity_service = PerplexityService()