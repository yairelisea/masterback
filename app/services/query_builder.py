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

def get_name_variations(name: str) -> List[str]:
    """
    Generates a list of name variations for a given name.
    This is a simple implementation and can be expanded.
    """
    parts = name.split()
    if len(parts) > 1:
        return [name, f"{parts[0]} {parts[-1]}", parts[0], parts[-1]]
    return [name]

def build_basic_query(actor: str, campaign_name: str | None = None, city_keywords: Optional[Iterable[str]] = None) -> str:
    """
    Builds a more specific query for Perplexity using OR for name variations.
    """
    a = (actor or "").strip()
    if not a:
        return ""

    name_variations = get_name_variations(a)
    name_query = f"({' OR '.join(name_variations)})"

    role = None
    name = (campaign_name or "").lower()
    for r in ROLE_KEYWORDS:
        if r in name:
            role = r
            break

    city = None
    for c in _norm_list(city_keywords):
        city = c
        break

    query_parts = [name_query]
    if role:
        query_parts.append(role)
    if city:
        query_parts.append(city)

    return " ".join(query_parts)

__all__ = ["build_basic_query"]