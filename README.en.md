# 🌩️ Python Cloud Chat · AI Chat & Image Generation Backend

## 📝 Project Overview

**Python Cloud Chat** is a lightweight Flask backend that integrates [DashScope](https://dashscope.aliyun.com/) (Alibaba Cloud's large model platform) to provide:

- 🤖 Real-time streaming AI chat with `qwen-turbo-2025-04-28`
- 🖼️ Text-to-image generation using `stable-diffusion-v1.5`
- ⚙️ Easy environment variable configuration for API keys
- 🌍 Compatible with macOS / Windows / Linux development environments

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
git clone https://gitee.com/your-repo/python-cloud-chat.git
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

1. Fork this repo
2. Create a new branch `feat_xyz`
3. Commit your code with clear messages
4. Submit a Pull Request for review

---

## 🔐 License

This project is for **personal and educational use only**.
Do **not** use it in commercial or production settings. API Keys should be kept private.

---

## 📬 Contact

**Author**: Renda Zhang
**Email**: [952402967@qq.com](mailto:952402967@qq.com)
**Website**: [https://rendazhang.com](https://rendazhang.com)