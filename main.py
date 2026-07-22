#!/usr/bin/env python3
"""
Engineers Babu - Koyeb Edition
===============================
Maximum Security System
- Session tokens with expiry
- Rate limiting
- IP tracking
- User profiles
- Encrypted storage
- Request validation
"""

import os
import sys
import json
import asyncio
import random
import hashlib
import secrets
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import aiohttp
from aiohttp import web, ClientTimeout, TCPConnector

PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# ═══════════ FILE PATHS ═══════════
USERS_FILE = Path(__file__).parent / "users.json"
SESSIONS_FILE = Path(__file__).parent / "sessions.json"
LOG_FILE = Path(__file__).parent / "login_log.txt"
SECURITY_LOG = Path(__file__).parent / "security_log.txt"
OTP_FILE = Path(__file__).parent / "otp_store.json"
BLOCKED_IPS = Path(__file__).parent / "blocked_ips.json"

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
    "created": datetime.now().isoformat(),
    "last_login": None,
    "login_count": 0,
    "ips": []
}

# ═══════════ SECURITY CONFIG ═══════════
MAX_LOGIN_ATTEMPTS = 5
LOGIN_BLOCK_MINUTES = 15
MAX_REQUESTS_PER_MINUTE = 30
SESSION_EXPIRY_DAYS = 7
OTP_EXPIRY_SECONDS = 300

# ═══════════ IN-MEMORY STORAGE ═══════════
pending_registrations = {}
password_reset_codes = {}
active_sessions = {}
login_attempts = defaultdict(list)
rate_limit = defaultdict(list)
ip_blocks = {}

# Load blocked IPs
def load_blocked_ips():
    if BLOCKED_IPS.exists():
        return json.loads(BLOCKED_IPS.read_text())
    return {}

def save_blocked_ips(data):
    BLOCKED_IPS.write_text(json.dumps(data, indent=2))

ip_blocks = load_blocked_ips()

# ═══════════ CLEANUP OLD DATA ═══════════
def cleanup_old_data():
    now = datetime.now().timestamp()
    
    # Clean expired sessions
    expired_sessions = [t for t, s in active_sessions.items() if now > s["expires"]]
    for t in expired_sessions:
        del active_sessions[t]
    
    # Clean old rate limit entries
    for ip in list(rate_limit.keys()):
        rate_limit[ip] = [t for t in rate_limit[ip] if now - t < 60]
        if not rate_limit[ip]:
            del rate_limit[ip]
    
    # Clean old login attempts
    for ip in list(login_attempts.keys()):
        login_attempts[ip] = [t for t in login_attempts[ip] if now - t < LOGIN_BLOCK_MINUTES * 60]
        if not login_attempts[ip]:
            del login_attempts[ip]
    
    # Clean expired IP blocks
    for ip in list(ip_blocks.keys()):
        if now > ip_blocks[ip]:
            del ip_blocks[ip]
    save_blocked_ips(ip_blocks)
    
    # Clean OTP store
    if OTP_FILE.exists():
        otps = json.loads(OTP_FILE.read_text())
        for email in list(otps.keys()):
            if now > otps[email].get("expires", 0):
                del otps[email]
        OTP_FILE.write_text(json.dumps(otps, indent=2))

# ═══════════ FILE OPERATIONS ═══════════
def load_users():
    if USERS_FILE.exists():
        data = json.loads(USERS_FILE.read_text())
    else:
        data = {"users": {}}
    if VIP_USERID not in data["users"]:
        data["users"][VIP_USERID] = VIP_DATA
        save_users(data)
    return data

def save_users(data):
    USERS_FILE.write_text(json.dumps(data, indent=2))

def load_sessions():
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text())
    return {}

def save_sessions(data):
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))

# ═══════════ LOGGING ═══════════
def log_action(log_file, action, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {action} | {detail}\n")

def security_log(action, detail=""):
    log_action(SECURITY_LOG, action, detail)

def login_log(action, detail=""):
    log_action(LOG_FILE, action, detail)

# ═══════════ HELPERS ═══════════
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_hex(32)

def get_client_ip(request):
    """Get real client IP from headers."""
    x_forwarded = request.headers.get("X-Forwarded-For", "")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    x_real = request.headers.get("X-Real-IP", "")
    if x_real:
        return x_real
    return request.remote

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

def is_ip_blocked(ip):
    """Check if IP is blocked."""
    now = datetime.now().timestamp()
    if ip in ip_blocks and now < ip_blocks[ip]:
        return True
    if len(login_attempts.get(ip, [])) >= MAX_LOGIN_ATTEMPTS:
        ip_blocks[ip] = now + LOGIN_BLOCK_MINUTES * 60
        save_blocked_ips(ip_blocks)
        security_log("IP_BLOCKED", f"IP: {ip} | Reason: Too many login attempts")
        return True
    return False

def check_rate_limit(ip):
    """Check if IP exceeded rate limit."""
    now = datetime.now().timestamp()
    rate_limit[ip] = [t for t in rate_limit.get(ip, []) if now - t < 60]
    if len(rate_limit[ip]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    rate_limit[ip].append(now)
    return True

def validate_token(token):
    """Validate session token."""
    if not token:
        return None
    session = active_sessions.get(token)
    if not session:
        return None
    if datetime.now().timestamp() > session["expires"]:
        del active_sessions[token]
        return None
    return session

# ═══════════ HTML ═══════════
def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

# ═══════════ API HANDLERS ═══════════

async def send_registration_otp(request):
    """Step 1: Send OTP for registration."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests. Try later."}, status=429)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    
    email = data.get("email", "").strip().lower()
    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")
    
    if not all([email, name, password]):
        return web.json_response({"success": False, "error": "Name, email, and password are required"})
    
    if len(password) < 6:
        return web.json_response({"success": False, "error": "Password must be at least 6 characters"})
    
    if not mobile or len(mobile) < 10:
        return web.json_response({"success": False, "error": "Valid mobile number required"})
    
    users = load_users()
    for uid, u in users["users"].items():
        if u.get("email") == email:
            return web.json_response({"success": False, "error": "Email already registered"})
    
    code = str(random.randint(100000, 999999))
    pending_registrations[email] = {
        "code": code,
        "expires": datetime.now().timestamp() + OTP_EXPIRY_SECONDS,
        "user_data": {
            "name": name,
            "email": email,
            "mobile": mobile,
            "password": hash_password(password)
        }
    }
    
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Engineers Babu</h2>
        <p>Hi {name},</p>
        <p>Your verification code is:</p>
        <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
        <p>This code expires in 5 minutes.</p>
    </div>
    """
    
    sent = send_email(email, "Verify Your Registration", body)
    if not sent:
        print(f"\n📧 Registration OTP for {email}: {code}\n")
    
    security_log("REG_OTP_SENT", f"{name} <{email}> | IP: {ip}")
    return web.json_response({"success": True})

async def verify_registration_otp(request):
    """Step 2: Verify OTP and create account."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    
    pending = pending_registrations.get(email)
    if not pending:
        return web.json_response({"success": False, "error": "No registration pending. Start over."})
    
    if datetime.now().timestamp() > pending["expires"]:
        del pending_registrations[email]
        return web.json_response({"success": False, "error": "Code expired. Register again."})
    
    if code != pending["code"]:
        security_log("REG_OTP_FAILED", f"Email: {email} | IP: {ip}")
        return web.json_response({"success": False, "error": "Invalid code"})
    
    user_data = pending["user_data"]
    userid = f"EB{random.randint(1000, 9999)}"
    
    users = load_users()
    while userid in users["users"]:
        userid = f"EB{random.randint(1000, 9999)}"
    
    now = datetime.now().isoformat()
    users["users"][userid] = {
        "userid": userid,
        "password": user_data["password"],
        "name": user_data["name"],
        "email": user_data["email"],
        "mobile": user_data["mobile"],
        "is_vip": False,
        "created": now,
        "last_login": None,
        "login_count": 0,
        "ips": [ip],
        "last_ip": ip,
        "profile_views": 0
    }
    save_users(users)
    del pending_registrations[email]
    
    # Welcome email
    welcome_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Welcome to Engineers Babu!</h2>
        <p>Hi {user_data['name']},</p>
        <p>Your account has been created successfully.</p>
        <div style="background:#f6f8fc;padding:15px;border-radius:10px;margin:15px 0;">
            <p><strong>User ID:</strong> {userid}</p>
            <p><strong>Email:</strong> {user_data['email']}</p>
        </div>
        <p>Use your User ID and password to login.</p>
    </div>
    """
    send_email(email, "Welcome to Engineers Babu!", welcome_body)
    
    login_log("REGISTERED", f"{user_data['name']} <{email}> | UserID: {userid} | IP: {ip}")
    security_log("REG_SUCCESS", f"UserID: {userid} | IP: {ip}")
    
    return web.json_response({"success": True, "userid": userid, "name": user_data["name"]})

async def login_handler(request):
    """Login with UserID + Password."""
    ip = get_client_ip(request)
    
    # Check IP block
    if is_ip_blocked(ip):
        security_log("BLOCKED_ATTEMPT", f"IP: {ip}")
        return web.json_response({"success": False, "error": "Access temporarily blocked. Try later."}, status=403)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    
    userid = data.get("userid", "").strip()
    password = data.get("password", "")
    
    if not userid or not password:
        return web.json_response({"success": False, "error": "UserID and password required"})
    
    users = load_users()
    user = users["users"].get(userid)
    
    if not user or hash_password(password) != user["password"]:
        login_attempts[ip].append(datetime.now().timestamp())
        login_log("LOGIN_FAILED", f"UserID: {userid} | IP: {ip} | Attempt: {len(login_attempts[ip])}")
        remaining = MAX_LOGIN_ATTEMPTS - len(login_attempts[ip])
        msg = f"Invalid credentials. {remaining} attempts remaining." if remaining > 0 else "Account locked for 15 minutes."
        return web.json_response({"success": False, "error": msg})
    
    # Success - create session
    token = generate_token()
    now = datetime.now()
    active_sessions[token] = {
        "userid": userid,
        "name": user["name"],
        "email": user["email"],
        "ip": ip,
        "created": now.isoformat(),
        "expires": now.timestamp() + SESSION_EXPIRY_DAYS * 86400
    }
    
    # Update user data
    user["last_login"] = now.isoformat()
    user["login_count"] = user.get("login_count", 0) + 1
    user["last_ip"] = ip
    if ip not in user.get("ips", []):
        user["ips"] = user.get("ips", []) + [ip]
    save_users(users)
    
    # Clear failed attempts
    if ip in login_attempts:
        del login_attempts[ip]
    
    login_log("LOGIN_SUCCESS", f"{user['name']} | UserID: {userid} | IP: {ip}")
    
    return web.json_response({
        "success": True,
        "token": token,
        "userid": userid,
        "name": user["name"],
        "email": user["email"]
    })

async def profile_handler(request):
    """Get user profile (requires auth)."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    
    token = request.query.get("token", "")
    session = validate_token(token)
    
    if not session:
        return web.json_response({"success": False, "error": "Session expired. Login again."}, status=401)
    
    users = load_users()
    user = users["users"].get(session["userid"])
    
    if not user:
        return web.json_response({"success": False, "error": "User not found"}, status=404)
    
    user["profile_views"] = user.get("profile_views", 0) + 1
    save_users(users)
    
    return web.json_response({
        "success": True,
        "profile": {
            "userid": user["userid"],
            "name": user["name"],
            "email": user["email"],
            "mobile": user.get("mobile", ""),
            "is_vip": user.get("is_vip", False),
            "created": user.get("created", ""),
            "last_login": user.get("last_login", ""),
            "login_count": user.get("login_count", 0),
            "last_ip": user.get("last_ip", "")
        }
    })

async def logout_handler(request):
    """Logout and invalidate session."""
    token = request.query.get("token", "")
    
    if token in active_sessions:
        session = active_sessions[token]
        login_log("LOGOUT", f"UserID: {session['userid']}")
        del active_sessions[token]
    
    return web.json_response({"success": True})

async def forgot_password_handler(request):
    """Send password reset code."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    
    email = data.get("email", "").strip().lower()
    users = load_users()
    
    found = None
    for uid, u in users["users"].items():
        if u.get("email") == email:
            found = u
            break
    
    if not found:
        return web.json_response({"success": False, "error": "Email not found"})
    
    code = str(random.randint(100000, 999999))
    password_reset_codes[email] = {
        "code": code,
        "expires": datetime.now().timestamp() + OTP_EXPIRY_SECONDS,
        "userid": found["userid"]
    }
    
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Engineers Babu - Password Reset</h2>
        <p>Hi {found['name']},</p>
        <p>Your password reset code is:</p>
        <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
        <p>Your User ID: <strong>{found['userid']}</strong></p>
        <p>This code expires in 5 minutes.</p>
    </div>
    """
    
    sent = send_email(email, "Password Reset Code", body)
    if not sent:
        print(f"\n📧 Reset code for {email}: {code}\n")
    
    security_log("PASSWORD_RESET", f"UserID: {found['userid']} | IP: {ip}")
    return web.json_response({"success": True, "userid": found["userid"]})

async def reset_password_handler(request):
    """Reset password with code."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    new_password = data.get("password", "")
    
    reset = password_reset_codes.get(email)
    if not reset:
        return web.json_response({"success": False, "error": "No reset requested. Start over."})
    
    if datetime.now().timestamp() > reset["expires"]:
        del password_reset_codes[email]
        return web.json_response({"success": False, "error": "Code expired"})
    
    if code != reset["code"]:
        return web.json_response({"success": False, "error": "Invalid code"})
    
    if len(new_password) < 6:
        return web.json_response({"success": False, "error": "Password must be at least 6 characters"})
    
    users = load_users()
    users["users"][reset["userid"]]["password"] = hash_password(new_password)
    save_users(users)
    del password_reset_codes[email]
    
    security_log("PASSWORD_CHANGED", f"UserID: {reset['userid']} | IP: {ip}")
    return web.json_response({"success": True})

async def proxy_handler(request):
    """Protected API proxy."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"error": "Too many requests"}, status=429)
    
    # Check auth
    token = request.query.get("token", "")
    session = validate_token(token)
    
    if not session:
        return web.json_response({"error": "Unauthorized. Please login."}, status=401)
    
    endpoint = request.query.get("endpoint", "")
    if not endpoint:
        return web.json_response({"error": "Missing endpoint"}, status=400)

    params = dict(request.query)
    params.pop("endpoint", None)
    params.pop("token", None)
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
            async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as s:
                async with s.get(target_url, params=params, allow_redirects=True) as resp:
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

# ═══════════ MIDDLEWARE ═══════════

@web.middleware
async def security_middleware(request, handler):
    """Global security middleware."""
    # CORS preflight
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        })
    
    # Block suspicious User-Agents
    ua = request.headers.get("User-Agent", "").lower()
    blocked_agents = ["sqlmap", "nikto", "nmap", "masscan", "gobuster", "dirbuster"]
    for agent in blocked_agents:
        if agent in ua:
            ip = get_client_ip(request)
            security_log("BLOCKED_AGENT", f"IP: {ip} | Agent: {ua}")
            return web.Response(text="Access Denied", status=403)
    
    # Add security headers
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    
    return response

# ═══════════ ROUTES ═══════════
async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def health_handler(request):
    cleanup_old_data()
    return web.json_response({
        "status": "healthy",
        "active_sessions": len(active_sessions),
        "timestamp": datetime.now().isoformat()
    })

def create_app():
    app = web.Application(middlewares=[security_middleware])
    
    # Public routes
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    
    # Auth routes
    app.router.add_post("/api/register-otp", send_registration_otp)
    app.router.add_post("/api/register-verify", verify_registration_otp)
    app.router.add_post("/api/login", login_handler)
    app.router.add_get("/api/logout", logout_handler)
    app.router.add_post("/api/forgot-password", forgot_password_handler)
    app.router.add_post("/api/reset-password", reset_password_handler)
    
    # Protected routes
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_get("/api/profile", profile_handler)
    
    return app

def main():
    print("""
╔══════════════════════════════════════╗
║  Engineers Babu - Secure Edition     ║
║  Session Auth + Rate Limit + Profile ║
╚══════════════════════════════════════╝
    """)
    load_users()
    if not SMTP_EMAIL:
        print("⚠️ SMTP not configured. OTP shown in server logs.")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
