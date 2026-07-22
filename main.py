#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Full browser simulation to bypass CloudFlare.
"""

import os
import sys
import json
import asyncio
import random
import ssl
import traceback
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, quote, unquote

import aiohttp
from aiohttp import web, ClientTimeout, TCPConnector

# ─── Configuration ───────────────────────────────────────────────────────────

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

# Real Chrome headers (exactly what a browser sends)
CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="150", "Google Chrome";v="150", "Not.A/Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ─── API Proxy ───────────────────────────────────────────────────────────────

async def proxy_handler(request):
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint"}, status=400)

    params = dict(request.query)
    params.pop("endpoint", None)
    params["userId"] = USER_ID

    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    headers = dict(CHROME_HEADERS)
    headers["Referer"] = "https://www.selectionway.com/"
    headers["Origin"] = "https://www.selectionway.com"

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

# ─── Video Proxy ─────────────────────────────────────────────────────────────

async def video_proxy_handler(request):
    video_url = request.query.get("url", "")
    if not video_url:
        return web.Response(text="Missing url", status=400)

    video_url = unquote(video_url)
    
    print(f"\n🎬 PROXY: {video_url[:120]}...")

    # Use EXACT browser headers
    headers = dict(CHROME_HEADERS)
    headers.update({
        "Accept": "*/*",
        "Referer": "https://www.selectionway.com/",
        "Origin": "https://www.selectionway.com",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    })

    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    try:
        timeout = ClientTimeout(total=120, connect=15)
        connector = TCPConnector(
            ssl=False,           # Don't verify SSL
            force_close=True,     # Fresh connection
            ttl_dns_cache=300,
            limit=10,
        )

        # Create cookie jar to accept cookies
        jar = aiohttp.CookieJar(unsafe=True)
        
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector,
            cookie_jar=jar,
        ) as session:
            
            print(f"🔗 Fetching: {video_url[:100]}...")
            
            async with session.get(
                video_url,
                allow_redirects=True,
                max_redirects=10,
            ) as resp:
                
                print(f"📥 Status: {resp.status}")
                print(f"📋 Type: {resp.headers.get('Content-Type','?')[:50]}")
                
                # Check if we got HTML instead of video (CloudFlare block)
                ct = resp.headers.get("Content-Type", "")
                if "text/html" in ct and resp.status == 200:
                    body = await resp.text()
                    print(f"❌ Got HTML instead of video! ({len(body)} bytes)")
                    print(f"📄 HTML preview: {body[:300]}")
                    return web.Response(
                        text=f"CloudFlare blocked: got HTML page instead of video. Body: {body[:500]}",
                        status=502,
                        headers={"Access-Control-Allow-Origin": "*"}
                    )
                
                if resp.status != 200 and resp.status != 206:
                    body_text = await resp.text()
                    print(f"❌ Upstream error {resp.status}: {body_text[:200]}")
                    return web.Response(
                        text=f"Upstream {resp.status}: {body_text[:200]}",
                        status=502,
                        headers={"Access-Control-Allow-Origin": "*"}
                    )

                content_type = ct or "application/octet-stream"

                response_headers = {
                    "Content-Type": content_type,
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "*",
                    "Cache-Control": "public, max-age=3600",
                    "Accept-Ranges": "bytes",
                }

                for h in ["Content-Range", "Content-Length", "Accept-Ranges", "ETag", "Last-Modified"]:
                    if h in resp.headers:
                        response_headers[h] = resp.headers[h]

                body = await resp.read()
                print(f"📦 Body: {len(body)} bytes")

                # Rewrite m3u8
                is_m3u8 = ".m3u8" in video_url.lower() or "mpegurl" in content_type.lower()

                if is_m3u8 and len(body) < 100000:  # Only rewrite if it's a playlist (not a huge file)
                    try:
                        body_text = body.decode("utf-8", errors="ignore")
                        
                        # Check if it's actually HTML
                        if body_text.strip().startswith("<"):
                            print(f"❌ m3u8 is actually HTML! CloudFlare block confirmed.")
                            return web.Response(
                                text=f"CloudFlare returned HTML: {body_text[:500]}",
                                status=502,
                                headers={"Access-Control-Allow-Origin": "*"}
                            )
                        
                        print(f"📝 First 200 chars:\n{body_text[:200]}")
                        
                        base_url = video_url.rsplit("/", 1)[0] + "/"
                        lines = body_text.split("\n")
                        new_lines = []
                        count = 0

                        for line in lines:
                            stripped = line.strip()
                            if not stripped or stripped.startswith("#"):
                                new_lines.append(line)
                                continue
                            if stripped.startswith("/api/video"):
                                new_lines.append(line)
                                continue
                            
                            if stripped.startswith("http"):
                                seg = stripped
                            else:
                                seg = urljoin(base_url, stripped)
                            
                            new_lines.append(f"/api/video?url={quote(seg, safe='')}")
                            count += 1

                        body = "\n".join(new_lines).encode("utf-8")
                        response_headers["Content-Length"] = str(len(body))
                        print(f"✅ Rewrote {count} segments")
                        
                    except Exception as e:
                        print(f"⚠️ Rewrite error: {e}")

                print(f"✅ Done ({len(body)} bytes)")
                return web.Response(body=body, status=200, headers=response_headers)

    except asyncio.TimeoutError:
        return web.Response(text="Timeout", status=504, headers={"Access-Control-Allow-Origin": "*"})
    except aiohttp.ClientError as e:
        print(f"🌐 Error: {e}")
        return web.Response(text=str(e), status=502, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        print(f"💥 Error: {e}")
        traceback.print_exc()
        return web.Response(text=str(e), status=500, headers={"Access-Control-Allow-Origin": "*"})

# ─── CORS ────────────────────────────────────────────────────────────────────

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        })
    try:
        response = await handler(request)
    except Exception as e:
        response = web.Response(text=str(e), status=500)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# ─── Routes ──────────────────────────────────────────────────────────────────

async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def health_handler(request):
    return web.json_response({"status": "healthy"})

# ─── App ─────────────────────────────────────────────────────────────────────

def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_get("/api/video", video_proxy_handler)
    return app

def main():
    print("🚀 Engineers Babu starting...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
