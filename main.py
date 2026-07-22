#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Spoofs real browser to bypass SelectionWay blocks.
"""

import os
import sys
import json
import asyncio
import random
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import aiohttp
from aiohttp import web

# ─── Configuration ───────────────────────────────────────────────────────────

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

# Spoofed browser fingerprints
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

# Spoofed IP ranges (common Indian ISP IPs - these are fake examples)
# CloudFront checks X-Forwarded-For and client IP
SPOOF_IPS = [
    "103.15.60.{}",
    "117.200.80.{}",
    "157.50.100.{}",
    "42.106.120.{}",
]

def get_random_ip():
    template = random.choice(SPOOF_IPS)
    return template.format(random.randint(2, 254))

def get_random_ua():
    return random.choice(USER_AGENTS)

# ─── HTML ────────────────────────────────────────────────────────────────────

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ─── Browser-like Headers ────────────────────────────────────────────────────

def get_browser_headers(video_url=""):
    """Generate headers that look exactly like a real browser."""
    
    # Parse domain for Referer
    domain = "https://www.selectionway.com/"
    if "cloudfront" in video_url:
        domain = "https://www.selectionway.com/"
    elif "gdgoenkaratia" in video_url:
        domain = "https://gdgoenkaratia.com/"
    
    return {
        "User-Agent": get_random_ua(),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": domain,
        "Origin": domain.rstrip("/"),
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
    }

# ─── API Proxy ───────────────────────────────────────────────────────────────

async def proxy_handler(request):
    """Proxy API requests with browser spoofing."""
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint"}, status=400)
    
    params = dict(request.query)
    params.pop("endpoint", None)
    params["userId"] = USER_ID
    
    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    
    # Use spoofed browser headers
    headers = get_browser_headers()
    
    for attempt in range(3):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(
                ssl=False,
                force_close=True,  # Fresh connection each time
                enable_cleanup_closed=True,
            )
            async with aiohttp.ClientSession(
                headers=headers, 
                timeout=timeout,
                connector=connector,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            ) as session:
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
    """
    Proxy video with complete browser spoofing.
    Mimics a real Chrome browser playing video.
    """
    video_url = request.query.get("url", "")
    if not video_url:
        return web.Response(text="Missing url", status=400)
    
    # Get spoofed browser headers
    headers = get_browser_headers(video_url)
    
    # Forward Range header for partial content
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]
    
    # Add typical browser video headers
    headers.update({
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    })
    
    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        connector = aiohttp.TCPConnector(
            ssl=False,
            force_close=True,
            enable_cleanup_closed=True,
            ttl_dns_cache=300,
        )
        
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        ) as session:
            async with session.get(video_url, allow_redirects=True) as resp:
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                
                response_headers = {
                    "Content-Type": content_type,
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Range, Origin",
                    "Access-Control-Expose-Headers": "Content-Length, Content-Range",
                    "Cache-Control": "public, max-age=3600",
                    "Accept-Ranges": "bytes",
                }
                
                # Pass through important headers
                for h in ["Content-Range", "Content-Length", "Accept-Ranges", "ETag", "Last-Modified"]:
                    if h in resp.headers:
                        response_headers[h] = resp.headers[h]
                
                body = await resp.read()
                
                # Rewrite m3u8 playlists
                is_m3u8 = (
                    ".m3u8" in video_url.lower() or 
                    (content_type and "mpegurl" in content_type.lower()) or
                    (content_type and "vnd.apple.mpegurl" in content_type.lower())
                )
                
                is_mpd = ".mpd" in video_url.lower()
                
                if is_m3u8 or is_mpd:
                    try:
                        body_text = body.decode("utf-8", errors="ignore")
                        base_url = video_url.rsplit("/", 1)[0] + "/"
                        
                        # Also resolve relative to parent
                        if "?" in base_url:
                            base_url = base_url.split("?")[0].rsplit("/", 1)[0] + "/"
                        
                        lines = body_text.split("\n")
                        new_lines = []
                        
                        for line in lines:
                            stripped = line.strip()
                            
                            # Keep comments and empty lines
                            if not stripped or stripped.startswith("#"):
                                new_lines.append(line)
                                continue
                            
                            # Skip if already proxied
                            if stripped.startswith("/api/video"):
                                new_lines.append(line)
                                continue
                            
                            # Resolve URL
                            if stripped.startswith("http"):
                                segment_url = stripped
                            else:
                                # Try different resolution methods
                                segment_url = urljoin(base_url, stripped)
                                if not segment_url.startswith("http"):
                                    # Try parent directory
                                    parent_base = base_url.rsplit("/", 2)[0] + "/"
                                    segment_url = urljoin(parent_base, stripped)
                            
                            # Proxy through our server
                            proxy_url = f"/api/video?url={segment_url}"
                            new_lines.append(proxy_url)
                        
                        body = "\n".join(new_lines).encode("utf-8")
                        response_headers["Content-Length"] = str(len(body))
                        
                    except Exception as e:
                        print(f"m3u8 rewrite error: {e}")
                        # If rewrite fails, still serve original
                        pass
                
                return web.Response(
                    body=body,
                    status=resp.status,
                    headers=response_headers
                )
                
    except asyncio.TimeoutError:
        return web.Response(text="Video request timeout", status=504)
    except aiohttp.ClientError as e:
        print(f"Video fetch error: {e}")
        return web.Response(text=f"Fetch error: {str(e)}", status=502)
    except Exception as e:
        print(f"Video proxy error: {e}")
        return web.Response(text=f"Proxy error: {str(e)}", status=500)

# ─── Direct Stream Handler (for iframe fallback) ─────────────────────────────

async def stream_handler(request):
    """Handle OPTIONS preflight."""
    return web.Response(status=204, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Range",
    })

# ─── CORS Middleware ─────────────────────────────────────────────────────────

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Range, Origin, Accept",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",
        })
    
    try:
        response = await handler(request)
    except Exception as e:
        response = web.Response(text=str(e), status=500)
    
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# ─── Routes ──────────────────────────────────────────────────────────────────

async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def health_handler(request):
    return web.json_response({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "spoofed_ua": get_random_ua()[:50] + "...",
    })

# ─── App ─────────────────────────────────────────────────────────────────────

def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_get("/api/video", video_proxy_handler)
    app.router.add_options("/api/video", stream_handler)
    app.router.add_options("/api/proxy", stream_handler)
    return app

def main():
    print(f"""
╔══════════════════════════════════════╗
║  Engineers Babu - Browser Spoofing   ║
║  Mimics Real Chrome Browser          ║
╚══════════════════════════════════════╝
    """)
    app = create_app()
    print(f"🚀 Port: {PORT}")
    print(f"🕵️ UA Spoofing: {len(USER_AGENTS)} user agents")
    print(f"🌐 Referer: selectionway.com")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
