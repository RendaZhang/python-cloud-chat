from flask import Flask, request, jsonify, render_template, stream_with_context, Response
from dashscope import Generation
import time
import json

app = Flask(__name__)

#@app.route('/chat', methods=['POST'])
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
    last_length = 0
    for response in response_generator:
        if "text" in response.output:
            current_message = response.output["text"]
            new_message = current_message[last_length:]
            last_length = len(current_message)
            yield json.dumps({"text": new_message}).encode('utf-8') + b'\n'

# Simulated Generator (for testing purposes)
def simulated_generator():
    messages = [
        "I am a",
        "I am a large language model created by DAMO Academy",
        ". I am called QianWen",
        "."
    ]
    
    for message in messages:
        yield message
        time.sleep(1)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')

    # This is just a simulated response. In reality, you'd call your model here.
    def generate_response():
        for chunk in simulated_generator():
            yield json.dumps({"text": chunk}).encode('utf-8') + b'\n'

    return Response(stream_with_context(generate_response()), content_type='application/json')


if __name__ == '__main__':
    app.run(debug=True, port=8080)
