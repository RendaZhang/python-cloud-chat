from flask import Flask, request, jsonify, Response
from dashscope import Generation

app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    message = data['message']

    response_generator = Generation.call(
        model='qwen-turbo',
        prompt=message,
        stream=True,
        top_p=0.8
    )

    def generate():
        head_idx = 0
        for resp in response_generator:
            paragraph = resp.output['text']
            yield paragraph[head_idx:]
            if paragraph.rfind('\n') != -1:
                head_idx = paragraph.rfind('\n') + 1

    return Response(generate(), content_type='text/plain')

@app.route('/')
def hello():
    return "Hello from Flask!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
