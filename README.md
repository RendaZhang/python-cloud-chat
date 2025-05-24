# 🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务

## 📝 项目简介

这是一个基于 Flask 的轻量级 Python Web 服务，整合了阿里云 DashScope API，实现了以下功能：

- 🤖 与 AI 模型实时对话（流式输出）
- 🖼️ 基于 Stable Diffusion 的 AI 图像生成
- ✅ 支持 DashScope API Key 环境变量配置
- 💻 支持 macOS / Windows / Linux 开发环境
- 🌐 可与前端页面或第三方应用对接

---

## 🧱 项目结构与技术栈

- **后端框架**：Flask 2.0.1
- **核心依赖**：
  - `dashscope` （阿里云多模态大模型平台）
  - `openai`（预留扩展）
  - `requests` 用于网络请求
- **图像生成模型**：stable-diffusion-v1.5
- **聊天模型**：qwen-turbo-2025-04-28

---

## 📦 安装指南

### 1. 克隆项目
```bash
git clone https://gitee.com/RendaZhang/python-cloud-chat.git
cd python-cloud-chat
````

### 2. 创建并激活虚拟环境（推荐）

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

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 设置 DashScope API 密钥（推荐使用环境变量）

#### macOS/Linux:

```bash
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### Windows PowerShell:

```powershell
$env:DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

或直接添加到 `activate` 文件中。

---

## 🚀 启动服务

```bash
python app.py
```

运行后默认监听：

```
http://127.0.0.1:8080
```

---

## 📡 接口说明

### 🔹 POST `/chat`

AI 聊天接口（流式返回）

#### 请求：

```json
{
  "message": "你好，请介绍一下自己"
}
```

#### 返回（分段 JSON 流）：

```json
{"text": "你好，我是..."}
```

---

### 🔹 POST `/generate_image`

图像生成接口

#### 请求：

```json
{
  "prompt": "一只在阳光下打盹的橘猫"
}
```

#### 返回：

```json
{
  "image_urls": ["https://dashscope.aliyun.com/..."]
}
```

---

## 📁 文件说明

| 文件名                | 功能描述                    |
| ------------------ | ----------------------- |
| `app.py`           | 主应用，定义两个接口（聊天 + 图像生成）   |
| `requirements.txt` | 依赖列表                    |
| `.python-version`  | 指定 Python 版本（如使用 pyenv） |
| `README.md`        | 中文说明文档                  |
| `README.en.md`     | 英文说明文档（待优化）             |

---

## 🙌 贡献指南

1. Fork 本仓库
2. 新建分支 `feat_xxx`
3. 提交代码并附带说明
4. 提交 Pull Request，我们会尽快审核

---

## 🔐 License

仅供个人学习与展示使用，**请勿商用**。涉及 API Key 的部分请自行保管。

---

## 📬 联系方式

作者：张人大（Renda Zhang）
邮箱：[952402967@qq.com](mailto:952402967@qq.com)
个人网站：[https://rendazhang.com](https://rendazhang.com)
