#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Full registration + login system with VIP access.
"""

import os
import sys
import json
import asyncio
import random
import hashlib
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

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

USERS_FILE = Path(__file__).parent / "users.json"
LOG_FILE = Path(__file__).parent / "login_log.txt"

# ═══════════ VIP ACCOUNT ═══════════
VIP_USERID = "Enggbabu8564"
VIP_PASSWORD = "gbabu8564"
VIP_DATA = {
    "userid": VIP_USERID,
    "password": hashlib.sha256(VIP_PASSWORD.encode()).hexdigest(),
    "name": "VIP Member",
    "email": "vip@engineersbabu.com",
    "mobile": "",
    "is_vip": True,
    "created": datetime.now().isoformat()
}

def load_users():
    if USERS_FILE.exists():
        data = json.loads(USERS_FILE.read_text())
    else:
        data = {"users": {}}
    
    # Always ensure VIP exists
    if VIP_USERID not in data["users"]:
        data["users"][VIP_USERID] = VIP_DATA
    
    return data

def save_users(data):
    USERS_FILE.write_text(json.dumps(data, indent=2))

def log_action(action, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {action} | {detail}\n")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_email(to_email, subject, body_html):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"❌ SMTP not configured")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

# ═══════════ TEMP STORAGE ═══════════
pending_registrations = {}  # email -> {code, user_data}
password_reset_codes = {}   # email -> {code, expires}

# ═══════════ HTML ═══════════
def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ═══════════ API HANDLERS ═══════════

async def send_registration_otp(request):
    """Send OTP for registration verification."""
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    
    email = data.get("email", "")
    name = data.get("name", "")
    mobile = data.get("mobile", "")
    password = data.get("password", "")
    
    if not all([email, name, password]):
        return web.json_response({"success": False, "error": "All fields required"})
    
    users = load_users()
    
    # Check if email already registered
    for uid, u in users["users"].items():
        if u.get("email") == email:
            return web.json_response({"success": False, "error": "Email already registered"})
    
    code = str(random.randint(100000, 999999))
    pending_registrations[email] = {
        "code": code,
        "expires": datetime.now().timestamp() + 300,
        "user_data": {"name": name, "email": email, "mobile": mobile, "password": hash_password(password)}
    }
    
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Engineers Babu</h2>
        <p>Hi {name},</p>
        <p>Your verification code for registration is:</p>
        <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
        <p>This code expires in 5 minutes.</p>
    </div>
    """
    
    sent = send_email(email, "Verify Your Registration", body)
    if not sent:
        print(f"\n📧 Registration OTP for {email}: {code}\n")
    
    log_action("REG_OTP_SENT", f"{name} <{email}>")
    return web.json_response({"success": True})

async def verify_registration_otp(request):
    """Verify registration OTP and create account."""
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    
    email = data.get("email", "")
    code = data.get("code", "")
    
    pending = pending_registrations.get(email)
    if not pending:
        return web.json_response({"success": False, "error": "No registration pending"})
    
    if datetime.now().timestamp() > pending["expires"]:
        del pending_registrations[email]
        return web.json_response({"success": False, "error": "Code expired"})
    
    if code != pending["code"]:
        return web.json_response({"success": False, "error": "Invalid code"})
    
    # Create user account
    user_data = pending["user_data"]
    userid = f"EB{random.randint(1000, 9999)}"
    
    # Ensure unique userid
    users = load_users()
    while userid in users["users"]:
        userid = f"EB{random.randint(1000, 9999)}"
    
    users["users"][userid] = {
        "userid": userid,
        "password": user_data["password"],
        "name": user_data["name"],
        "email": user_data["email"],
        "mobile": user_data["mobile"],
        "is_vip": False,
        "created": datetime.now().isoformat()
    }
    save_users(users)
    del pending_registrations[email]
    
    log_action("REGISTERED", f"{user_data['name']} <{email}> | UserID: {userid}")
    
    # Send welcome email with credentials
    welcome_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Welcome to Engineers Babu!</h2>
        <p>Hi {user_data['name']},</p>
        <p>Your account has been created successfully.</p>
        <div style="background:#f6f8fc;padding:15px;border-radius:10px;margin:15px 0;">
            <p><strong>User ID:</strong> {userid}</p>
        </div>
        <p>Use your User ID and password to login.</p>
    </div>
    """
    send_email(email, "Welcome to Engineers Babu!", welcome_body)
    
    return web.json_response({"success": True, "userid": userid})

async def login_handler(request):
    """Login with UserID + Password OR VIP credentials."""
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    
    userid = data.get("userid", "").strip()
    password = data.get("password", "")
    
    if not userid or not password:
        return web.json_response({"success": False, "error": "UserID and password required"})
    
    users = load_users()
    
    user = users["users"].get(userid)
    if not user:
        return web.json_response({"success": False, "error": "Invalid UserID or password"})
    
    if hash_password(password) != user["password"]:
        log_action("LOGIN_FAILED", f"UserID: {userid}")
        return web.json_response({"success": False, "error": "Invalid UserID or password"})
    
    log_action("LOGIN_SUCCESS", f"{user['name']} | UserID: {userid}")
    
    return web.json_response({
        "success": True,
        "userid": userid,
        "name": user["name"],
        "email": user["email"]
    })

async def forgot_password_handler(request):
    """Send reset code to email."""
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    
    email = data.get("email", "")
    users = load_users()
    
    # Find user by email
    found_userid = None
    found_name = None
    for uid, u in users["users"].items():
        if u.get("email") == email:
            found_userid = uid
            found_name = u["name"]
            break
    
    if not found_userid:
        return web.json_response({"success": False, "error": "Email not found"})
    
    code = str(random.randint(100000, 999999))
    password_reset_codes[email] = {
        "code": code,
        "expires": datetime.now().timestamp() + 300,
        "userid": found_userid
    }
    
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Engineers Babu - Password Reset</h2>
        <p>Hi {found_name},</p>
        <p>Your password reset code is:</p>
        <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
        <p>Your User ID: <strong>{found_userid}</strong></p>
        <p>This code expires in 5 minutes.</p>
    </div>
    """
    
    sent = send_email(email, "Password Reset Code", body)
    if not sent:
        print(f"\n📧 Reset code for {email}: {code}\n")
    
    log_action("PASSWORD_RESET", f"{found_name} <{email}>")
    return web.json_response({"success": True, "userid": found_userid})

async def reset_password_handler(request):
    """Reset password with code."""
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    
    email = data.get("email", "")
    code = data.get("code", "")
    new_password = data.get("password", "")
    
    reset = password_reset_codes.get(email)
    if not reset:
        return web.json_response({"success": False, "error": "No reset requested"})
    
    if datetime.now().timestamp() > reset["expires"]:
        del password_reset_codes[email]
        return web.json_response({"success": False, "error": "Code expired"})
    
    if code != reset["code"]:
        return web.json_response({"success": False, "error": "Invalid code"})
    
    users = load_users()
    users["users"][reset["userid"]]["password"] = hash_password(new_password)
    save_users(users)
    del password_reset_codes[email]
    
    log_action("PASSWORD_CHANGED", f"UserID: {reset['userid']}")
    return web.json_response({"success": True})

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
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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
    app.router.add_post("/api/register-otp", send_registration_otp)
    app.router.add_post("/api/register-verify", verify_registration_otp)
    app.router.add_post("/api/login", login_handler)
    app.router.add_post("/api/forgot-password", forgot_password_handler)
    app.router.add_post("/api/reset-password", reset_password_handler)
    return app

def main():
    print("🚀 Engineers Babu starting...")
    # Initialize VIP account
    load_users()
    if not SMTP_EMAIL:
        print("⚠️ SMTP not configured. OTP shown in server logs.")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
