
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

PARTY_KEYWORDS = ["morena", "pan", "pri", "prd", "mc", "verde", "pt"]

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
    Devuelve variantes de búsqueda con priorización para
    "actor + ciudad + puesto" como las primeras opciones.
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

    # 1) Prioridad: actor + rol + ciudad
    for c in cities:
        for r in ROLE_KEYWORDS:
            add(f'{a} {r} {c}')
            add(f'"{a}" {r} {c}')

    # 2) actor + partido + ciudad
    for c in cities:
        for p in PARTY_KEYWORDS:
            add(f'{a} {p} {c}')
            add(f'"{a}" {p} {c}')

    # 3) actor + ciudad
    for c in cities:
        add(f'{a} {c}')
        add(f'"{a}" {c}')

    # 4) actor + rol (sin ciudad)
    for r in ROLE_KEYWORDS:
        add(f'{a} {r}')
        add(f'"{a}" {r}')

    # 5) actor + partido (sin ciudad)
    for p in PARTY_KEYWORDS:
        add(f'{a} {p}')
        add(f'"{a}" {p}')

    # 6) extras
    for x in extra_words:
        add(f'{a} {x}')
        add(f'"{a}" {x}')
        for c in cities:
            add(f'{a} {x} {c}')
            add(f'"{a}" {x} {c}')

    # 7) base
    add(a)
    add(f'"{a}"')

    return ordered

def get_name_variations(name: str) -> List[str]:
    """
    Genera variaciones de un nombre (nombre completo, nombre + apellido, etc.)
    """
    parts = name.split()
    if len(parts) > 1:
        return [name, f"{parts[0]} {parts[-1]}", parts[0], parts[-1]]
    return [name]

def build_basic_query(
    actor: str, 
    campaign_name: str | None = None, 
    city_keywords: Optional[Iterable[str]] = None,
    country: str = "MX",
    require_exact_match: bool = True
) -> str:
    """
    ✅ Construye query ESPECÍFICO con operadores booleanos para Perplexity
    
    Ejemplo:
    Entrada: actor="Marcelo Abundiz", city_keywords=["Tamaulipas", "Altamira"]
    Salida: "Marcelo Abundiz" AND (diputado OR diputada) AND ("Tamaulipas" OR "Altamira") AND (México OR Mexicano)
    """
    import re
    
    a = (actor or "").strip()
    if not a:
        return ""

    # ✅ Detectar rol del nombre de campaña
    role = None
    name_lower = (campaign_name or "").lower()
    
    role_map = {
        "alcalde": "alcalde OR presidente municipal",
        "alcaldesa": "alcaldesa OR presidenta municipal",
        "diputado": "diputado OR diputada",
        "senador": "senador OR senadora",
        "gobernador": "gobernador OR gobernadora",
    }
    
    for keyword, expanded in role_map.items():
        if keyword in name_lower:
            role = expanded
            break
    
    # ✅ Construir query con operadores booleanos
    query_parts = []
    
    # Nombre exacto con comillas (obligatorio)
    if require_exact_match:
        query_parts.append(f'"{a}"')
    else:
        # Alternativa: variaciones del nombre
        name_vars = get_name_variations(a)
        query_parts.append(f"({' OR '.join(name_vars)})")
    
    # Rol (si se detectó)
    if role:
        query_parts.append(f"AND ({role})")
    
    # Ciudad/región (crítico para relevancia)
    cities = _norm_list(city_keywords)
    if cities:
        city_query = " OR ".join([f'"{c}"' for c in cities[:3]])  # Top 3 ciudades
        query_parts.append(f"AND ({city_query})")
    
    # País (ayuda con relevancia)
    if country:
        country_names = {
            "MX": "México OR Mexicano OR Mexicana",
            "US": "Estados Unidos OR USA",
        }
        if country in country_names:
            query_parts.append(f"AND ({country_names[country]})")
    
    final_query = " ".join(query_parts)
    return final_query

__all__ = ["build_query_variants", "build_basic_query", "get_name_variations"]