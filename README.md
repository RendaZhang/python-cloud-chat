<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务](#-python-cloud-chat-%C2%B7-%E4%BA%91%E7%AB%AF-ai-%E8%81%8A%E5%A4%A9%E4%B8%8E%E5%9B%BE%E5%83%8F%E7%94%9F%E6%88%90%E6%9C%8D%E5%8A%A1)
  - [📝 项目简介](#-%E9%A1%B9%E7%9B%AE%E7%AE%80%E4%BB%8B)
  - [🧱 项目结构与技术栈](#-%E9%A1%B9%E7%9B%AE%E7%BB%93%E6%9E%84%E4%B8%8E%E6%8A%80%E6%9C%AF%E6%A0%88)
  - [📦 安装指南](#-%E5%AE%89%E8%A3%85%E6%8C%87%E5%8D%97)
    - [1. 克隆项目](#1-%E5%85%8B%E9%9A%86%E9%A1%B9%E7%9B%AE)
    - [2. 创建并激活虚拟环境（推荐）](#2-%E5%88%9B%E5%BB%BA%E5%B9%B6%E6%BF%80%E6%B4%BB%E8%99%9A%E6%8B%9F%E7%8E%AF%E5%A2%83%E6%8E%A8%E8%8D%90)
      - [macOS/Linux:](#macoslinux)
      - [Windows PowerShell:](#windows-powershell)
    - [3. 安装依赖](#3-%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96)
    - [4. 设置 DashScope API 密钥（推荐使用环境变量）](#4-%E8%AE%BE%E7%BD%AE-dashscope-api-%E5%AF%86%E9%92%A5%E6%8E%A8%E8%8D%90%E4%BD%BF%E7%94%A8%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F)
      - [macOS/Linux:](#macoslinux-1)
      - [Windows PowerShell:](#windows-powershell-1)
  - [🚀 启动服务](#-%E5%90%AF%E5%8A%A8%E6%9C%8D%E5%8A%A1)
  - [在 CentOS 7 部署与测试（示例）](#%E5%9C%A8-centos-7-%E9%83%A8%E7%BD%B2%E4%B8%8E%E6%B5%8B%E8%AF%95%E7%A4%BA%E4%BE%8B)
  - [📡 接口说明](#-%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E)
    - [🔹 POST `/chat`](#-post-chat)
      - [请求：](#%E8%AF%B7%E6%B1%82)
      - [返回（分段 JSON 流）：](#%E8%BF%94%E5%9B%9E%E5%88%86%E6%AE%B5-json-%E6%B5%81)
    - [🔹 POST `/generate_image`](#-post-generate_image)
      - [请求：](#%E8%AF%B7%E6%B1%82-1)
      - [返回：](#%E8%BF%94%E5%9B%9E)
  - [📁 文件说明](#-%E6%96%87%E4%BB%B6%E8%AF%B4%E6%98%8E)
  - [🙌 贡献指南](#-%E8%B4%A1%E7%8C%AE%E6%8C%87%E5%8D%97)
  - [🔐 License](#-license)
  - [📬 联系方式](#-%E8%81%94%E7%B3%BB%E6%96%B9%E5%BC%8F)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# 🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务

* **Last Updated:** July 7, 2025, 17:50 (UTC+8)
* **作者:** 张人大（Renda Zhang）

## 📝 项目简介

这是一个基于 Flask 的轻量级 Python Web 服务，整合了阿里云 DashScope API，实现了以下功能。
项目最初在 CentOS 7 系统的阿里云香港轻量级服务器（2 vCPUs、1 GB RAM、40 GB SSD）上部署并测试：

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

## 在 CentOS 7 部署与测试（示例）

以下步骤展示了在全新 CentOS 7 系统上部署 CloudChat，并通过 systemd 管理服务：

1. **准备工作目录**
   ```bash
   mkdir -p /opt/cloudchat
   cd /opt/cloudchat
   # 将代码上传或 git clone 到此目录
   ```
2. **创建虚拟环境并安装依赖**
   ```bash
   virtualenv -p /root/.pyenv/versions/3.9.7/bin/python venv
   source venv/bin/activate
   pip install -r requirements.txt
   deactivate
   ```
   - `virtualenv` 用于构建隔离环境；
   - `source` 激活环境后安装依赖；
   - `deactivate` 退出虚拟环境。
3. **编写 systemd 服务文件**
   在 `/etc/systemd/system/cloudchat.service` 中填写如下内容：
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
   - `WorkingDirectory` 指向代码目录；
   - `Environment` 中的密钥替换为实际值；
   - `ExecStart` 使用虚拟环境中的 Python 启动应用。
4. **启动并管理服务**
   ```bash
   sudo systemctl daemon-reload     # 载入新服务
   sudo systemctl start cloudchat   # 启动 CloudChat
   sudo systemctl enable cloudchat  # 开机自启
   sudo systemctl status cloudchat  # 查看运行状态
   ```
   修改 service 文件或代码后，可运行：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart cloudchat
   ```
5. **接口测试**
   ```bash
   curl -X POST localhost:8080/chat \
        -H "Content-Type: application/json" \
        -H "Referer: https://rendazhang.com" \
        -d '{"message": "Hello from curl!"}'
   ```
   预期输出（分段）：
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

1. Fork 本仓库并克隆到本地
2. 安装依赖及 **pre-commit**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   pre-commit install
   ```
3. 新建分支 `feat_xxx` 开发并提交
4. 提交前可手动运行：
   ```bash
   pre-commit run --all-files
   ```
5. 提交 Pull Request，我们会尽快审核
   > ✅ 所有提交必须通过 pre-commit 检查

---

## 🔐 License

仅供个人学习与展示使用，**请勿商用**。涉及 API Key 的部分请自行保管。

---

## 📬 联系方式

作者：张人大（Renda Zhang）
邮箱：[952402967@qq.com](mailto:952402967@qq.com)
个人网站：[https://rendazhang.com](https://rendazhang.com)
