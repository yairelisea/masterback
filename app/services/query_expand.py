import unicodedata
from typing import List, Optional

def _normalize(s: str) -> str:
    # Remove accents
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def expand_actor(actor: str, extra_aliases: Optional[List[str]] = None) -> List[str]:
    """
    Generates alias list for an actor, including an accent-insensitive variant.
    Deduplicates while preserving order.
    """
    base = [actor.strip()] if actor else []
    norm = _normalize(actor or "")
    if norm and norm.lower() != (actor or "").lower():
        base.append(norm)

    for a in (extra_aliases or []):
        a = a.strip()
        if a:
            base.append(a)
            n = _normalize(a)
            if n.lower() != a.lower():
                base.append(n)

    out, seen = [], set()
    for q in base:
        k = q.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out