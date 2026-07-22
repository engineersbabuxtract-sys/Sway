#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
API proxy only. Videos open in new tab (no CORS/CloudFlare issues).
"""

import os
import sys
import json
import asyncio
import random
from pathlib import Path
from datetime import datetime

import aiohttp
from aiohttp import web, ClientTimeout, TCPConnector

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

async def proxy_handler(request):
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint"}, status=400)

    params = dict(request.query)
    params.pop("endpoint", None)
    params["userId"] = USER_ID

    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.selectionway.com/",
        "Origin": "https://www.selectionway.com",
    }

    for attempt in range(3):
        try:
            timeout = ClientTimeout(total=30)
            connector = TCPConnector(ssl=False, force_close=True)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
                async with session.get(target_url, params=params, allow_redirects=True) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(random.uniform(2, 5))
                        continue
                    data = await resp.json()
                    return web.json_response(data, status=resp.status)
        except Exception as e:
            if attempt == 2:
                return web.json_response({"error": str(e)}, status=500)
            await asyncio.sleep(random.uniform(1, 3))

    return web.json_response({"error": "Max retries"}, status=500)

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        })
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def health_handler(request):
    return web.json_response({"status": "healthy"})

def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    return app

def main():
    print("🚀 Engineers Babu starting...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
