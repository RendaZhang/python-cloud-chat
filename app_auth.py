from __future__ import annotations
import os
import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import redis
from argon2 import PasswordHasher
from flask import Blueprint, request, jsonify, make_response

from db import get_session
from models import User, Credential

# ---- 配置 ----
COOKIE_NAME = "session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"  # 若需在 HTTP 下本机测试，设为 0
COOKIE_SAMESITE = "Lax"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
RATE_LIMIT_LOGIN_PER_10MIN = 10

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
auth = Blueprint("auth", __name__, url_prefix="/cloudchat/auth")

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
            return user, sid
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
    sid = _issue_session(user.id)
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
    user, sid = _get_user_from_cookie()
    if not user:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return (
        jsonify(
            {
                "ok": True,
                "user": {
                    "id": user.id,
                    "uid": user.uid,
                    "email": user.email,
                    "phone": user.phone,
                    "display_name": user.display_name,
                    "is_active": user.is_active,
                },
            }
        ),
        200,
    )


# 可选：健康检查（检查依赖连通性）
@auth.get("/healthz")
def healthz():
    try:
        redis_client.ping()
        healthy = True
    except Exception:
        healthy = False
    return jsonify({"ok": healthy}), (200 if healthy else 503)
