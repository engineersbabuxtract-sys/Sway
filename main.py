#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Python server that:
1. Serves the index.html frontend
2. Acts as CORS proxy for SelectionWay API
3. Proxies video segments for HLS playback
"""

import os
import sys
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin

import aiohttp
from aiohttp import web

# ─── Configuration ───────────────────────────────────────────────────────────

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

# ─── HTML Template ───────────────────────────────────────────────────────────

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ─── API Proxy Handler ───────────────────────────────────────────────────────

async def proxy_handler(request):
    """Proxy API requests to SelectionWay, bypassing CORS."""
    
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint parameter"}, status=400)
    
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

# ─── Video Proxy Handler (for HLS segments) ──────────────────────────────────

async def video_proxy_handler(request):
    """
    Proxy video segments and m3u8 playlists.
    This handles CORS for HLS video playback.
    """
    video_url = request.query.get("url", "")
    if not video_url:
        return web.Response(text="Missing url parameter", status=400)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://www.selectionway.com/",
        "Origin": "https://www.selectionway.com",
    }
    
    # Copy relevant headers from original request
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]
    
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(video_url, ssl=False) as resp:
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                response_headers = {
                    "Content-Type": content_type,
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Range",
                    "Cache-Control": "public, max-age=3600",
                }
                
                # Pass through content-range for partial content
                if "Content-Range" in resp.headers:
                    response_headers["Content-Range"] = resp.headers["Content-Range"]
                if "Content-Length" in resp.headers:
                    response_headers["Content-Length"] = resp.headers["Content-Length"]
                
                # Read the body
                body = await resp.read()
                
                # If it's an m3u8 playlist, rewrite the URLs to use our proxy
                if ".m3u8" in video_url.lower() or content_type and "mpegurl" in content_type.lower():
                    body_text = body.decode("utf-8", errors="ignore")
                    # Rewrite relative URLs to go through our proxy
                    base_url = video_url.rsplit("/", 1)[0] + "/"
                    proxy_base = f"/api/video?url="
                    
                    lines = body_text.split("\n")
                    new_lines = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # It's a segment URL
                            if line.startswith("http"):
                                segment_url = line
                            else:
                                segment_url = urljoin(base_url, line)
                            new_lines.append(f"{proxy_base}{segment_url}")
                        else:
                            new_lines.append(line)
                    
                    body = "\n".join(new_lines).encode("utf-8")
                
                resp_status = resp.status if resp.status == 206 else 200
                return web.Response(body=body, status=resp_status, headers=response_headers)
                
    except Exception as e:
        print(f"Video proxy error: {e}")
        return web.Response(text=f"Proxy error: {str(e)}", status=500)

# ─── CORS Preflight Handler ──────────────────────────────────────────────────

async def cors_preflight(request):
    """Handle CORS preflight requests."""
    return web.Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Range, Authorization",
            "Access-Control-Max-Age": "86400",
        }
    )

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

# ─── CORS Middleware ─────────────────────────────────────────────────────────

@web.middleware
async def cors_middleware(request, handler):
    """Add CORS headers to all responses."""
    if request.method == "OPTIONS":
        return await cors_preflight(request)
    
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Range"
    return response

# ─── Application Setup ───────────────────────────────────────────────────────

def create_app():
    """Create and configure the aiohttp application."""
    app = web.Application(middlewares=[cors_middleware])
    
    # Routes
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_get("/api/video", video_proxy_handler)
    app.router.add_options("/api/video", cors_preflight)
    app.router.add_options("/api/proxy", cors_preflight)
    
    return app

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    """Start the web server."""
    print(f"""
╔══════════════════════════════════════╗
║  Engineers Babu - Koyeb Edition      ║
║  API + Video Proxy Server            ║
╚══════════════════════════════════════╝
    """)
    
    app = create_app()
    
    print(f"🚀 Starting server on port {PORT}")
    print(f"📡 API Proxy: /api/proxy")
    print(f"🎬 Video Proxy: /api/video")
    print(f"🌐 Health: http://0.0.0.0:{PORT}/health")
    print(f"📱 App: http://0.0.0.0:{PORT}/")
    
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
