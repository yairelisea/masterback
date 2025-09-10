from typing import List, Dict, Any

def score_item(item: Dict[str, Any], aliases: List[str], city_keywords: List[str] | None = None) -> float:
    """
    Soft ranking:
    - exact/alias mention in title (5), in snippet (3)
    - city/region in title (2), in snippet (1)
    """
    title = (item.get("title") or "").lower()
    snip  = (item.get("snippet") or "").lower()
    s = 0.0

    for a in aliases:
        al = a.lower()
        if al and al in title:
            s += 5.0
        elif al and al in snip:
            s += 3.0

    for c in (city_keywords or []):
        cl = (c or "").lower()
        if cl and cl in title:
            s += 2.0
        elif cl and cl in snip:
            s += 1.0

    return s