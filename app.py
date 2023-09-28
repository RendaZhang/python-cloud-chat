from flask import Flask, request, jsonify, render_template, stream_with_context, Response
from dashscope import Generation, ImageSynthesis, audio
import os
from http import HTTPStatus
import time
import json
from urllib import request as urllib_request

app = Flask(__name__)

@app.route('/transcribe_audio', methods=['POST'])
def transcribe_audio():
    audio_file = request.files.get('audio_file')
    
    if audio_file:
        temp_dir = 'temp'
        # Check if the temp directory exists, if not create it
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        
        # Save the uploaded file temporarily
        file_path = os.path.join(temp_dir, audio_file.filename)
        audio_file.save(file_path)

        # Call the transcription service and get the result
        task_response = audio.asr.Transcription.async_call(
            model='paraformer-v1',
            file_urls=[file_path]
        )

        transcription_response = audio.asr.Transcription.wait(task_response.output.task_id)

        #transcription_url = transcription_response.output['results'][0]['transcription_url']
        #transcription_results = json.loads(urllib_request.urlopen(transcription_url).read().decode('utf8'))

        #transcriptions = [sentence['text'] for sentence in transcription_results['transcripts'][0]['sentences']]

        # Delete the temporary file
        os.remove(file_path)

        return jsonify({'transcriptions': transcription_response})
    else:
        return jsonify({'error': 'No audio file uploaded'}), 400

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
