# app/services/query_builder.py
# VERSIÓN MEJORADA - Queries más específicas para evitar resultados irrelevantes

from __future__ import annotations
from typing import Iterable, List, Optional

ROLE_KEYWORDS = [
    "alcalde",
    "alcaldesa",
    "presidente municipal",
    "edil",
    "munícipe",
    "diputado",
    "diputada",
    "senador",
    "senadora",
    "candidato",
    "candidata",
    "gobernador",
    "gobernadora",
]

PARTY_KEYWORDS = ["morena", "pan", "pri", "prd", "mc", "verde", "pt", "movimiento ciudadano"]

# Palabras clave de contexto político mexicano
POLITICAL_CONTEXT = [
    "política",
    "gobierno",
    "elecciones",
    "campaña",
    "administración",
]

def _norm_list(values: Optional[Iterable[str]]) -> List[str]:
    out: List[str] = []
    if not values:
        return out
    for v in values:
        if not v:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out

def build_query_variants(
    actor: str,
    city_keywords: Optional[Iterable[str]] = None,
    extras: Optional[Iterable[str]] = None,
) -> List[str]:
    """
    Devuelve variantes de búsqueda OPTIMIZADAS para evitar resultados irrelevantes.
    Prioriza: "actor + ciudad + puesto" > "actor + puesto" > "actor + ciudad"
    """
    a = (actor or "").strip()
    if not a:
        return []

    cities = _norm_list(city_keywords)
    extra_words = _norm_list(extras)

    ordered: List[str] = []
    seen: set[str] = set()

    def add(s: str):
        s2 = s.strip()
        if not s2:
            return
        if s2 not in seen:
            seen.add(s2)
            ordered.append(s2)

    # ============================================
    # PRIORIDAD 1: Actor + Rol + Ciudad (MÁS ESPECÍFICO)
    # ============================================
    for c in cities:
        for r in ROLE_KEYWORDS:
            # Con comillas para búsqueda exacta del nombre
            add(f'"{a}" {r} {c}')
            # Sin comillas para más flexibilidad
            add(f'{a} {r} {c}')

    # ============================================
    # PRIORIDAD 2: Actor + Partido + Ciudad
    # ============================================
    for c in cities:
        for p in PARTY_KEYWORDS:
            add(f'"{a}" {p} {c}')
            add(f'{a} {p} {c}')

    # ============================================
    # PRIORIDAD 3: Actor + Rol (sin ciudad pero con contexto)
    # ============================================
    for r in ROLE_KEYWORDS:
        add(f'"{a}" {r}')
        add(f'{a} {r}')

    # ============================================
    # PRIORIDAD 4: Actor + Ciudad + Contexto político
    # ============================================
    for c in cities:
        add(f'"{a}" política {c}')
        add(f'{a} gobierno {c}')
        add(f'{a} {c}')

    # ============================================
    # PRIORIDAD 5: Actor + Partido (sin ciudad)
    # ============================================
    for p in PARTY_KEYWORDS:
        add(f'"{a}" {p}')

    # ============================================
    # PRIORIDAD 6: Extras específicos
    # ============================================
    for x in extra_words:
        add(f'"{a}" {x}')
        for c in cities:
            add(f'"{a}" {x} {c}')

    # ============================================
    # ÚLTIMA OPCIÓN: Actor solo (con comillas para exactitud)
    # ============================================
    add(f'"{a}"')
    
    # Solo si es necesario, actor sin comillas
    # (esto puede traer más ruido)
    if len(ordered) < 10:
        add(a)

    return ordered

def get_name_variations(name: str) -> List[str]:
    """
    Genera variaciones del nombre del actor.
    Optimizado para nombres políticos mexicanos.
    """
    parts = name.split()
    variations = []
    
    # Nombre completo
    variations.append(name)
    
    if len(parts) >= 2:
        # Primer nombre + Apellido paterno
        variations.append(f"{parts[0]} {parts[-1]}")
        
        # Solo apellido paterno (si es distintivo)
        if len(parts[-1]) > 4:  # Evitar apellidos muy cortos
            variations.append(parts[-1])
        
        # Primer nombre + inicial del apellido
        variations.append(f"{parts[0]} {parts[-1][0]}.")
    
    if len(parts) == 1:
        variations.append(parts[0])
    
    # Remover duplicados manteniendo orden
    seen = set()
    unique_variations = []
    for v in variations:
        if v not in seen:
            seen.add(v)
            unique_variations.append(v)
    
    return unique_variations

def build_basic_query(
    actor: str, 
    campaign_name: str | None = None, 
    city_keywords: Optional[Iterable[str]] = None
) -> str:
    """
    Construye una consulta ESPECÍFICA para Perplexity.
    Usa OR para variaciones del nombre + AND para contexto.
    
    Ejemplo resultado:
    ("Samuel Garcia" OR "Samuel G." OR "Garcia") AND (alcalde OR candidato) AND Monterrey
    """
    a = (actor or "").strip()
    if not a:
        return ""

    # ============================================
    # 1. VARIACIONES DEL NOMBRE (con OR)
    # ============================================
    name_variations = get_name_variations(a)
    # Usar comillas para búsqueda exacta
    quoted_variations = [f'"{v}"' for v in name_variations]
    name_query = f"({' OR '.join(quoted_variations)})"

    # ============================================
    # 2. DETECTAR ROL del campaign_name
    # ============================================
    role = None
    if campaign_name:
        name_lower = campaign_name.lower()
        for r in ROLE_KEYWORDS:
            if r in name_lower:
                role = r
                break

    # ============================================
    # 3. CIUDAD de city_keywords
    # ============================================
    city = None
    for c in _norm_list(city_keywords):
        city = c
        break

    # ============================================
    # 4. CONSTRUIR QUERY FINAL
    # ============================================
    query_parts = [name_query]
    
    # Agregar contexto político para mejorar relevancia
    if role:
        query_parts.append(role)
    else:
        # Si no hay rol, agregar contexto político genérico
        query_parts.append("política OR gobierno OR candidato")
    
    if city:
        query_parts.append(city)
    
    # Unir con AND implícito (espacio)
    final_query = " ".join(query_parts)
    
    print(f"🔍 Query construido: {final_query}")
    return final_query

# ============================================
# NUEVA FUNCIÓN: Validar query
# ============================================
def validate_query(query: str) -> bool:
    """
    Valida que el query tenga suficiente especificidad.
    Retorna True si el query es válido, False si es muy genérico.
    """
    if not query or len(query) < 3:
        return False
    
    # Palabras genéricas que NO deberían ser el único contenido
    generic_words = {
        'política', 'gobierno', 'elecciones', 'noticias',
        'méxico', 'mexico', 'nacional', 'estatal'
    }
    
    query_words = set(query.lower().split())
    
    # Si solo tiene palabras genéricas, rechazar
    if query_words.issubset(generic_words):
        return False
    
    return True

__all__ = [
    "build_query_variants",
    "build_basic_query",
    "get_name_variations",
    "validate_query",
]