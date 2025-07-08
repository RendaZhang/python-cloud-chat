"""Flask web service for Qwen chat and Stable Diffusion image generation."""

import json
import os
import uuid
from http import HTTPStatus
import openai
import psutil
import redis
from apscheduler.schedulers.background import BackgroundScheduler
from dashscope import Generation, ImageSynthesis
from flask import (
    Flask,
    Response,
    jsonify,
    request,
    session,
    stream_with_context,
)
from flask_session import Session

app = Flask(__name__)

# ===== 环境变量配置 =====
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default-secret-key")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
redis_password = os.getenv("REDIS_PASSWORD", "")

# ===== Redis 会话配置 =====
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_REDIS"] = redis.Redis(
    host="localhost",
    port=6379,
    password=redis_password,
    db=0,
    socket_timeout=5,
)
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1小时过期
Session(app)


@app.route("/generate_image", methods=["POST"])
def generate_image():
    """Return image URLs generated from the given prompt."""

    prompt = request.json.get("prompt")  # Text description for image generation

    if not prompt:
        # Client must provide a prompt
        return jsonify({"error": "Prompt is required"}), 400

    rsp = ImageSynthesis.call(
        model="stable-diffusion-v1.5", prompt=prompt, size="512*512"
    )  # Call DashScope image API

    if rsp.status_code == HTTPStatus.OK:
        # Extract returned image URLs and respond to client
        image_urls = [result["url"] for result in rsp.output["results"]]
        return jsonify({"image_urls": image_urls})
    else:
        # Propagate error to client if generation fails
        return jsonify({"error": "Failed to generate image"}), 500


@app.route("/chat", methods=["POST"])
def chat():
    """Stream chat responses for the provided message."""

    content = request.json
    user_message = content.get("message")  # Text from the client

    response_json = generate_response(user_message)

    # Stream back each chunk as JSON lines
    return Response(stream_with_context(response_json), content_type="application/json")


def generate_response(prompt_text):
    """Generator yielding incremental chat responses."""

    response_generator = Generation.call(
        model="qwen-turbo-2025-04-28", prompt=prompt_text, stream=True, top_p=0.8
    )  # Request streaming chat completion
    last_length = 0
    for response in response_generator:
        if "text" in response.output:
            current_message = response.output["text"]
            new_message = current_message[last_length:]
            last_length = len(current_message)
            # Yield only the newly generated portion as a JSON line
            yield json.dumps({"text": new_message}).encode("utf-8") + b"\n"


@app.route("/deepseek_chat", methods=["POST"])
def deepseek_chat():
    """支持多轮对话的流式聊天接口"""

    if "messages" not in session:
        session["session_id"] = str(uuid.uuid4())
        session["messages"] = [
            {"role": "system", "content": "请你扮演张人大，英文名 Renda Zhang"}
        ]

    content = request.json
    user_message = content.get("message")

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    session["messages"].append({"role": "user", "content": user_message})

    MAX_HISTORY = 6
    if len(session["messages"]) > MAX_HISTORY * 2 + 1:
        session["messages"] = [session["messages"][0]] + session["messages"][
            -MAX_HISTORY * 2 :
        ]

    session.modified = True

    response_gen = generate_deepseek_response(session["messages"])
    return Response(stream_with_context(response_gen), content_type="application/json")


def generate_deepseek_response(messages):
    """生成器：流式返回 DeepSeek 响应并维护对话历史"""

    client = openai.OpenAI(
        api_key=deepseek_api_key,
        base_url="https://api.deepseek.com/v1",
    )

    full_response = []
    stream = client.chat.completions.create(
        model="deepseek-chat",
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
            session.modified = True


@app.route("/reset_chat", methods=["POST"])
def reset_chat():
    """重置当前会话的对话历史"""
    if "messages" in session:
        session["messages"] = [
            {"role": "system", "content": "请你扮演张人大，英文名 Renda Zhang"}
        ]
        session.modified = True
    return jsonify({"status": "对话历史已重置"})


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
            app.logger.warning("⚠️ 系统内存使用过高!")
    except Exception as e:
        app.logger.error(f"监控错误: {str(e)}")


scheduler = BackgroundScheduler()
scheduler.add_job(monitor_resources, "interval", minutes=1)
scheduler.start()
