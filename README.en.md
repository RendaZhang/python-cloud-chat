# 🌩️ Python Cloud Chat · AI Chat & Image Generation Backend

* **Last Updated:** July 7, 2025, 17:50 (UTC+8)
* **Author:** Renda Zhang

## 📝 Project Overview

**Python Cloud Chat** is a lightweight Flask backend that integrates [DashScope](https://dashscope.aliyun.com/) (Alibaba Cloud's large model platform) to provide:

- 🤖 Real-time streaming AI chat with `qwen-turbo-2025-04-28`
- 🖼️ Text-to-image generation using `stable-diffusion-v1.5`
- ⚙️ Easy environment variable configuration for API keys
- 🌍 Compatible with macOS / Windows / Linux development environments
- 🌐 Able to integrate with front-end pages or third-party apps

---

## 🧱 Tech Stack

- **Framework**: Flask 2.0.1
- **Dependencies**:
  - `dashscope`: Access to Qwen and Stable Diffusion models
  - `openai`: Reserved for future extension
  - `requests`: HTTP networking
- **Image Model**: `stable-diffusion-v1.5`
- **Chat Model**: `qwen-turbo-2025-04-28`

---

## 📦 Installation

### 1. Clone the project
```bash
git clone https://gitee.com/RendaZhang/python-cloud-chat.git
cd python-cloud-chat
````

### 2. Create & activate a virtual environment

#### macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

#### Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set your DashScope API Key

#### macOS/Linux:

```bash
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### Windows PowerShell:

```powershell
$env:DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

Or add it to your venv's `activate` script.

---

## 🚀 Run the App

```bash
python app.py
```

Server will run at:

```
http://127.0.0.1:8080
```

## Deployment & Testing on CentOS 7

The following steps illustrate how to deploy CloudChat on a fresh CentOS 7 system and manage it via systemd.

1. **Prepare a working directory**
   ```bash
   mkdir -p /opt/cloudchat
   cd /opt/cloudchat
   # Upload your code or git clone the repo here
   ```
2. **Create a virtual environment and install dependencies**
   ```bash
   virtualenv -p /root/.pyenv/versions/3.9.7/bin/python venv
   source venv/bin/activate
   pip install -r requirements.txt
   deactivate
   ```
   - `virtualenv` creates an isolated Python environment.
   - `source` activates the venv so packages install inside it.
   - `deactivate` exits the venv when done.
3. **Create a systemd service file**
   Write `/etc/systemd/system/cloudchat.service` with the following content:
   ```ini
   [Unit]
   Description=CloudChat Flask App
   After=network.target

   [Service]
   User=root
   WorkingDirectory=/opt/cloudchat
   Environment="PATH=/opt/cloudchat/venv/bin"
   Environment="DASHSCOPE_API_KEY=sk-******************"
   Environment="OPENAI_API_KEY=sk-***********************"
   ExecStart=/opt/cloudchat/venv/bin/python app.py

   [Install]
   WantedBy=multi-user.target
   ```
   - `WorkingDirectory` points to where the code lives.
   - Replace the API keys in `Environment` with your own values.
   - `ExecStart` launches the app using the venv Python.
4. **Start and manage the service**
   ```bash
   sudo systemctl daemon-reload     # Load new unit files
   sudo systemctl start cloudchat   # Start CloudChat
   sudo systemctl enable cloudchat  # Auto-start on boot
   sudo systemctl status cloudchat  # Check current status
   ```
   If you modify the service or the code later, run:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart cloudchat
   ```
5. **Test the endpoint**
   ```bash
   curl -X POST localhost:8080/chat \
        -H "Content-Type: application/json" \
        -H "Referer: https://rendazhang.com" \
        -d '{"message": "Hello from curl!"}'
   ```
   You should see chunked output similar to:
   ```json
   {"text": "Hello"}
   {"text": "!"}
   {"text": " It"}
   {"text": "'s"}
   {"text": " great to hear from"}
   {"text": " you. How can"}
   {"text": " I assist you today"}
   {"text": "? \ud83d\ude0a"}
   ```

---

## 📡 API Endpoints

### 🔹 POST `/chat`

Interactive AI chat endpoint (returns streaming JSON)

**Request Body:**

```json
{
  "message": "Tell me about yourself."
}
```

**Response (chunked):**

```json
{"text": "Hello, I am..."}
```

---

### 🔹 POST `/generate_image`

AI-powered image generation endpoint

**Request Body:**

```json
{
  "prompt": "A sleeping orange cat under the sun"
}
```

**Response:**

```json
{
  "image_urls": ["https://dashscope.aliyun.com/..."]
}
```

---

## 📁 Project Structure

| File               | Description                          |
| ------------------ | ------------------------------------ |
| `app.py`           | Main Flask application with 2 routes |
| `requirements.txt` | Python dependency list               |
| `.python-version`  | Python version (for pyenv users)     |
| `README.md`        | Chinese documentation                |
| `README.en.md`     | English documentation                |

---

## 🙌 Contributing

1. Fork this repo and clone it locally
2. Install dependencies and **pre-commit**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   pre-commit install
   ```
3. Create a new branch `feat_xyz` for development
4. Before committing, you can run:
   ```bash
   pre-commit run --all-files
   ```
5. Submit a Pull Request for review
   > ✅ All commits must pass pre-commit checks

---

## 🔐 License

This project is for **personal and educational use only**.
Do **not** use it in commercial or production settings. API Keys should be kept private.

---

## 📬 Contact

**Author**: Renda Zhang
**Email**: [952402967@qq.com](mailto:952402967@qq.com)
**Website**: [https://rendazhang.com](https://rendazhang.com)
