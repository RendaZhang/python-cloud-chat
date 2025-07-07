<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务](#️-python-cloud-chat--云端-ai-聊天与图像生成服务)
  - [📝 项目简介](#-项目简介)
  - [🧱 项目结构与技术栈](#-项目结构与技术栈)
  - [📦 安装指南](#-安装指南)
    - [1. 克隆项目](#1-克隆项目)
    - [2. 创建并激活虚拟环境（推荐）](#2-创建并激活虚拟环境推荐)
      - [macOS/Linux:](#macoslinux)
      - [Windows PowerShell:](#windows-powershell)
    - [3. 安装依赖](#3-安装依赖)
    - [4. 设置 API 密钥（推荐使用环境变量）](#4-设置-api-密钥推荐使用环境变量)
      - [macOS/Linux:](#macoslinux-1)
      - [Windows PowerShell:](#windows-powershell-1)
  - [🚀 启动服务](#-启动服务)
  - [在 CentOS 7 部署与测试（示例）](#在-centos-7-部署与测试示例)
  - [📁 文件说明](#-文件说明)
  - [接口说明](#接口说明)
  - [🙌 贡献指南](#-贡献指南)
  - [🔐 License](#-license)
  - [📬 联系方式](#-联系方式)

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

### 4. 设置 API 密钥（推荐使用环境变量）

#### macOS/Linux:

```bash
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### Windows PowerShell:

```powershell
$env:DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
$env:DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

或直接添加到 `activate` 文件中。

---

## 🚀 启动服务

```bash
python app.py
```

运行后默认监听：

```
http://127.0.0.1:5000
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
   python -m venv venv
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
   Environment="DEEPSEEK_API_KEY=sk-******************"
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
   sudo systemctl daemon-reload        # 载入新服务
   sudo systemctl start cloudchat      # 启动 CloudChat
   sudo systemctl enable cloudchat     # 开机自启
   sudo systemctl status cloudchat     # 查看运行状态
   journalctl -u cloudchat.service -f  # 监控状态
   ```
   修改 service 文件或代码后，可运行：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart cloudchat
   ```
   如果你希望限制 systemd 的日志的保留时间或大小，可以编辑 /etc/systemd/journald.conf 文件。例如：
   ```bash
   SystemMaxUse=100M  # 限制日志占用的最大磁盘空间为 100MB
   MaxRetentionSec=7day  # 日志最多保留 7 天
   ```
   修改后，重启 journald 服务：
   ```bash
   sudo systemctl restart systemd-journald
   ```
5. **接口测试**
   ```bash
   curl -X POST localhost:5000/chat \
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

## 📁 文件说明

| 文件名                | 功能描述                    |
| ------------------ | ----------------------- |
| `app.py`           | 主应用，定义两个接口（聊天 + 图像生成）   |
| `requirements.txt` | 依赖列表                    |
| `.python-version`  | 指定 Python 版本（如使用 pyenv） |
| `README.md`        | 中文说明文档                  |

---

## 接口说明

* 📡 [接口文档](docs/api.md)

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

本项目采用 **MIT 协议** 开源发布。这意味着你可以自由地使用、修改并重新发布本仓库的内容，只需在分发时附上原始许可证声明。

---

## 📬 联系方式

作者：张人大（Renda Zhang）
邮箱：[952402967@qq.com](mailto:952402967@qq.com)
个人网站：[https://rendazhang.com](https://rendazhang.com)
