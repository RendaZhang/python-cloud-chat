from flask import Flask, request, jsonify, Response
from dashscope import Generation

app = Flask(__name__)

@app.route('/cloudchat/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data['message']
    
    # Use the dashscope SDK to get the response
    response_generator = Generation.call(
        model='qwen-turbo',
        prompt=user_message,
        stream=True,
        top_p=0.8
    )
    
    def generate():
        head_idx = 0
        for resp in response_generator:
            paragraph = resp.output['text']
            # Extract the new part of the text to send
            new_text = paragraph[head_idx:len(paragraph)]
            if paragraph.rfind('\n') != -1:
                head_idx = paragraph.rfind('\n') + 1
            # Yield the new part of the text as a JSON string
            yield f"data: {json.dumps({'message': new_text})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=8080, threaded=True)
