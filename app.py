"""Flask web service for Deepseek chat"""

from apscheduler.schedulers.background import BackgroundScheduler
from flask import (
    Flask,
    Response,
    jsonify,
    request,
    session,
    stream_with_context,
)
from flask_session import Session
from app_auth import auth as auth_bp
from chat_guide_prompt import build_chat_guide_prompt
import json
import os
import uuid
import time
import openai
import psutil
import redis
from security_policy import (
    CHAT_RATE_LIMIT_PER_MINUTE,
    MAX_CHAT_MESSAGE_CHARS,
    MAX_CHAT_SESSION_BYTES,
    MAX_JSON_BODY_BYTES,
    MAX_SYSTEM_PROMPT_CHARS,
    MODEL_MAX_RETRIES,
    MODEL_TIMEOUT_SECONDS,
    RequestValidationError,
    bounded_env,
    positive_int_env,
    rate_limit_allowed,
    require_json_object,
    required_env,
    string_field,
    trim_chat_history,
    trusted_client_ip,
    trusted_hosts_from_env,
)
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)

# ===== 环境变量配置 =====

app.secret_key = required_env(
    "FLASK_SECRET_KEY",
    min_length=16,
    forbidden_values=(
        "default-secret-key",
        "dev-secret-key",
        "dev_secret",
        "change-me",
    ),
)
deepseek_api_key = required_env("DEEPSEEK_API_KEY")
redis_password = os.getenv("REDIS_PASSWORD", "")

# ===== 全局可配置常量 =====

# 系统提示语，可根据需要修改角色设定
DEFAULT_SYSTEM_PROMPT = bounded_env(
    "SYSTEM_PROMPT",
    "请你扮演张人大，英文名 Renda Zhang",
    max_length=MAX_SYSTEM_PROMPT_CHARS,
)
# Qwen 聊天模型名称
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo-2025-04-28")
# DeepSeek 聊天模型名称
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
# DeepSeek API 基础地址
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
# Stable Diffusion 图像模型名称
SD_MODEL = os.getenv("SD_MODEL", "stable-diffusion-v1.5")
# 生成图像的分辨率
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "512*512")
# 保留的历史对话轮数
MAX_HISTORY = positive_int_env("MAX_HISTORY", 6, maximum=20)
# 受控 Chat Guide 模式；缺省值保持原聊天路径，其他值拒绝
CHAT_GUIDE_MODE_PUBLIC_SITE = "public_site"
# Redis 服务配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_TIMEOUT = positive_int_env("REDIS_TIMEOUT", 5, maximum=30)
# Model request inactivity timeout. The outer Nginx/Gunicorn timeout remains longer.
DEEPSEEK_TIMEOUT_SECONDS = positive_int_env(
    "DEEPSEEK_TIMEOUT_SECONDS", MODEL_TIMEOUT_SECONDS, maximum=300
)
# 会话过期时间（秒）1小时过期
SESSION_EXPIRE = positive_int_env(
    "SESSION_EXPIRE", 3600, minimum=60, maximum=30 * 24 * 3600
)

# ===== Redis 会话配置 =====
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_REDIS"] = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=redis_password,
    db=REDIS_DB,
    socket_timeout=REDIS_TIMEOUT,
    socket_connect_timeout=REDIS_TIMEOUT,
    retry_on_timeout=False,
)
app.config["PERMANENT_SESSION_LIFETIME"] = SESSION_EXPIRE
app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BODY_BYTES
app.config["TRUSTED_HOSTS"] = trusted_hosts_from_env()
app.config["SESSION_COOKIE_NAME"] = os.getenv("APP_SESSION_COOKIE_NAME", "cc_app")
# 可保持和认证 Cookie 一致的安全属性
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "1") == "1"
app.config["SESSION_COOKIE_HTTPONLY"] = True

# 登录和注册接口
app.register_blueprint(auth_bp)

Session(app)


@app.errorhandler(RequestValidationError)
def handle_request_validation(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_error):
    return jsonify({"error": "Request body is too large"}), 413


@app.route("/deepseek_chat", methods=["POST"])
def deepseek_chat():
    """支持多轮对话的流式聊天接口"""

    content = require_json_object(request)
    user_message = string_field(
        content, "message", max_length=MAX_CHAT_MESSAGE_CHARS, strip=True
    )
    guide_mode = string_field(content, "guideMode", max_length=32, strip=True)
    preset_id = string_field(content, "presetId", max_length=64, strip=True)
    locale = string_field(content, "locale", max_length=16, strip=True)

    if not user_message:
        return jsonify({"error": "Message is required"}), 400
    if guide_mode not in (None, CHAT_GUIDE_MODE_PUBLIC_SITE):
        raise RequestValidationError("guideMode is invalid")

    client_ip = trusted_client_ip(
        request.remote_addr, request.headers.get("X-Forwarded-For")
    )
    if not rate_limit_allowed(
        app.config["SESSION_REDIS"],
        f"rl:chat:ip:{client_ip}",
        CHAT_RATE_LIMIT_PER_MINUTE,
        60,
    ):
        return jsonify({"error": "Too many requests"}), 429

    if "messages" not in session:
        session["session_id"] = str(uuid.uuid4())
        session["messages"] = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]

    session["messages"].append({"role": "user", "content": user_message})
    session["messages"] = trim_chat_history(
        session["messages"],
        max_rounds=MAX_HISTORY,
        max_bytes=MAX_CHAT_SESSION_BYTES,
    )

    session.modified = True

    model_messages = session["messages"]
    if guide_mode == CHAT_GUIDE_MODE_PUBLIC_SITE:
        guide_prompt = build_chat_guide_prompt(
            user_message,
            preset_id=preset_id,
            locale=locale,
        )
        model_messages = [
            session["messages"][0],
            {"role": "user", "content": guide_prompt.prompt},
        ]

    response_gen = generate_deepseek_response(model_messages)
    return Response(stream_with_context(response_gen), content_type="application/json")


def generate_deepseek_response(messages):
    """生成器：流式返回 DeepSeek 响应并维护对话历史"""

    client = openai.OpenAI(
        api_key=deepseek_api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=DEEPSEEK_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )

    full_response = []
    stream = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=2000,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            full_response.append(delta)
            yield json.dumps({"text": delta}).encode("utf-8") + b"\n"

    if full_response:
        ai_message = "".join(full_response)
        if "messages" in session:
            session["messages"].append({"role": "assistant", "content": ai_message})
            session["messages"] = trim_chat_history(
                session["messages"],
                max_rounds=MAX_HISTORY,
                max_bytes=MAX_CHAT_SESSION_BYTES,
            )
            session.modified = True


@app.route("/reset_chat", methods=["POST"])
def reset_chat():
    """重置当前会话的对话历史"""

    if "messages" in session:
        session["messages"] = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        session.modified = True
    return jsonify({"status": "Reset chat history successfully"})


@app.route("/test", methods=["GET"])
def cache_test():
    """返回动态内容以用于 Nginx 缓存测试"""

    return jsonify({"timestamp": time.time(), "request_id": str(uuid.uuid4())})


# ===== 系统监控 =====
def monitor_resources():
    """监控系统资源使用情况"""
    try:
        mem = psutil.virtual_memory()
        redis_conn = app.config["SESSION_REDIS"]
        redis_info = redis_conn.info("memory")

        app.logger.info(
            f"系统内存: {mem.used/1024/1024:.1f}MB/{mem.total/1024/1024:.1f}MB | "
            f"Redis内存: {int(redis_info['used_memory'])/1024/1024:.1f}MB"
        )

        if mem.percent > 80:
            app.logger.warning("WARN: 系统内存使用过高!")
    except Exception as e:
        app.logger.error(f"监控错误: {str(e)}")


if os.getenv("ENABLE_SCHEDULER", "0") == "1":
    scheduler = BackgroundScheduler()
    scheduler.add_job(monitor_resources, "interval", minutes=1)
    scheduler.start()
