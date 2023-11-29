from flask import Flask, request, jsonify, render_template, stream_with_context, Response, send_from_directory, url_for
from dashscope import Generation, ImageSynthesis
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
import io
import threading
from http import HTTPStatus
import time
import json
from urllib import request as urllib_request
import openai
import os

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)

@app.route('/generate_image', methods=['POST'])
def generate_image():
    prompt = request.json.get('prompt')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    
    rsp = ImageSynthesis.call(model='stable-diffusion-v1.5', prompt=prompt, size='512*512')
    
    if rsp.status_code == HTTPStatus.OK:
        image_urls = [result['url'] for result in rsp.output['results']]
        return jsonify({'image_urls': image_urls})
    else:
        return jsonify({'error': 'Failed to generate image'}), 500

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
    last_length = 0
    for response in response_generator:
        if "text" in response.output:
            current_message = response.output["text"]
            new_message = current_message[last_length:]
            last_length = len(current_message)
            yield json.dumps({"text": new_message}).encode('utf-8') + b'\n'

@app.route('/gpt_chat', methods=['POST'])
def gpt_chat():
    content = request.json
    user_message = content.get('message')

    response_json = gpt_generate_response(user_message)

    return Response(stream_with_context(response_json), content_type='application/json')

def gpt_generate_response(user_input):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Adjust model as needed
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_input}
            ]
        )
        assistant_reply = response['choices'][0]['message']['content']
        yield json.dumps({"text": assistant_reply}).encode('utf-8') + b'\n'
    except Exception as e:
        yield json.dumps({"error": str(e)}).encode('utf-8') + b'\n'

# Simulated Generator (for testing purposes)
def simulated_generator():
    messages = [
        "I am a",
        " large language model created by DAMO Academy",
        ". I am called QianWen",
        "."
    ]

    for message in messages:
        yield message
        time.sleep(1)

#@app.route('/chat', methods=['POST'])
def simulated_chat():
    user_message = request.json.get('message')

    # This is just a simulated response. In reality, you'd call your model here.
    def generate_response():
        for chunk in simulated_generator():
            yield json.dumps({"text": chunk}).encode('utf-8') + b'\n'

    return Response(stream_with_context(generate_response()), content_type='application/json')


if __name__ == '__main__':
    app.run(debug=True, port=8080)
