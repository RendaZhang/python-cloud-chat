"""Flask web service for Authetication"""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from argon2 import PasswordHasher
from flask import Blueprint, request, jsonify, make_response
from db import get_session
from models import User, Credential
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


# ---- 路由 ----
# 注册接口会返回 409 表示邮箱/手机号已被占用（注册场景允许提示唯一性冲突）。
@auth.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    phone = (data.get("phone") or "").strip() or None
    pwd = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None

    if not pwd or len(pwd) < 8:
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
    统一返回 200，避免枚举。开发期可返回 debug_token。
    速率限制: 按 IP 与 identifier 双维度。
    """
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip().lower()
    # 基础限速：每小时 IP 20 次，单 identifier 5 次
    if not _rate_limit(f"rl:pwf:ip:{_client_ip()}", 20, 3600) or not _rate_limit(
        f"rl:pwf:id:{identifier}", 5, 3600
    ):
        # 同样返回 200，防枚举
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
                # 生成一次性 token，Redis 保存 user_id
                token = secrets.token_urlsafe(32)
                redis_client.setex(f"pwreset:{token}", PWRESET_TOKEN_TTL, user.id)
                # TODO: 生产环境在这里发送邮件/短信，而不是返回 token

    resp = {"ok": True}
    if DEBUG_RETURN_RESET_TOKEN and token:
        resp["debug_token"] = token
        resp["debug_ttl"] = PWRESET_TOKEN_TTL
    return jsonify(resp), 200


@auth.post("/password/reset")
def password_reset():
    """
    输入: { "token": "...", "password": "NewStrongPass!" }
    校验 token，更新 password 凭据。token 一次性使用。
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_pwd = data.get("password") or ""

    if not token or len(new_pwd) < 8:
        return jsonify({"ok": False, "error": "Invalid token or weak password"}), 400

    key = f"pwreset:{token}"
    # 尝试一次性取回 token（近似原子：读后删）
    pipe = redis_client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    val, _ = pipe.execute()
    if not val:
        return jsonify({"ok": False, "error": "Token invalid or expired"}), 400

    user_id = int(val)
    # 更新/创建本地密码凭据
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

    return jsonify({"ok": True}), 200


# 健康检查（检查依赖连通性）
@auth.get("/healthz")
def healthz():
    try:
        redis_client.ping()
        healthy = True
    except Exception:
        healthy = False
    return jsonify({"ok": healthy}), (200 if healthy else 503)
