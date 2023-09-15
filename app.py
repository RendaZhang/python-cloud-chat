from flask import Flask, request, stream_with_context, Response
from http import HTTPStatus
from dashscope import Generation

app = Flask(__name__)

@app.route('/')
def hello():
    return "Hello from Flask!"

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message', '')

    # The AI response will be streamed using the generator function
    def generate():
        prompt_text = message
        response_generator = Generation.call(
            model='qwen-turbo',
            prompt=prompt_text,
            stream=True,
            top_p=0.8)

        head_idx = 0
        for resp in response_generator:
            paragraph = resp.output['text']
            yield paragraph[head_idx:len(paragraph)]
            if paragraph.rfind('\n') != -1:
                head_idx = paragraph.rfind('\n') + 1

    return Response(stream_with_context(generate()), content_type='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

