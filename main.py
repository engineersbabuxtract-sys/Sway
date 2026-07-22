#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Single Python server that:
1. Serves the index.html frontend
2. Acts as CORS proxy for SelectionWay API
3. Handles all API requests without CORS issues
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

import aiohttp
from aiohttp import web

# ─── Configuration ───────────────────────────────────────────────────────────

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

# ─── HTML Template (embedded) ────────────────────────────────────────────────

def get_html():
    """Read index.html from file or return embedded version."""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ─── API Proxy Handler ───────────────────────────────────────────────────────

async def proxy_handler(request):
    """Proxy API requests to SelectionWay, bypassing CORS."""
    
    # Get target endpoint from query
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint parameter"}, status=400)
    
    # Get additional params
    params = dict(request.query)
    params.pop("endpoint", None)
    params["userId"] = USER_ID
    
    # Build full URL
    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.selectionway.com/",
        "Origin": "https://www.selectionway.com",
    }
    
    # Retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                async with session.get(target_url, params=params, ssl=False) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2)
                        continue
                    
                    data = await resp.json()
                    
                    return web.json_response(data, status=resp.status)
                    
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                return web.json_response({"error": "Request timeout"}, status=504)
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                return web.json_response({"error": str(e)}, status=500)
    
    return web.json_response({"error": "Max retries exceeded"}, status=500)

# ─── Main HTML Handler ───────────────────────────────────────────────────────

async def index_handler(request):
    """Serve the main HTML page."""
    html = get_html()
    return web.Response(text=html, content_type="text/html")

# ─── Health Check ────────────────────────────────────────────────────────────

async def health_handler(request):
    """Health check endpoint for Koyeb."""
    return web.json_response({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "app": "Engineers Babu",
        "api": API_BASE
    })

# ─── Application Setup ───────────────────────────────────────────────────────

def create_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    
    # Routes
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    
    # Serve static files if needed
    app.router.add_static("/static/", path=Path(__file__).parent, show_index=False)
    
    return app

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    """Start the web server."""
    print(f"""
╔══════════════════════════════════════╗
║  Engineers Babu - Koyeb Edition      ║
║  API Proxy + Frontend Server         ║
╚══════════════════════════════════════╝
    """)
    
    app = create_app()
    
    print(f"🚀 Starting server on port {PORT}")
    print(f"📡 API Base: {API_BASE}")
    print(f"🌐 Health check: http://0.0.0.0:{PORT}/health")
    print(f"📱 App: http://0.0.0.0:{PORT}/")
    print(f"🔄 Proxy: http://0.0.0.0:{PORT}/api/proxy?endpoint=courses/active")
    
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
