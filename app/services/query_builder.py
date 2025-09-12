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
    Devuelve variantes de búsqueda combinando:
    - Nombre exacto
    - Nombre + cargos típicos
    - Nombre + partidos
    - Nombre + ciudades/estados
    - Combinaciones con cargos/partidos + ciudad
    - Extras provistos por el usuario, opcionalmente combinados con ciudad
    Quita duplicados y ordena por longitud ascendente (más precisos primero).
    """
    a = (actor or "").strip()
    if not a:
        return []

    cities = _norm_list(city_keywords)
    extra_words = _norm_list(extras)

    variants: set[str] = set()

    # Base: nombre en varias formas
    variants.add(a)
    variants.add(f'"{a}"')

    # Nombre + roles
    for r in ROLE_KEYWORDS:
        variants.add(f"{a} {r}")
    # Nombre + partidos
    for p in PARTY_KEYWORDS:
        variants.add(f"{a} {p}")

    # Nombre + ciudades
    for c in cities:
        variants.add(f"{a} {c}")
        for r in ROLE_KEYWORDS:
            variants.add(f"{a} {r} {c}")
        for p in PARTY_KEYWORDS:
            variants.add(f"{a} {p} {c}")

    # Extras
    for x in extra_words:
        variants.add(f"{a} {x}")
        for c in cities:
            variants.add(f"{a} {x} {c}")

    # Ordena por longitud (más cortas primero) y quita duplicados conservando orden
    ordered = sorted(variants, key=lambda s: (len(s), s.lower()))
    return ordered


__all__ = ["build_query_variants"]

