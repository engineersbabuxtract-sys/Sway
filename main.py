#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
API proxy + Email OTP sending via Gmail SMTP.
"""

import os
import sys
import json
import asyncio
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

import aiohttp
from aiohttp import web, ClientTimeout, TCPConnector

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

# Email configuration (set in Koyeb environment variables)
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")      # your@gmail.com
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # Gmail app password

def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

def send_email(to_email, code):
    """Send OTP via Gmail SMTP."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("⚠️ SMTP not configured. OTP:", code)
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg["Subject"] = "Engineers Babu - Verification Code"

        body = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
            <h2 style="color:#2955c9;">Engineers Babu</h2>
            <p>Your verification code is:</p>
            <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
            <p>This code expires in 5 minutes.</p>
            <p style="color:#5b6478;font-size:12px;">If you didn't request this, ignore this email.</p>
        </div>
        """

        msg.attach(MIMEText(body, "html"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        print(f"✅ OTP sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

async def send_otp_handler(request):
    """Handle OTP sending request."""
    email = request.query.get("email", "")
    code = request.query.get("code", "")

    if not email or not code:
        return web.json_response({"sent": False, "error": "Missing email or code"}, status=400)

    sent = send_email(email, code)
    return web.json_response({"sent": sent})

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
    app.router.add_get("/api/send-otp", send_otp_handler)
    return app

def main():
    print("🚀 Engineers Babu starting...")
    if not SMTP_EMAIL:
        print("⚠️ SMTP not configured. Set SMTP_EMAIL and SMTP_PASSWORD env vars.")
        print("   OTP codes will be shown in console (demo mode).")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
