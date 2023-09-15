from flask import Flask, jsonify, request
from http import HTTPStatus
from dashscope import Generation

app = Flask(__name__)

@app.route('/')
def hello():
    return "Hello from Flask!"

@app.route('/chat', methods=['POST'])
def chat_with_ai():
    user_message = request.json.get('message', '')

    messages = [
        {'role': 'system', 'content': 'My name is Renda Zhang'},
        {'role': 'user', 'content': user_message}
    ]

    gen = Generation()
    response = gen.call(
        Generation.Models.qwen_turbo,
        messages=messages,
        result_format='message',
    )

    if response.status_code == HTTPStatus.OK:
        # Extract the assistant's response from the DashScope API's response
        assistant_message = response.output["choices"][0]["message"]["content"]
        return jsonify({"message": assistant_message}), HTTPStatus.OK
    else:
        error_message = f"Request id: {response.request_id}, Status code: {response.status_code}, error code: {response.code}, error message: {response.message}"
        return jsonify({"error": error_message}), HTTPStatus.INTERNAL_SERVER_ERROR

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

