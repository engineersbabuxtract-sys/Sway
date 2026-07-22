#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
With detailed error logging for debugging.
"""

import os
import sys
import json
import asyncio
import random
import traceback
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, quote, unquote

import aiohttp
from aiohttp import web

# ─── Configuration ───────────────────────────────────────────────────────────

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

def get_random_ua():
    return random.choice(USER_AGENTS)

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ─── Headers ─────────────────────────────────────────────────────────────────

def get_browser_headers():
    return {
        "User-Agent": get_random_ua(),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.selectionway.com/",
        "Origin": "https://www.selectionway.com",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

# ─── API Proxy ───────────────────────────────────────────────────────────────

async def proxy_handler(request):
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint"}, status=400)

    params = dict(request.query)
    params.pop("endpoint", None)
    params["userId"] = USER_ID

    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    headers = get_browser_headers()

    for attempt in range(3):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
                async with session.get(target_url, params=params, allow_redirects=True) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(random.uniform(2, 5))
                        continue
                    data = await resp.json()
                    return web.json_response(data, status=resp.status)
        except Exception as e:
            print(f"API ERROR (attempt {attempt+1}): {e}")
            if attempt == 2:
                return web.json_response({"error": str(e)}, status=500)
            await asyncio.sleep(random.uniform(1, 3))

    return web.json_response({"error": "Max retries"}, status=500)

# ─── Video Proxy (WITH FULL ERROR LOGGING) ───────────────────────────────────

async def video_proxy_handler(request):
    video_url = request.query.get("url", "")
    if not video_url:
        return web.Response(text="Missing url", status=400)

    # URL might be double-encoded, decode it
    video_url = unquote(video_url)
    
    print(f"\n{'='*60}")
    print(f"🎬 VIDEO PROXY REQUEST")
    print(f"📡 URL: {video_url[:150]}")
    print(f"{'='*60}")

    headers = get_browser_headers()
    headers.update({
        "Accept": "*/*",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    })

    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=15)
        connector = aiohttp.TCPConnector(ssl=False, force_close=True, ttl_dns_cache=300)

        print(f"🔗 Connecting to: {video_url[:100]}...")
        
        async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
            async with session.get(video_url, allow_redirects=True) as resp:
                
                print(f"📥 Response Status: {resp.status}")
                print(f"📋 Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
                
                if resp.status != 200 and resp.status != 206:
                    body_text = await resp.text()
                    print(f"❌ Error Body: {body_text[:500]}")
                    return web.Response(
                        text=f"Upstream returned {resp.status}: {body_text[:200]}",
                        status=resp.status,
                        headers={"Access-Control-Allow-Origin": "*"}
                    )

                content_type = resp.headers.get("Content-Type", "application/octet-stream")

                response_headers = {
                    "Content-Type": content_type,
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "*",
                    "Cache-Control": "public, max-age=3600",
                    "Accept-Ranges": "bytes",
                }

                for h in ["Content-Range", "Content-Length", "Accept-Ranges", "ETag"]:
                    if h in resp.headers:
                        response_headers[h] = resp.headers[h]

                body = await resp.read()
                print(f"📦 Body size: {len(body)} bytes")

                # Rewrite m3u8
                is_m3u8 = ".m3u8" in video_url.lower() or (content_type and "mpegurl" in content_type.lower())

                if is_m3u8:
                    try:
                        body_text = body.decode("utf-8", errors="ignore")
                        print(f"📝 m3u8 content (first 300 chars):\n{body_text[:300]}")
                        
                        base_url = video_url.rsplit("/", 1)[0] + "/"
                        lines = body_text.split("\n")
                        new_lines = []
                        segment_count = 0

                        for line in lines:
                            stripped = line.strip()
                            if not stripped or stripped.startswith("#"):
                                new_lines.append(line)
                                continue
                            if stripped.startswith("/api/video"):
                                new_lines.append(line)
                                continue
                            if stripped.startswith("http"):
                                segment_url = stripped
                            else:
                                segment_url = urljoin(base_url, stripped)
                            
                            new_lines.append(f"/api/video?url={quote(segment_url, safe='')}")
                            segment_count += 1

                        body = "\n".join(new_lines).encode("utf-8")
                        response_headers["Content-Length"] = str(len(body))
                        print(f"✅ Rewrote {segment_count} segments")
                        
                    except Exception as e:
                        print(f"⚠️ m3u8 rewrite error: {e}")
                        traceback.print_exc()

                print(f"✅ Sending response ({len(body)} bytes)")
                return web.Response(body=body, status=200, headers=response_headers)

    except asyncio.TimeoutError:
        print("⏰ TIMEOUT")
        return web.Response(text="Timeout fetching video", status=504, headers={"Access-Control-Allow-Origin": "*"})
    except aiohttp.ClientError as e:
        print(f"🌐 CLIENT ERROR: {e}")
        traceback.print_exc()
        return web.Response(text=f"Connection error: {str(e)}", status=502, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        print(f"💥 UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        return web.Response(text=f"Server error: {str(e)}", status=500, headers={"Access-Control-Allow-Origin": "*"})

# ─── CORS ────────────────────────────────────────────────────────────────────

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        })
    try:
        response = await handler(request)
    except Exception as e:
        print(f"💥 MIDDLEWARE ERROR: {e}")
        traceback.print_exc()
        response = web.Response(text=str(e), status=500)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# ─── Routes ──────────────────────────────────────────────────────────────────

async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def health_handler(request):
    return web.json_response({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ─── App ─────────────────────────────────────────────────────────────────────

def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_get("/api/video", video_proxy_handler)
    return app

def main():
    print("""
╔══════════════════════════════════════╗
║  Engineers Babu - Debug Edition      ║
╚══════════════════════════════════════╝
    """)
    app = create_app()
    print(f"🚀 Port: {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
