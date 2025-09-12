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

    # 6) extras (y extras + ciudad)
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


__all__ = ["build_query_variants"]
