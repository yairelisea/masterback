from __future__ import annotations
import os, asyncio, httpx

SELF_BASE = os.getenv("SELF_BASE_URL", "http://localhost:8000")

async def _post_json(client: httpx.AsyncClient, url: str, json: dict | None = None, headers: dict | None = None):
    resp = await client.post(url, json=json, headers=headers)
    return resp.status_code, (await resp.aread())

async def run_gn_local_analyses(token: str, campaign_id: str) -> dict:
    headers_nojson = {"Authorization": f"Bearer {token}"}
    headers_json   = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        code_local, _ = await _post_json(client, f"{SELF_BASE}/search-local/campaign/{campaign_id}", headers=headers_nojson)
        code_ingest, _ = await _post_json(client, f"{SELF_BASE}/ingest/ingest", json={"campaignId": campaign_id}, headers=headers_json)
        code_an, _     = await _post_json(client, f"{SELF_BASE}/analyses/ingest", json={"campaignId": campaign_id}, headers=headers_json)
    return {"local": code_local, "ingest": code_ingest, "analyses": code_an}

def run_gn_local_analyses_sync(token: str, campaign_id: str) -> dict:
    return asyncio.run(run_gn_local_analyses(token, campaign_id))