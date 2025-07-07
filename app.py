import json
from http import HTTPStatus

from dashscope import Generation, ImageSynthesis
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)


@app.route("/generate_image", methods=["POST"])
def generate_image():
    prompt = request.json.get("prompt")

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    rsp = ImageSynthesis.call(
        model="stable-diffusion-v1.5", prompt=prompt, size="512*512"
    )

    if rsp.status_code == HTTPStatus.OK:
        image_urls = [result["url"] for result in rsp.output["results"]]
        return jsonify({"image_urls": image_urls})
    else:
        return jsonify({"error": "Failed to generate image"}), 500


@app.route("/chat", methods=["POST"])
def chat():
    content = request.json
    user_message = content.get("message")

    response_json = generate_response(user_message)

    return Response(stream_with_context(response_json), content_type="application/json")


def generate_response(prompt_text):
    response_generator = Generation.call(
        model="qwen-turbo-2025-04-28", prompt=prompt_text, stream=True, top_p=0.8
    )
    last_length = 0
    for response in response_generator:
        if "text" in response.output:
            current_message = response.output["text"]
            new_message = current_message[last_length:]
            last_length = len(current_message)
            yield json.dumps({"text": new_message}).encode("utf-8") + b"\n"


if __name__ == "__main__":
    app.run(debug=True, port=8080)
