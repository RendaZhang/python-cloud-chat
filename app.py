from flask import Flask, request, jsonify, render_template, stream_with_context, Response
from dashscope import Generation
import json

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
    last_output_tokens = 0
    for response in response_generator:
        if "text" in response.output and "output_tokens" in response.usage:
            current_output_tokens = response.usage["output_tokens"]
            current_message = response.output["text"]
            
            # Calculate the start position of the new message chunk
            start_pos = len(current_message) - (current_output_tokens - last_output_tokens)
            new_message = current_message[start_pos:]
            
            last_output_tokens = current_output_tokens
            yield json.dumps({"text": new_message}).encode('utf-8') + b'\n'

if __name__ == '__main__':
    app.run(debug=True, port=8080)
