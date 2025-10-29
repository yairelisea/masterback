# app/services/relevance_filter.py
"""
✅ Sistema de filtrado de relevancia en 3 capas
Evita que Perplexity traiga artículos irrelevantes
"""
from __future__ import annotations
import re
import logging
from typing import Optional, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ✅ Medios confiables mexicanos
TRUSTED_MEXICAN_MEDIA = [
    # Nacionales
    "milenio.com", "eluniversal.com.mx", "jornada.com.mx",
    "reforma.com", "excelsior.com.mx", "proceso.com.mx",
    "animalpolitico.com", "sinembargo.mx", "aristeguinoticias.com",
    "forbes.com.mx", "elfinanciero.com.mx", "eleconomista.com.mx",
    "tribuna.com.mx", "vanguardia.com.mx", "zocalo.com.mx",
    "tv7.mx", "televisa.com", "noticiero.com.mx",
    
    # Regionales
    "ntrguadalajara.com", "ntrzacatecas.com", "ntrmonterrey.mx",
    "info7.mx", "multimedios.com",
    "hoytamaulipas.net", "expreso.press", "tribunahoy.com",
    "elmanana.com",
    
    # Sitios oficiales
    ".gob.mx",
]

# ✅ Keywords políticos (boost)
POLITICAL_KEYWORDS = [
    "elección", "voto", "campaña", "candidato", "partido",
    "congreso", "senado", "diputado", "alcalde", "gobernador",
    "legislatura", "propuesta", "iniciativa", "moción",
    "gobierno", "política", "político", "electoral",
]

# ✅ Keywords irrelevantes (penalty)
IRRELEVANT_KEYWORDS = [
    "receta", "horóscopo", "deportes", "fútbol", "beisbol",
    "espectáculos", "farándula", "cine", "música",
    "fallece", "murió", "obituario", "QEPD", "descanse en paz",
]


async def quick_relevance_check(
    result_title: str,
    result_url: str,
    actor_name: str,
    city_keywords: Optional[List[str]] = None,
) -> Tuple[bool, float]:
    """
    ✅ Validación rápida de relevancia SIN consumir API de análisis
    
    Sistema de scoring:
    - 50 pts: nombre completo del actor
    - 20 pts: ciudad mencionada
    - 20 pts: medio confiable
    - 15 pts: keywords políticos
    - -30 pts: redes sociales sin contexto
    - -40 pts: Wikipedia/IMDB
    - -25 pts: palabras irrelevantes
    
    Threshold: 40 puntos mínimo para ser relevante
    
    Returns:
        (es_relevante, score)
    """
    # Normalizar textos
    title_lower = result_title.lower()
    url_lower = result_url.lower()
    actor_lower = actor_name.lower()
    
    score = 0.0
    
    # ✅ 1. Verificar que el nombre del actor esté en título o URL
    actor_parts = actor_lower.split()
    
    # Buscar nombre completo
    if actor_lower in title_lower or actor_lower in url_lower:
        score += 50  # Match exacto = 50 puntos
    else:
        # Buscar partes del nombre (apellidos suelen ser únicos)
        matches = sum(1 for part in actor_parts if len(part) > 3 and part in title_lower)
        score += matches * 15  # 15 puntos por cada parte
    
    # ✅ 2. Verificar región/ciudad
    if city_keywords:
        cities_lower = [c.lower() for c in city_keywords]
        city_matches = sum(1 for city in cities_lower if city in title_lower or city in url_lower)
        score += city_matches * 20  # 20 puntos por match de ciudad
    
    # ✅ 3. Verificar que sea medio confiable
    domain = urlparse(result_url).netloc.lower()
    
    if any(trusted in domain for trusted in TRUSTED_MEXICAN_MEDIA):
        score += 20
    elif domain.endswith(".mx"):
        score += 10  # Dominio mexicano genérico
    
    # ✅ 4. Penalizaciones (descartar obviamente irrelevantes)
    
    # Descartar redes sociales sin contexto
    social_domains = ["facebook.com", "twitter.com", "instagram.com", "tiktok.com"]
    if any(social in domain for social in social_domains):
        score -= 30
    
    # Descartar Wikipedia, IMDB (biográfico viejo)
    if "wikipedia" in domain or "imdb" in domain:
        score -= 40
    
    # Descartar si tiene palabras irrelevantes en título
    if any(kw in title_lower for kw in IRRELEVANT_KEYWORDS):
        score -= 25
    
    # ✅ 5. Boost por palabras clave políticas
    if any(kw in title_lower for kw in POLITICAL_KEYWORDS):
        score += 15
    
    # ✅ Decisión: relevante si score >= 40
    is_relevant = score >= 40
    
    if is_relevant:
        logger.debug(f"✅ RELEVANT (score={score:.1f}): {result_title[:50]}")
    else:
        logger.debug(f"⛔ REJECTED (score={score:.1f}): {result_title[:50]}")
    
    return is_relevant, score


# ✅ Base de datos de medios por estado (para expansión futura)
MEDIA_BY_STATE = {
    "Tamaulipas": [
        "hoytamaulipas.net",
        "expreso.press",
        "tribunahoy.com",
        "milenio.com/estados/tamaulipas",
        "elmanana.com",
    ],
    "Nuevo León": [
        "info7.mx",
        "multimedios.com",
        "abcnoticias.mx",
        "elporvenir.mx",
        "milenio.com/estados/nuevo-leon",
    ],
    "CDMX": [
        "chilango.com",
        "capitalmexico.com.mx",
        "razon.com.mx",
        "eluniversal.com.mx",
        "jornada.com.mx",
    ],
}

def get_trusted_domains_for_region(city_keywords: List[str]) -> List[str]:
    """
    ✅ Retorna dominios confiables según la región
    Útil para configuración futura
    """
    domains = []
    for city in city_keywords:
        for state, media_list in MEDIA_BY_STATE.items():
            if city.lower() in state.lower() or state.lower() in city.lower():
                domains.extend(media_list)
    return list(set(domains))  # Dedupeß