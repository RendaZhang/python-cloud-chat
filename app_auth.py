"""Flask web service for Authetication"""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from argon2 import PasswordHasher
from flask import Blueprint, request, jsonify, make_response, current_app
from db import get_session
from models import User, Credential
from sqlalchemy import text
import os
import re
import secrets
import redis

# ---- 配置 ----
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "cc_auth")
COOKIE_NAME = AUTH_COOKIE_NAME
# 生产请设为 1；若需在 HTTP 下本机测试，设为 0
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
COOKIE_SAMESITE = "Lax"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
RATE_LIMIT_LOGIN_PER_10MIN = 10
# 密码找回配置
PWRESET_TOKEN_TTL = int(os.getenv("PWRESET_TOKEN_TTL", "900"))  # 15分钟
# 生产请设为 0
DEBUG_RETURN_RESET_TOKEN = os.getenv("DEBUG_RETURN_RESET_TOKEN", "0") == "1"
# 重置后强制下线
PWRESET_REVOKE_SESSIONS = os.getenv("PWRESET_REVOKE_SESSIONS", "1") == "1"

# Redis 服务配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_TIMEOUT = int(os.getenv("REDIS_TIMEOUT", 5))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
)

ph = PasswordHasher()
auth = Blueprint("auth", __name__, url_prefix="/auth")

# ---- 工具 ----
_email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(s: str | None) -> str | None:
    return s.strip().lower() if s else None


def _client_ip() -> str:
    # 适配 Nginx 反代
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else request.remote_addr or "0.0.0.0"


def _rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """返回是否允许。使用 Redis 计数 + 过期。"""
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_sec)
    count, _ = pipe.execute()
    return int(count) <= limit


def _issue_session(user_id: int):
    sid = secrets.token_urlsafe(32)
    redis_client.setex(f"sess:{sid}", SESSION_TTL_SECONDS, user_id)
    return sid


def _get_user_from_cookie():
    sid = request.cookies.get(COOKIE_NAME)
    if not sid:
        return None, None
    uid = redis_client.get(f"sess:{sid}")
    if not uid:
        return None, sid
    try:
        with get_session() as s:
            user = s.get(User, int(uid))
            if not user:
                return None, sid
            # 提前提取用户信息，避免在会话外访问 user 对象
            user_data = {
                "id": user.id,
                "uid": user.uid,
                "email": user.email,
                "phone": user.phone,
                "display_name": user.display_name,
                "is_active": user.is_active,
            }
            return user_data, sid  # 返回提取的用户数据字典
    except Exception:
        return None, sid


# 简单版“全端下线”：遍历 Redis sess:* 找到属于该用户的会话并删除（小规模下可用）
def _revoke_user_sessions_simple(user_id: int) -> int:
    count = 0
    for key in redis_client.scan_iter("sess:*", count=100):
        try:
            uid = redis_client.get(key)
            if uid and int(uid) == user_id:
                redis_client.delete(key)
                count += 1
        except Exception:
            # 忽略单条错误，保持健壮
            pass
    return count


# 注册限速（防撞库/滥用） + 密码强度统一校验
def _password_ok(p: str) -> bool:
    if not p or len(p) < 8 or len(p) > 128:
        return False
    classes = 0
    classes += 1 if re.search(r"[A-Za-z]", p) else 0
    classes += 1 if re.search(r"\d", p) else 0
    classes += 1 if re.search(r"[^A-Za-z0-9]", p) else 0
    return classes >= 2


# ---- 路由 ----
# 注册接口会返回 409 表示邮箱/手机号已被占用（注册场景允许提示唯一性冲突）。
@auth.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    phone = (data.get("phone") or "").strip() or None
    pwd = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None

    # 基础限速：按 IP 10/小时；email 3/小时
    if not _rate_limit(f"rl:reg:ip:{_client_ip()}", 10, 3600) or (
        email and not _rate_limit(f"rl:reg:email:{email}", 3, 3600)
    ):
        return jsonify({"ok": False, "error": "Too many requests"}), 429

    # 密码强度
    if not _password_ok(pwd):
        return jsonify({"ok": False, "error": "Weak password"}), 400

    if not email and not phone:
        return jsonify({"ok": False, "error": "email or phone required"}), 400
    if email and not _email_re.match(email):
        return jsonify({"ok": False, "error": "Invalid email"}), 400

    with get_session() as s:
        # 重复检查
        if email and s.query(User).filter(User.email == email).first():
            return jsonify({"ok": False, "error": "Email already registered"}), 409
        if phone and s.query(User).filter(User.phone == phone).first():
            return jsonify({"ok": False, "error": "Phone already registered"}), 409

        user = User(
            uid=uuid4().hex[:12],
            email=email,
            phone=phone,
            display_name=display_name,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(user)
        s.flush()  # 获取 user.id

        cred = Credential(
            user_id=user.id,
            type="password",
            secret_hash=ph.hash(pwd),
            created_at=datetime.now(timezone.utc),
        )
        s.add(cred)

    return jsonify({"ok": True}), 201


# 登录接口统一返回 “Invalid credentials”，避免账号枚举。
@auth.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    pwd = data.get("password") or ""
    if not identifier or not pwd:
        return jsonify({"ok": False, "error": "Invalid credentials"}), 401

    # 简单限速：按 IP 和 identifier 双维度
    ip_key = f"rl:login:ip:{_client_ip()}"
    id_key = f"rl:login:id:{identifier.lower()}"
    if not _rate_limit(ip_key, RATE_LIMIT_LOGIN_PER_10MIN, 600) or not _rate_limit(
        id_key, RATE_LIMIT_LOGIN_PER_10MIN, 600
    ):
        # 避免枚举，返回同样的错误
        return jsonify({"ok": False, "error": "Invalid credentials"}), 401

    # 查找用户 + 密码凭据
    email = _norm_email(identifier) if _email_re.match(identifier) else None
    with get_session() as s:
        q = s.query(User)
        if email:
            q = q.filter(User.email == email)
        else:
            q = q.filter(User.phone == identifier)
        user = q.first()

        if not user or not user.is_active:
            return jsonify({"ok": False, "error": "Invalid credentials"}), 401

        # 提前提取 user.id，避免在会话关闭后访问 user 对象
        user_id = user.id

        cred = (
            s.query(Credential)
            .filter(Credential.user_id == user.id, Credential.type == "password")
            .first()
        )
        if not cred or not cred.secret_hash:
            return jsonify({"ok": False, "error": "Invalid credentials"}), 401

        try:
            ph.verify(cred.secret_hash, pwd)
            # 如果未来调整了 Argon2 参数，这里自动换新
            if ph.check_needs_rehash(cred.secret_hash):
                with get_session() as s2:
                    from sqlalchemy import select

                    c2 = (
                        s2.execute(select(Credential).filter(Credential.id == cred.id))
                        .scalars()
                        .first()
                    )
                    if c2:
                        c2.secret_hash = ph.hash(pwd)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid credentials"}), 401

    # 发会话
    # 会话关闭后，只使用 user_id
    sid = _issue_session(user_id)
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(
        COOKIE_NAME,
        sid,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    return resp, 200


@auth.post("/logout")
def logout():
    # 幂等
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        redis_client.delete(f"sess:{sid}")
    resp = make_response(jsonify({"ok": True}))
    # 置空 Cookie
    resp.set_cookie(COOKIE_NAME, "", max_age=0, path="/")
    return resp, 200


@auth.get("/me")
def me():
    user_data, sid = _get_user_from_cookie()  # 接收用户数据字典
    if not user_data:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return (
        jsonify(
            {
                "ok": True,
                "user": user_data,  # 直接使用提取的用户数据
            }
        ),
        200,
    )


@auth.post("/password/forgot")
def password_forgot():
    """
    输入: { "identifier": "<email>" }
    统一返回 200（防枚举）。开发期可返回 debug_token；生产请关闭并发送邮件。
    """
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip().lower()

    # 基础限速：每小时 IP 20 次 / 单 identifier 5 次
    if not _rate_limit(f"rl:pwf:ip:{_client_ip()}", 20, 3600) or not _rate_limit(
        f"rl:pwf:id:{identifier}", 5, 3600
    ):
        return jsonify({"ok": True}), 200

    token = None
    if identifier and _email_re.match(identifier):
        from sqlalchemy import select

        with get_session() as s:
            user = (
                s.execute(select(User).filter(User.email == identifier))
                .scalars()
                .first()
            )
            if user:
                token = secrets.token_urlsafe(32)
                redis_client.setex(f"pwreset:{token}", PWRESET_TOKEN_TTL, user.id)

                # 生产：发邮件（构造前端重置链接）
                if not DEBUG_RETURN_RESET_TOKEN:
                    try:
                        from mailer import send_reset_email

                        base = os.getenv("FRONTEND_BASE_URL") or (
                            request.host_url.rstrip("/")
                        )
                        # 前端路由示例：/cloudchat/reset_password?token=...
                        reset_link = f"{base}/cloudchat/reset_password?token={token}"
                        send_reset_email(
                            user.email, token, reset_link, PWRESET_TOKEN_TTL
                        )
                    except Exception as e:
                        current_app.logger.exception("send reset email failed: %s", e)

    resp = {"ok": True}
    if DEBUG_RETURN_RESET_TOKEN and token:
        resp["debug_token"] = token
        resp["debug_ttl"] = PWRESET_TOKEN_TTL
    return jsonify(resp), 200


# 这个“简单版强制下线”会 扫描 sess:*，把映射到该用户的会话删掉，适合当前规模。
# 后续要提效，再引入 user_sess:<uid> 反向索引。
@auth.post("/password/reset")
def password_reset():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_pwd = data.get("password") or ""

    if not token or not _password_ok(new_pwd):
        return jsonify({"ok": False, "error": "Invalid token or weak password"}), 400

    key = f"pwreset:{token}"
    pipe = redis_client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    val, _ = pipe.execute()
    if not val:
        return jsonify({"ok": False, "error": "Token invalid or expired"}), 400

    user_id = int(val)
    with get_session() as s:
        from sqlalchemy import select

        cred = (
            s.execute(
                select(Credential).filter(
                    Credential.user_id == user_id, Credential.type == "password"
                )
            )
            .scalars()
            .first()
        )
        if not cred:
            cred = Credential(
                user_id=user_id, type="password", created_at=datetime.now(timezone.utc)
            )
            s.add(cred)
        cred.secret_hash = ph.hash(new_pwd)

    revoked = 0
    if PWRESET_REVOKE_SESSIONS:
        revoked = _revoke_user_sessions_simple(user_id)

    # 返回 revoked_sessions，便于在日志里观察效果
    return jsonify({"ok": True, "revoked_sessions": int(revoked)}), 200


# 健康检查（检查依赖连通性）
@auth.get("/healthz")
def healthz():
    redis_ok = True
    db_ok = True
    try:
        redis_client.ping()
    except Exception:
        redis_ok = False
    try:
        with get_session() as s:
            s.execute(text("select 1"))
    except Exception:
        db_ok = False
    ok = redis_ok and db_ok
    return jsonify({"ok": ok, "redis": bool(redis_ok), "db": bool(db_ok)}), (
        200 if ok else 503
    )


@auth.after_request
def _auth_headers(resp):
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp
