"""Exercise the actual API handler and real upstream without exposing configuration."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from apps.api.main import app


async def main():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.local"
    ) as client:
        response = await client.post("/ai/generate", json={
            "prompt": "Réponds en français : propose un titre court pour un article sur les jardins urbains.",
            "max_tokens": 64,
        })
    data = response.json()
    print(json.dumps({"http_status": response.status_code, "result": data}, ensure_ascii=False, indent=2))
    if response.status_code != 200:
        return 1
    if not isinstance(data.get("response"), str) or not data["response"].strip():
        return 1
    print("Contenu textuel non vide vérifié. Vérifier le modèle et la pertinence du texte ci-dessus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
