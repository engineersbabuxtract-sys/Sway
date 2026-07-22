#!/usr/bin/env python3
"""
Engineers Babu - Complete System
================================
SQLite + Admin Panel + Secure OTP Login
"""

import os
import sys
import json
import asyncio
import random
import hashlib
import secrets
import string
import time
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

import aiohttp
from aiohttp import web, ClientTimeout, TCPConnector

# ═══════════ CONFIGURATION ═══════════
PORT = int(os.getenv("PORT", "8080"))
API_BASE = "https://gdgoenkaratia.com/api"
USER_ID = os.getenv("USER_ID", "")
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", SMTP_EMAIL)  # Admin email for OTP

DB_FILE = Path(__file__).parent / "database.db"
BACKUP_DIR = Path(__file__).parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# ═══════════ DATABASE ═══════════
def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            userid TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            mobile TEXT DEFAULT '',
            is_vip INTEGER DEFAULT 0,
            created TEXT NOT NULL,
            last_login TEXT,
            login_count INTEGER DEFAULT 0,
            last_ip TEXT,
            profile_views INTEGER DEFAULT 0,
            devices TEXT DEFAULT '[]',
            twofa_enabled INTEGER DEFAULT 0,
            account_locked INTEGER DEFAULT 0,
            lock_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            userid TEXT NOT NULL,
            ip TEXT,
            device TEXT,
            created TEXT NOT NULL,
            expires REAL NOT NULL,
            FOREIGN KEY (userid) REFERENCES users(userid)
        );
        CREATE TABLE IF NOT EXISTS login_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            userid TEXT,
            email TEXT,
            ip TEXT,
            device TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS otp_store (
            email TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            expires REAL NOT NULL,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            userid TEXT NOT NULL,
            action TEXT NOT NULL,
            batch_id TEXT,
            topic_id TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS blocked_ips (
            ip TEXT PRIMARY KEY,
            reason TEXT,
            blocked_until REAL,
            blocked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS batch_cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            cached_at REAL NOT NULL,
            expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            ip TEXT,
            created TEXT NOT NULL,
            expires REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        CREATE INDEX IF NOT EXISTS idx_sessions_userid ON sessions(userid);
        CREATE INDEX IF NOT EXISTS idx_login_log_timestamp ON login_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_activity_userid ON activity_log(userid);
    """)
    conn.commit()
    conn.close()

# ═══════════ VIP ACCOUNT ═══════════
VIP_USERID = "Enggbabu8564"
VIP_PASSWORD = "gbabu8564"

def create_vip():
    conn = get_db()
    existing = conn.execute("SELECT userid FROM users WHERE userid = ?", (VIP_USERID,)).fetchone()
    if not existing:
        conn.execute("INSERT INTO users (userid, password, name, email, is_vip, created) VALUES (?, ?, ?, ?, 1, ?)",
                     (VIP_USERID, hashlib.sha256(VIP_PASSWORD.encode()).hexdigest(),
                      "VIP Member", "vip@engineersbabu.com", datetime.now().isoformat()))
        conn.commit()
    conn.close()

# ═══════════ HELPERS ═══════════
def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()

def generate_token(): return secrets.token_hex(32)

def generate_secure_password(length=20):
    """Generate cryptographically secure random password."""
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    all_chars = uppercase + lowercase + digits + special
    
    # Ensure at least one of each type
    password = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    
    # Fill remaining with random from all types
    password += [secrets.choice(all_chars) for _ in range(length - 4)]
    
    # Shuffle
    random.shuffle(password)
    return ''.join(password)

def generate_admin_credentials():
    """Generate one-time admin credentials."""
    # Random UserID: ADM-XXXX-XXXX
    uid_part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    uid_part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    userid = f"ADM-{uid_part1}-{uid_part2}"
    
    # Secure password
    password = generate_secure_password(20)
    
    # 6-digit OTP
    otp = str(random.randint(100000, 999999))
    
    return userid, password, otp

def get_client_ip(request):
    x_forwarded = request.headers.get("X-Forwarded-For", "")
    if x_forwarded: return x_forwarded.split(",")[0].strip()
    x_real = request.headers.get("X-Real-IP", "")
    if x_real: return x_real
    return request.remote

def get_device_info(request):
    ua = request.headers.get("User-Agent", "Unknown")
    if "Mobile" in ua or "Android" in ua: return "Mobile"
    if "Tablet" in ua or "iPad" in ua: return "Tablet"
    return "Desktop"

def send_email(to_email, subject, body_html):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"📧 Would send to {to_email}: {subject}")
        print(f"   Body preview: {body_html[:200]}...")
        return True  # Return True in demo mode
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

def log_action(action, userid="", email="", ip="", device="", detail=""):
    conn = get_db()
    conn.execute("INSERT INTO login_log (timestamp, action, userid, email, ip, device, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now().isoformat(), action, userid, email, ip, device, detail))
    conn.commit()
    conn.close()

def log_activity(userid, action, batch_id="", topic_id="", detail=""):
    conn = get_db()
    conn.execute("INSERT INTO activity_log (timestamp, userid, action, batch_id, topic_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
                 (datetime.now().isoformat(), userid, action, batch_id, topic_id, detail))
    conn.commit()
    conn.close()

def cache_get(key):
    conn = get_db()
    cached = conn.execute("SELECT data FROM batch_cache WHERE cache_key = ? AND expires > ?",
                          (key, datetime.now().timestamp())).fetchone()
    conn.close()
    return json.loads(cached["data"]) if cached else None

def cache_set(key, data, ttl=300):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO batch_cache (cache_key, data, cached_at, expires) VALUES (?, ?, ?, ?)",
                 (key, json.dumps(data), datetime.now().timestamp(), datetime.now().timestamp() + ttl))
    conn.commit()
    conn.close()

# ═══════════ SECURITY ═══════════
MAX_LOGIN_ATTEMPTS = 5
LOGIN_BLOCK_MINUTES = 15
MAX_REQUESTS_PER_MINUTE = 30
SESSION_EXPIRY_DAYS = 7
OTP_EXPIRY_SECONDS = 300
ADMIN_SESSION_MINUTES = 30

rate_limit = defaultdict(list)
login_attempts = defaultdict(list)

def is_ip_blocked(ip):
    conn = get_db()
    blocked = conn.execute("SELECT * FROM blocked_ips WHERE ip = ? AND blocked_until > ?",
                           (ip, datetime.now().timestamp())).fetchone()
    conn.close()
    if blocked: return True
    if len(login_attempts.get(ip, [])) >= MAX_LOGIN_ATTEMPTS:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO blocked_ips (ip, reason, blocked_until, blocked_at) VALUES (?, ?, ?, ?)",
                     (ip, "Too many login attempts", datetime.now().timestamp() + LOGIN_BLOCK_MINUTES * 60,
                      datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    return False

def check_rate_limit(ip):
    now = datetime.now().timestamp()
    rate_limit[ip] = [t for t in rate_limit.get(ip, []) if now - t < 60]
    if len(rate_limit[ip]) >= MAX_REQUESTS_PER_MINUTE: return False
    rate_limit[ip].append(now)
    return True

def cleanup_old_data():
    conn = get_db()
    now = datetime.now().timestamp()
    conn.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    conn.execute("DELETE FROM admin_sessions WHERE expires < ?", (now,))
    conn.execute("DELETE FROM otp_store WHERE expires < ?", (now,))
    conn.execute("DELETE FROM blocked_ips WHERE blocked_until < ?", (now,))
    conn.execute("DELETE FROM batch_cache WHERE expires < ?", (now,))
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    conn.execute("DELETE FROM activity_log WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()

def backup_database():
    backup_path = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    conn = get_db()
    backup = sqlite3.connect(str(backup_path))
    conn.backup(backup)
    backup.close()
    conn.close()
    backups = sorted(BACKUP_DIR.glob("backup_*.db"))
    for old in backups[:-7]:
        old.unlink()

# ═══════════ HTML ═══════════
def get_html():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists(): return html_path.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

def get_admin_html():
    admin_path = Path(__file__).parent / "admin.html"
    if admin_path.exists(): return admin_path.read_text(encoding="utf-8")
    return "<h1>Admin panel not found</h1>"

# ═══════════ API: REGISTRATION ═══════════

async def send_registration_otp(request):
    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)

    email = data.get("email", "").strip().lower()
    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")

    if not all([email, name, password]):
        return web.json_response({"success": False, "error": "All fields required"})
    if len(password) < 6:
        return web.json_response({"success": False, "error": "Password min 6 characters"})

    conn = get_db()
    existing = conn.execute("SELECT userid FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if existing: return web.json_response({"success": False, "error": "Email already registered"})

    code = str(random.randint(100000, 999999))
    conn = get_db()
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.execute("INSERT INTO otp_store (email, code, expires, data) VALUES (?, ?, ?, ?)",
                 (email, code, datetime.now().timestamp() + OTP_EXPIRY_SECONDS,
                  json.dumps({"name": name, "email": email, "mobile": mobile, "password": hash_password(password)})))
    conn.commit(); conn.close()

    body = f"""<div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Engineers Babu</h2><p>Hi {name},</p>
        <p>Your verification code is:</p>
        <h1 style="font-size:36px;letter-spacing:8px;color:#1b2333;background:#f6f8fc;padding:15px;text-align:center;border-radius:10px;">{code}</h1>
        <p>Expires in 5 minutes.</p></div>"""
    send_email(email, "Verify Registration", body)
    log_action("REG_OTP_SENT", email=email, ip=ip)
    return web.json_response({"success": True})

async def verify_registration_otp(request):
    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)
    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)

    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    conn = get_db()
    otp = conn.execute("SELECT * FROM otp_store WHERE email = ?", (email,)).fetchone()
    if not otp: conn.close(); return web.json_response({"success": False, "error": "No registration pending"})
    if datetime.now().timestamp() > otp["expires"]:
        conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
        conn.commit(); conn.close()
        return web.json_response({"success": False, "error": "Code expired"})
    if code != otp["code"]: conn.close(); return web.json_response({"success": False, "error": "Invalid code"})

    user_data = json.loads(otp["data"])
    userid = f"EB{random.randint(1000, 9999)}"
    while conn.execute("SELECT userid FROM users WHERE userid = ?", (userid,)).fetchone():
        userid = f"EB{random.randint(1000, 9999)}"

    now = datetime.now().isoformat()
    conn.execute("INSERT INTO users (userid, password, name, email, mobile, created) VALUES (?, ?, ?, ?, ?, ?)",
                 (userid, user_data["password"], user_data["name"], user_data["email"], user_data["mobile"], now))
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.commit(); conn.close()

    body = f"""<div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
        <h2 style="color:#2955c9;">Welcome!</h2><p>Hi {user_data['name']},</p>
        <p>Your User ID: <strong>{userid}</strong></p></div>"""
    send_email(email, "Welcome!", body)
    log_action("REGISTERED", userid=userid, email=email, ip=ip)
    return web.json_response({"success": True, "userid": userid, "name": user_data["name"]})

# ═══════════ API: LOGIN ═══════════

async def login_handler(request):
    ip = get_client_ip(request)
    device = get_device_info(request)

    if is_ip_blocked(ip):
        return web.json_response({"success": False, "error": "Access blocked"}, status=403)
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)

    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)

    userid = data.get("userid", "").strip()
    password = data.get("password", "")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE userid = ?", (userid,)).fetchone()

    if not user or hash_password(password) != user["password"]:
        login_attempts[ip].append(datetime.now().timestamp())
        log_action("LOGIN_FAILED", userid=userid, ip=ip, device=device)
        remaining = MAX_LOGIN_ATTEMPTS - len(login_attempts[ip])
        conn.close()
        if user and len(login_attempts[ip]) >= 3:
            body = f"""<div style="font-family:Arial,sans-serif;padding:20px;">
                <h2>⚠️ Security Alert</h2><p>Multiple failed login attempts.</p>
                <p>IP: {ip}</p></div>"""
            send_email(user["email"], "Security Alert", body)
        msg = f"Invalid credentials. {remaining} attempts." if remaining > 0 else "Locked for 15 min."
        return web.json_response({"success": False, "error": msg})

    if user["account_locked"]:
        conn.close()
        return web.json_response({"success": False, "error": f"Account locked: {user['lock_reason']}"})

    devices = json.loads(user["devices"] or "[]")
    is_new_device = device not in [d.get("type") for d in devices]

    if is_new_device and user["twofa_enabled"]:
        code = str(random.randint(100000, 999999))
        conn.execute("DELETE FROM otp_store WHERE email = ?", (user["email"],))
        conn.execute("INSERT INTO otp_store (email, code, expires, data) VALUES (?, ?, ?, ?)",
                     (user["email"], code, datetime.now().timestamp() + OTP_EXPIRY_SECONDS,
                      json.dumps({"type": "2fa", "userid": userid})))
        conn.commit(); conn.close()
        body = f"""<div style="font-family:Arial,sans-serif;padding:20px;">
            <h2>New Device Login</h2><p>2FA code: <strong>{code}</strong></p></div>"""
        send_email(user["email"], "2FA Code", body)
        return web.json_response({"success": False, "require_2fa": True, "email": user["email"]})

    token = generate_token()
    now = datetime.now()
    if not any(d.get("type") == device for d in devices):
        devices.append({"type": device, "ip": ip, "first_seen": now.isoformat()})

    conn.execute("INSERT INTO sessions (token, userid, ip, device, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
                 (token, userid, ip, device, now.isoformat(), now.timestamp() + SESSION_EXPIRY_DAYS * 86400))
    conn.execute("UPDATE users SET last_login = ?, login_count = login_count + 1, last_ip = ?, devices = ? WHERE userid = ?",
                 (now.isoformat(), ip, json.dumps(devices), userid))
    conn.commit(); conn.close()

    if ip in login_attempts: del login_attempts[ip]
    log_action("LOGIN_SUCCESS", userid=userid, ip=ip, device=device)
    return web.json_response({"success": True, "token": token, "userid": userid, "name": user["name"], "email": user["email"]})

async def verify_2fa_handler(request):
    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)

    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    conn = get_db()
    otp = conn.execute("SELECT * FROM otp_store WHERE email = ?", (email,)).fetchone()
    if not otp or datetime.now().timestamp() > otp["expires"]:
        conn.close(); return web.json_response({"success": False, "error": "Code expired"})
    if code != otp["code"]: conn.close(); return web.json_response({"success": False, "error": "Invalid code"})

    otp_data = json.loads(otp["data"])
    ip = get_client_ip(request)
    device = get_device_info(request)
    token = generate_token()
    now = datetime.now()

    conn.execute("INSERT INTO sessions (token, userid, ip, device, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
                 (token, otp_data["userid"], ip, device, now.isoformat(), now.timestamp() + SESSION_EXPIRY_DAYS * 86400))
    conn.execute("UPDATE users SET last_login = ?, login_count = login_count + 1, last_ip = ? WHERE userid = ?",
                 (now.isoformat(), ip, otp_data["userid"]))
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE userid = ?", (otp_data["userid"],)).fetchone()
    conn.close()

    log_action("LOGIN_2FA", userid=otp_data["userid"], ip=ip, device=device)
    return web.json_response({"success": True, "token": token, "userid": user["userid"], "name": user["name"], "email": user["email"]})

# ═══════════ API: PROFILE ═══════════

async def profile_handler(request):
    token = request.query.get("token", "")
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE token = ? AND expires > ?",
                           (token, datetime.now().timestamp())).fetchone()
    if not session: conn.close(); return web.json_response({"success": False, "error": "Session expired"}, status=401)

    user = conn.execute("SELECT * FROM users WHERE userid = ?", (session["userid"],)).fetchone()
    conn.execute("UPDATE users SET profile_views = profile_views + 1 WHERE userid = ?", (session["userid"],))
    recent = conn.execute("SELECT * FROM activity_log WHERE userid = ? ORDER BY timestamp DESC LIMIT 10",
                          (session["userid"],)).fetchall()
    session_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE userid = ? AND expires > ?",
                                  (session["userid"], datetime.now().timestamp())).fetchone()[0]
    conn.commit(); conn.close()

    return web.json_response({
        "success": True,
        "profile": {
            "userid": user["userid"], "name": user["name"], "email": user["email"],
            "mobile": user["mobile"], "is_vip": bool(user["is_vip"]),
            "created": user["created"], "last_login": user["last_login"],
            "login_count": user["login_count"], "last_ip": user["last_ip"],
            "profile_views": user["profile_views"], "twofa_enabled": bool(user["twofa_enabled"]),
            "active_sessions": session_count, "recent_activity": [dict(r) for r in recent]
        }
    })

async def logout_handler(request):
    token = request.query.get("token", "")
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit(); conn.close()
    return web.json_response({"success": True})

# ═══════════ API: PASSWORD RESET ═══════════

async def forgot_password_handler(request):
    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    email = data.get("email", "").strip().lower()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not user: return web.json_response({"success": False, "error": "Email not found"})
    code = str(random.randint(100000, 999999))
    conn = get_db()
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.execute("INSERT INTO otp_store (email, code, expires, data) VALUES (?, ?, ?, ?)",
                 (email, code, datetime.now().timestamp() + OTP_EXPIRY_SECONDS, user["userid"]))
    conn.commit(); conn.close()
    body = f"""<div style="font-family:Arial,sans-serif;padding:20px;">
        <h2>Password Reset</h2><p>Code: <strong>{code}</strong></p><p>User ID: <strong>{user['userid']}</strong></p></div>"""
    send_email(email, "Password Reset", body)
    log_action("PASSWORD_RESET", userid=user["userid"], email=email)
    return web.json_response({"success": True, "userid": user["userid"]})

async def reset_password_handler(request):
    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    new_password = data.get("password", "")
    conn = get_db()
    otp = conn.execute("SELECT * FROM otp_store WHERE email = ?", (email,)).fetchone()
    if not otp or datetime.now().timestamp() > otp["expires"]:
        conn.close(); return web.json_response({"success": False, "error": "Code expired"})
    if code != otp["code"]: conn.close(); return web.json_response({"success": False, "error": "Invalid code"})
    conn.execute("UPDATE users SET password = ? WHERE userid = ?", (hash_password(new_password), otp["data"]))
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.commit(); conn.close()
    return web.json_response({"success": True})

# ═══════════ API: PROXY ═══════════

async def proxy_handler(request):
    token = request.query.get("token", "")
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE token = ? AND expires > ?",
                           (token, datetime.now().timestamp())).fetchone()
    conn.close()
    if not session: return web.json_response({"error": "Unauthorized"}, status=401)

    endpoint = request.query.get("endpoint", "")
    if not endpoint: return web.json_response({"error": "Missing endpoint"}, status=400)

    params = dict(request.query)
    params.pop("endpoint", None); params.pop("token", None)
    params["userId"] = USER_ID

    batch_id = params.get("courseId", ""); topic_id = params.get("topicId", "")
    log_activity(session["userid"], f"api:{endpoint}", batch_id, topic_id)

    cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
    cached = cache_get(cache_key)
    if cached: return web.json_response(cached)

    target_url = f"{API_BASE}/{endpoint.lstrip('/')}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
               "Referer": "https://www.selectionway.com/", "Origin": "https://www.selectionway.com"}

    for attempt in range(3):
        try:
            timeout = ClientTimeout(total=30)
            connector = TCPConnector(ssl=False, force_close=True)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as s:
                async with s.get(target_url, params=params, allow_redirects=True) as resp:
                    if resp.status == 429: await asyncio.sleep(random.uniform(2, 5)); continue
                    data = await resp.json()
                    cache_set(cache_key, data, ttl=300)
                    return web.json_response(data, status=resp.status)
        except Exception as e:
            if attempt == 2: return web.json_response({"error": str(e)}, status=500)
            await asyncio.sleep(random.uniform(1, 3))
    return web.json_response({"error": "Max retries"}, status=500)

# ═══════════ ADMIN PANEL - SECURE OTP LOGIN ═══════════

async def admin_request_otp_handler(request):
    """Step 1: Admin requests OTP. Generates secure one-time credentials."""
    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)

    admin_email = ADMIN_EMAIL
    if not admin_email:
        return web.json_response({"success": False, "error": "Admin email not configured"}, status=500)

    # Generate one-time secure credentials
    admin_userid, admin_password, otp_code = generate_admin_credentials()

    # Store in OTP table
    conn = get_db()
    conn.execute("DELETE FROM otp_store WHERE email = ?", (admin_email,))
    conn.execute("INSERT INTO otp_store (email, code, expires, data) VALUES (?, ?, ?, ?)",
                 (admin_email, otp_code, datetime.now().timestamp() + OTP_EXPIRY_SECONDS,
                  json.dumps({"type": "admin", "userid": admin_userid, "password": admin_password})))
    conn.commit(); conn.close()

    # Send email with all credentials
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:550px;margin:0 auto;padding:25px;background:#f8fafc;border-radius:12px;">
        <div style="background:#1e293b;color:#fff;padding:20px;border-radius:10px;text-align:center;margin-bottom:20px;">
            <h2 style="margin:0;">🔐 Admin Panel Access</h2>
            <p style="margin:5px 0 0;opacity:0.8;">One-time credentials - Expires in 5 minutes</p>
        </div>
        
        <div style="background:#fff;padding:20px;border-radius:10px;border:1px solid #e2e8f0;">
            <p style="color:#475569;margin-bottom:15px;">Use these credentials to access the admin panel:</p>
            
            <div style="background:#f1f5f9;padding:15px;border-radius:8px;margin-bottom:10px;">
                <p style="margin:0;font-size:13px;color:#64748b;">ONE-TIME USER ID</p>
                <p style="margin:5px 0 0;font-size:20px;font-weight:700;font-family:monospace;color:#1e293b;">{admin_userid}</p>
            </div>
            
            <div style="background:#f1f5f9;padding:15px;border-radius:8px;margin-bottom:10px;">
                <p style="margin:0;font-size:13px;color:#64748b;">ONE-TIME PASSWORD</p>
                <p style="margin:5px 0 0;font-size:16px;font-weight:700;font-family:monospace;color:#1e293b;word-break:break-all;">{admin_password}</p>
            </div>
            
            <div style="background:#fef3c7;padding:15px;border-radius:8px;text-align:center;">
                <p style="margin:0;font-size:13px;color:#92400e;">VERIFICATION CODE</p>
                <p style="margin:5px 0 0;font-size:36px;font-weight:700;letter-spacing:8px;color:#92400e;">{otp_code}</p>
            </div>
        </div>
        
        <div style="margin-top:20px;padding:15px;background:#fef2f2;border-radius:8px;border:1px solid #fecaca;">
            <p style="margin:0;font-size:12px;color:#991b1b;">
                ⚠️ <strong>Security Notice:</strong> These credentials are valid for ONE login only. 
                They expire in 5 minutes. Do not share with anyone. 
                Request IP: {ip}
            </p>
        </div>
    </div>
    """

    sent = send_email(admin_email, "🔐 Admin Panel - One-Time Access", body)
    
    if not sent:
        print(f"\n{'='*60}")
        print(f"🔐 ADMIN CREDENTIALS (Demo Mode)")
        print(f"   User ID:  {admin_userid}")
        print(f"   Password: {admin_password}")
        print(f"   OTP:      {otp_code}")
        print(f"{'='*60}\n")

    log_action("ADMIN_OTP_REQUESTED", email=admin_email, ip=ip)
    return web.json_response({"success": True, "message": "Credentials sent to admin email"})

async def admin_login_handler(request):
    """Step 2: Admin logs in with one-time credentials + OTP."""
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip):
        return web.json_response({"success": False, "error": "Too many requests"}, status=429)

    try: data = await request.json()
    except: return web.json_response({"success": False, "error": "Invalid request"}, status=400)

    email = ADMIN_EMAIL
    userid = data.get("userid", "").strip()
    password = data.get("password", "")
    otp = data.get("otp", "").strip()

    if not all([userid, password, otp]):
        return web.json_response({"success": False, "error": "User ID, password, and OTP required"})

    conn = get_db()
    stored = conn.execute("SELECT * FROM otp_store WHERE email = ?", (email,)).fetchone()

    if not stored:
        conn.close()
        return web.json_response({"success": False, "error": "No active admin session. Request new credentials."})

    if datetime.now().timestamp() > stored["expires"]:
        conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
        conn.commit(); conn.close()
        return web.json_response({"success": False, "error": "Credentials expired. Request new ones."})

    stored_data = json.loads(stored["data"])
    
    if stored_data.get("type") != "admin":
        conn.close()
        return web.json_response({"success": False, "error": "Invalid admin session"})

    # Verify all three: UserID, Password, OTP
    if userid != stored_data["userid"]:
        conn.close()
        log_action("ADMIN_LOGIN_FAILED", email=email, ip=ip, detail="Wrong UserID")
        return web.json_response({"success": False, "error": "Invalid credentials"})

    if password != stored_data["password"]:
        conn.close()
        log_action("ADMIN_LOGIN_FAILED", email=email, ip=ip, detail="Wrong password")
        return web.json_response({"success": False, "error": "Invalid credentials"})

    if otp != stored["code"]:
        conn.close()
        log_action("ADMIN_LOGIN_FAILED", email=email, ip=ip, detail="Wrong OTP")
        return web.json_response({"success": False, "error": "Invalid OTP"})

    # All verified - create admin session
    token = generate_token()
    now = datetime.now()
    conn.execute("INSERT INTO admin_sessions (token, email, ip, created, expires) VALUES (?, ?, ?, ?, ?)",
                 (token, email, ip, now.isoformat(), now.timestamp() + ADMIN_SESSION_MINUTES * 60))
    
    # Delete used OTP
    conn.execute("DELETE FROM otp_store WHERE email = ?", (email,))
    conn.commit(); conn.close()

    log_action("ADMIN_LOGIN_SUCCESS", email=email, ip=ip, detail=f"One-time user: {userid}")
    return web.json_response({"success": True, "token": token, "message": "Admin access granted"})

async def admin_data_handler(request):
    """Admin data API - requires valid admin session."""
    token = request.query.get("token", "")
    conn = get_db()
    session = conn.execute("SELECT * FROM admin_sessions WHERE token = ? AND expires > ?",
                           (token, datetime.now().timestamp())).fetchone()
    if not session:
        conn.close()
        return web.json_response({"error": "Admin session expired. Login again."}, status=401)

    action = request.query.get("action", "overview")

    if action == "overview":
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_today = conn.execute("SELECT COUNT(DISTINCT userid) FROM login_log WHERE action='LOGIN_SUCCESS' AND date(timestamp)=date('now')").fetchone()[0]
        total_logins = conn.execute("SELECT COUNT(*) FROM login_log WHERE action='LOGIN_SUCCESS'").fetchone()[0]
        total_activities = conn.execute("SELECT COUNT(*) FROM activity_log WHERE date(timestamp)=date('now')").fetchone()[0]
        blocked = conn.execute("SELECT COUNT(*) FROM blocked_ips WHERE blocked_until > ?", (datetime.now().timestamp(),)).fetchone()[0]
        conn.close()
        return web.json_response({"total_users": total_users, "active_today": active_today, "total_logins": total_logins, "total_activities_today": total_activities, "blocked_ips": blocked})

    elif action == "users":
        search = request.query.get("search", "")
        page = int(request.query.get("page", "1"))
        limit = 20; offset = (page - 1) * limit
        if search:
            users = conn.execute("SELECT * FROM users WHERE userid LIKE ? OR name LIKE ? OR email LIKE ? OR mobile LIKE ? ORDER BY created DESC LIMIT ? OFFSET ?",
                                (f"%{search}%",)*4 + (limit, offset)).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM users WHERE userid LIKE ? OR name LIKE ? OR email LIKE ? OR mobile LIKE ?",
                                (f"%{search}%",)*4).fetchone()[0]
        else:
            users = conn.execute("SELECT * FROM users ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return web.json_response({"users": [dict(u) for u in users], "total": total, "page": page, "pages": (total + limit - 1) // limit})

    elif action == "user_detail":
        userid = request.query.get("userid", "")
        user = conn.execute("SELECT * FROM users WHERE userid = ?", (userid,)).fetchone()
        if not user: conn.close(); return web.json_response({"error": "Not found"}, status=404)
        sessions = conn.execute("SELECT * FROM sessions WHERE userid = ? AND expires > ?", (userid, datetime.now().timestamp())).fetchall()
        logins = conn.execute("SELECT * FROM login_log WHERE userid = ? ORDER BY timestamp DESC LIMIT 50", (userid,)).fetchall()
        activities = conn.execute("SELECT * FROM activity_log WHERE userid = ? ORDER BY timestamp DESC LIMIT 100", (userid,)).fetchall()
        conn.close()
        return web.json_response({"user": dict(user), "active_sessions": [dict(s) for s in sessions], "login_history": [dict(l) for l in logins], "activities": [dict(a) for a in activities]})

    elif action == "logs":
        page = int(request.query.get("page", "1"))
        limit = 50; offset = (page - 1) * limit
        logs = conn.execute("SELECT * FROM login_log ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM login_log").fetchone()[0]
        conn.close()
        return web.json_response({"logs": [dict(l) for l in logs], "total": total, "page": page})

    elif action == "block_user":
        userid = request.query.get("userid", "")
        reason = request.query.get("reason", "Blocked by admin")
        conn.execute("UPDATE users SET account_locked = 1, lock_reason = ? WHERE userid = ?", (reason, userid))
        conn.execute("DELETE FROM sessions WHERE userid = ?", (userid,))
        conn.commit(); conn.close()
        log_action("USER_BLOCKED", userid=userid, detail=reason)
        return web.json_response({"success": True})

    elif action == "unblock_user":
        userid = request.query.get("userid", "")
        conn.execute("UPDATE users SET account_locked = 0, lock_reason = NULL WHERE userid = ?", (userid,))
        conn.commit(); conn.close()
        return web.json_response({"success": True})

    elif action == "delete_user":
        userid = request.query.get("userid", "")
        conn.execute("DELETE FROM sessions WHERE userid = ?", (userid,))
        conn.execute("DELETE FROM activity_log WHERE userid = ?", (userid,))
        conn.execute("DELETE FROM login_log WHERE userid = ?", (userid,))
        conn.execute("DELETE FROM users WHERE userid = ?", (userid,))
        conn.commit(); conn.close()
        return web.json_response({"success": True})

    conn.close()
    return web.json_response({"error": "Invalid action"}, status=400)

# ═══════════ MIDDLEWARE ═══════════

@web.middleware
async def security_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*", "Access-Control-Max-Age": "86400"})
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ═══════════ ROUTES ═══════════

async def index_handler(request):
    return web.Response(text=get_html(), content_type="text/html")

async def admin_page_handler(request):
    return web.Response(text=get_admin_html(), content_type="text/html")

async def health_handler(request):
    cleanup_old_data()
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return web.json_response({"status": "healthy", "users": users})

def create_app():
    app = web.Application(middlewares=[security_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/admin", admin_page_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/api/register-otp", send_registration_otp)
    app.router.add_post("/api/register-verify", verify_registration_otp)
    app.router.add_post("/api/login", login_handler)
    app.router.add_post("/api/verify-2fa", verify_2fa_handler)
    app.router.add_get("/api/logout", logout_handler)
    app.router.add_get("/api/profile", profile_handler)
    app.router.add_post("/api/forgot-password", forgot_password_handler)
    app.router.add_post("/api/reset-password", reset_password_handler)
    app.router.add_get("/api/proxy", proxy_handler)
    app.router.add_post("/api/admin/request-otp", admin_request_otp_handler)
    app.router.add_post("/api/admin/login", admin_login_handler)
    app.router.add_get("/api/admin/data", admin_data_handler)
    return app

def main():
    print("""
╔══════════════════════════════════════╗
║  Engineers Babu - Secure System      ║
║  Admin OTP + One-Time Credentials    ║
╚══════════════════════════════════════╝""")
    init_db()
    create_vip()
    backup_database()
    if not SMTP_EMAIL: print("⚠️ SMTP not configured. OTP shown in logs.")
    if not ADMIN_EMAIL: print("⚠️ ADMIN_EMAIL not set. Using SMTP_EMAIL.")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
