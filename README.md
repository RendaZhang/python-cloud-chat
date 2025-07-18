<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Python Cloud Chat · 云端 AI 聊天与图像生成服务](#python-cloud-chat-%C2%B7-%E4%BA%91%E7%AB%AF-ai-%E8%81%8A%E5%A4%A9%E4%B8%8E%E5%9B%BE%E5%83%8F%E7%94%9F%E6%88%90%E6%9C%8D%E5%8A%A1)
  - [项目简介](#%E9%A1%B9%E7%9B%AE%E7%AE%80%E4%BB%8B)
  - [项目结构与技术栈](#%E9%A1%B9%E7%9B%AE%E7%BB%93%E6%9E%84%E4%B8%8E%E6%8A%80%E6%9C%AF%E6%A0%88)
    - [Gunicorn + Gevent 的优势](#gunicorn--gevent-%E7%9A%84%E4%BC%98%E5%8A%BF)
  - [在 Ubuntu 部署与测试](#%E5%9C%A8-ubuntu-%E9%83%A8%E7%BD%B2%E4%B8%8E%E6%B5%8B%E8%AF%95)
  - [关联项目](#%E5%85%B3%E8%81%94%E9%A1%B9%E7%9B%AE)
    - [前端项目](#%E5%89%8D%E7%AB%AF%E9%A1%B9%E7%9B%AE)
    - [Nginx 项目](#nginx-%E9%A1%B9%E7%9B%AE)
  - [安装和部署指南](#%E5%AE%89%E8%A3%85%E5%92%8C%E9%83%A8%E7%BD%B2%E6%8C%87%E5%8D%97)
    - [1. 克隆项目](#1-%E5%85%8B%E9%9A%86%E9%A1%B9%E7%9B%AE)
    - [2. 创建并激活虚拟环境（推荐）](#2-%E5%88%9B%E5%BB%BA%E5%B9%B6%E6%BF%80%E6%B4%BB%E8%99%9A%E6%8B%9F%E7%8E%AF%E5%A2%83%E6%8E%A8%E8%8D%90)
      - [macOS/Linux:](#macoslinux)
      - [Windows PowerShell:](#windows-powershell)
    - [3. 安装依赖](#3-%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96)
    - [4. 设置 API 密钥（推荐使用环境变量）](#4-%E8%AE%BE%E7%BD%AE-api-%E5%AF%86%E9%92%A5%E6%8E%A8%E8%8D%90%E4%BD%BF%E7%94%A8%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F)
      - [macOS/Linux:](#macoslinux-1)
      - [Windows PowerShell:](#windows-powershell-1)
    - [5. 启动服务](#5-%E5%90%AF%E5%8A%A8%E6%9C%8D%E5%8A%A1)
  - [项目文件说明](#%E9%A1%B9%E7%9B%AE%E6%96%87%E4%BB%B6%E8%AF%B4%E6%98%8E)
    - [接口文档](#%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3)
    - [Python 轻量级后端开发指南](#python-%E8%BD%BB%E9%87%8F%E7%BA%A7%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
    - [故障排查及 BUG 追踪](#%E6%95%85%E9%9A%9C%E6%8E%92%E6%9F%A5%E5%8F%8A-bug-%E8%BF%BD%E8%B8%AA)
    - [开发需求](#%E5%BC%80%E5%8F%91%E9%9C%80%E6%B1%82)
  - [🙌 贡献指南](#-%E8%B4%A1%E7%8C%AE%E6%8C%87%E5%8D%97)
  - [🔐 License](#-license)
  - [📬 联系方式](#-%E8%81%94%E7%B3%BB%E6%96%B9%E5%BC%8F)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Python Cloud Chat · 云端 AI 聊天与图像生成服务

* **Last Updated:** July 18, 2025, 15:30 (UTC+8)
* **作者:** 张人大（Renda Zhang）

---

## 项目简介

项目目前在 Ubuntu 24 系统的阿里云香港轻量级服务器（2 vCPUs、1 GB RAM、40 GB SSD）上部署并测试。

这是一个基于 Flask 的轻量级 Python Web 服务，实现了以下功能。

- 🤖 与 AI 模型实时对话
- 🖼️ 基于 Stable Diffusion 的 AI 图像生成
- ✅ 支持 DashScope / OpenAI / Deepseek API Key 环境变量配置
- 💻 支持 macOS / Windows / Linux 开发环境
- 🌐 可与前端页面或第三方应用对接
- 🚀 使用 Gunicorn + Gevent 部署，支持高并发流式响应
- 🗄️ 使用 Redis 存储会话，DeepSeek 聊天接口支持多轮流式对话

---

## 项目结构与技术栈

- **后端框架**：Flask 3.1.1
- **核心依赖**：
  - `dashscope` （阿里云多模态大模型平台）
  - `openai`（Deepseek 和 ChatGpt 都可以使用 OpenAI SDK）
  - `requests` 用于网络请求
- **图像生成模型**：stable-diffusion-v1.5
- **聊天模型**：deepseek-chat, qwen-turbo-2025-04-28
- **WSGI 服务器**：Gunicorn 23.0.0 + Gevent 25.5.1

---

### Gunicorn + Gevent 的优势

1. **并发处理能力**：协程模型使小内存服务器也能稳定处理流式请求。
2. **资源效率**：相比多线程/多进程更节省内存，适合 1GB 内存机器。
3. **稳定性**：Gunicorn 能自动管理工作进程并在崩溃后重启。
4. **流式响应优化**：Gevent 优化长连接，避免客户端超时。

---

## 在 Ubuntu 部署与测试

在 Ubuntu 系统上安装并配置 Redis，并通过 systemd 部署和管理后端 CloudChat 服务。

具体步骤请参考 Nginx 项目的文档内容：📄 [后端迁移](https://github.com/RendaZhang/nginx-conf/blob/master/docs/MIGRATION_GUIDE.md#%E5%90%8E%E7%AB%AF%E8%BF%81%E7%A7%BB)

---

## 关联项目

### 前端项目

具体情况和网站页面功能描述请参考前端项目：📁 [Renda Zhang Web](https://github.com/RendaZhang/rendazhang)

### Nginx 项目

具体情况和项目部署请参考 Nginx 项目：📁 [Nginx Conf](https://github.com/RendaZhang/nginx-conf)

---

## 安装和部署指南

具体的操作步骤请参考 Nginx 项目的文档内容：📄 [后端迁移](https://github.com/RendaZhang/nginx-conf/blob/master/docs/MIGRATION_GUIDE.md#%E5%90%8E%E7%AB%AF%E8%BF%81%E7%A7%BB)

如下是通用的基本步骤描述。

### 1. 克隆项目

```bash
git clone https://gitee.com/RendaZhang/python-cloud-chat.git
cd python-cloud-chat
```

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
export DASHSCOPE_API_KEY=your_dashscope_api_key
export DEEPSEEK_API_KEY=your_deepseek_api_key
export REDIS_PASSWORD=your_redis_pass
export FLASK_SECRET_KEY=your_flask_secret_key
```

#### Windows PowerShell:

```powershell
$env:DASHSCOPE_API_KEY="your_dashscope_api_key"
$env:DEEPSEEK_API_KEY="your_deepseek_api_key"
$env:REDIS_PASSWORD="your_redis_pass"
$env:FLASK_SECRET_KEY="your_flask_secret_key"
```

或直接添加到 `activate` 文件中。

可选的环境变量示例：

```bash
# 自定义模型或会话配置
export QWEN_MODEL="qwen-turbo-2025-04-28"
export SD_MODEL="stable-diffusion-v1.5"
export MAX_HISTORY=6
```

### 5. 启动服务

默认使用 **Gunicorn + Gevent** 作为 WSGI 服务器。

启动后 Gunicorn 服务在 `0.0.0.0:5000` 监听。

---

## 项目文件说明

| 文件名              | 功能描述                |
| ------------------ | ----------------------- |
| `app.py`           | 主应用，提供聊天、多轮对话、图像生成等接口 |
| `requirements.txt` | 项目依赖列表             |
| `README.md`        | 中文说明文档             |

### 接口文档

主要描述了本服务提供的接口的请求与返回格式，详细情况参考文档内容：📄 [API Doc](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/api.md#api-%E6%96%87%E6%A1%A3)

### Python 轻量级后端开发指南

涵盖会话存储、数据库优化、API 设计、缓存策略等多个方面，具体请参考文档内容：📄 [Light Weight Backend Development](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/lightweight_backend_development.md)


### 故障排查及 BUG 追踪

BUG 记录和修复状态请查看文档：📄 [Troubleshooting](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/TROUBLESHOOTING.md#%E5%90%8E%E7%AB%AF-bug-%E8%B7%9F%E8%B8%AA%E6%95%B0%E6%8D%AE%E5%BA%93)

### 开发需求

详情参考文档：📄 [需求文档](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/REQUIREMENTS.md#%E9%A1%B9%E7%9B%AE%E9%9C%80%E6%B1%82%E6%B8%85%E5%8D%95)

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

* 联系人：张人大（Renda Zhang）
* 📧 邮箱：[952402967@qq.com](mailto:952402967@qq.com)
* 🌐 个人网站：[https://rendazhang.com](https://rendazhang.com)

> ⏰ **Maintainer**：@Renda — 如果本项目对你有帮助，请不要忘了点亮 ⭐️ Star 支持我们！
