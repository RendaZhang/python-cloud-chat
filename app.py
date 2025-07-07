"""Flask web service for Qwen chat and Stable Diffusion image generation."""

import json
import os
from http import HTTPStatus

import openai
from dashscope import Generation, ImageSynthesis
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)


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
    """Stream chat using DeepSeek model."""

    content = request.json
    user_message = content.get("message")

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    response_gen = generate_deepseek_response(user_message)
    return Response(stream_with_context(response_gen), content_type="application/json")


def generate_deepseek_response(prompt_text):
    """Generator yielding DeepSeek chat response."""

    client = openai.OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
    )
    stream = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt_text}],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield json.dumps({"text": delta}).encode("utf-8") + b"\n"


if __name__ == "__main__":
    # Start development server
    app.run(debug=True, port=8080)
