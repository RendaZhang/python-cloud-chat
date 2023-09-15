from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from dashscope import Generation

app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    content = request.json
    user_message = content.get('message')

    response_json = generate_response(user_message)

    return Response(stream_with_context(response_json), content_type='application/json')

def generate_response(prompt_text):
    response_generator = Generation.call(
        model='qwen-turbo',
        prompt=prompt_text,
        stream=True,
        top_p=0.8
    )
    full_text = ""
    for response in response_generator:
        if "text" in response.output:
            yield jsonify({"text": response.output["text"]})

if __name__ == '__main__':
    app.run(debug=True, port=8080)
