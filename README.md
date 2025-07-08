<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务](#-python-cloud-chat-%C2%B7-%E4%BA%91%E7%AB%AF-ai-%E8%81%8A%E5%A4%A9%E4%B8%8E%E5%9B%BE%E5%83%8F%E7%94%9F%E6%88%90%E6%9C%8D%E5%8A%A1)
  - [📝 项目简介](#-%E9%A1%B9%E7%9B%AE%E7%AE%80%E4%BB%8B)
  - [🧱 项目结构与技术栈](#-%E9%A1%B9%E7%9B%AE%E7%BB%93%E6%9E%84%E4%B8%8E%E6%8A%80%E6%9C%AF%E6%A0%88)
    - [Gunicorn + Gevent 的优势](#gunicorn--gevent-%E7%9A%84%E4%BC%98%E5%8A%BF)
  - [📦 安装指南](#-%E5%AE%89%E8%A3%85%E6%8C%87%E5%8D%97)
    - [1. 克隆项目](#1-%E5%85%8B%E9%9A%86%E9%A1%B9%E7%9B%AE)
    - [2. 创建并激活虚拟环境（推荐）](#2-%E5%88%9B%E5%BB%BA%E5%B9%B6%E6%BF%80%E6%B4%BB%E8%99%9A%E6%8B%9F%E7%8E%AF%E5%A2%83%E6%8E%A8%E8%8D%90)
      - [macOS/Linux:](#macoslinux)
      - [Windows PowerShell:](#windows-powershell)
    - [3. 安装依赖](#3-%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96)
    - [4. 设置 API 密钥（推荐使用环境变量）](#4-%E8%AE%BE%E7%BD%AE-api-%E5%AF%86%E9%92%A5%E6%8E%A8%E8%8D%90%E4%BD%BF%E7%94%A8%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F)
      - [macOS/Linux:](#macoslinux-1)
      - [Windows PowerShell:](#windows-powershell-1)
  - [🚀 启动服务](#-%E5%90%AF%E5%8A%A8%E6%9C%8D%E5%8A%A1)
  - [在 CentOS 7 部署与测试](#%E5%9C%A8-centos-7-%E9%83%A8%E7%BD%B2%E4%B8%8E%E6%B5%8B%E8%AF%95)
  - [📁 项目文件说明](#-%E9%A1%B9%E7%9B%AE%E6%96%87%E4%BB%B6%E8%AF%B4%E6%98%8E)
    - [📡 接口文档](#-%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3)
    - [📘 Python 轻量级后端开发指南](#-python-%E8%BD%BB%E9%87%8F%E7%BA%A7%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
  - [相关项目](#%E7%9B%B8%E5%85%B3%E9%A1%B9%E7%9B%AE)
    - [前端项目](#%E5%89%8D%E7%AB%AF%E9%A1%B9%E7%9B%AE)
    - [Nginx 项目](#nginx-%E9%A1%B9%E7%9B%AE)
  - [🙌 贡献指南](#-%E8%B4%A1%E7%8C%AE%E6%8C%87%E5%8D%97)
  - [🔐 License](#-license)
  - [📬 联系方式](#-%E8%81%94%E7%B3%BB%E6%96%B9%E5%BC%8F)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# 🌩️ Python Cloud Chat · 云端 AI 聊天与图像生成服务

* **Last Updated:** July 8, 2025, 21:40 (UTC+8)
* **作者:** 张人大（Renda Zhang）

---

## 📝 项目简介

这是一个基于 Flask 的轻量级 Python Web 服务，实现了以下功能。
项目最初在 CentOS 7 系统的阿里云香港轻量级服务器（2 vCPUs、1 GB RAM、40 GB SSD）上部署并测试：

- 🤖 与 AI 模型实时对话
- 🖼️ 基于 Stable Diffusion 的 AI 图像生成
- ✅ 支持 DashScope / OpenAI / Deepseek API Key 环境变量配置
- 💻 支持 macOS / Windows / Linux 开发环境
- 🌐 可与前端页面或第三方应用对接
- 🚀 使用 Gunicorn + Gevent 部署，支持高并发流式响应
- 🗄️ 使用 Redis 存储会话，DeepSeek 聊天接口支持多轮流式对话

---

## 🧱 项目结构与技术栈

- **后端框架**：Flask 2.0.1
- **核心依赖**：
  - `dashscope` （阿里云多模态大模型平台）
  - `openai`（Deepseek 和 ChatGpt 都可以使用 OpenAI SDK）
  - `requests` 用于网络请求
- **图像生成模型**：stable-diffusion-v1.5
- **聊天模型**：deepseek-chat, qwen-turbo-2025-04-28
- **WSGI 服务器**：Gunicorn + Gevent

---

### Gunicorn + Gevent 的优势

1. **并发处理能力**：协程模型使小内存服务器也能稳定处理流式请求。
2. **资源效率**：相比多线程/多进程更节省内存，适合 1GB 内存机器。
3. **稳定性**：Gunicorn 能自动管理工作进程并在崩溃后重启。
4. **流式响应优化**：Gevent 优化长连接，避免客户端超时。

---

## 📦 安装指南

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

---

## 🚀 启动服务

默认使用 **Gunicorn + Gevent** 作为 WSGI 服务器：

```bash
gunicorn --worker-class gevent --workers 2 --bind 0.0.0.0:5000 app:app
```

启动后在 `0.0.0.0:5000` 监听。

## 在 CentOS 7 部署与测试

以下步骤展示了在 CentOS 7 系统上部署 CloudChat，并通过 systemd 管理服务：

1. **准备工作目录**

```bash
mkdir -p /opt/cloudchat
cd /opt/cloudchat
# 将代码上传或 git clone 到此目录
```

2. **安装并配置 Redis**

```bash
# 安装 EPEL 仓库 和 Redis
sudo yum install epel-release -y
sudo yum install redis -y

# 启动 Redis 服务并设置开机自启
sudo systemctl start redis
sudo systemctl enable redis

# 检查 Redis 状态
sudo systemctl status redis
```

编辑 `/etc/redis.conf`，修改以下参数：

```bash
# 设置内存限制为 64MB
maxmemory 64mb
maxmemory-policy allkeys-lru

# 禁用持久化
save ""
appendonly no

# 启用内存碎片整理
activerehashing yes

# 设置密码 (可选但推荐）
requirepass your_redis_password

# 绑定到本地回环地址 (确保安全)
bind 127.0.0.1
```

重启并验证：

```bash
# 重启
sudo systemctl restart redis

# 如果没有设置密码可直接运行：
redis-cli info memory | grep maxmemory

# 如果设置了密码：
redis-cli
127.0.0.1:6379> AUTH your_redis_password
# 查看 Redis 内存使用
127.0.0.1:6379> INFO memory
# 手动清除 Redis 数据
127.0.0.1:6379> flushdb
# 查看活跃会话
keys *

```

3. **创建虚拟环境并安装依赖**

```bash
# 构建隔离环境：
python -m venv venv

# 激活环境后安装依赖：
source venv/bin/activate

# 安装依赖：
pip install -r requirements.txt

# 退出虚拟环境：
deactivate
```

4. **编写 systemd 服务文件**

在 `/etc/systemd/system/cloudchat.service` 中填写如下内容：

```ini
[Unit]
Description=CloudChat Flask App with Gunicorn
After=network.target redis.service

[Service]
User=root
WorkingDirectory=/opt/cloudchat
Environment="PATH=/opt/cloudchat/venv/bin"
Environment="DASHSCOPE_API_KEY=*****************"
Environment="DEEPSEEK_API_KEY=******************"
Environment="OPENAI_API_KEY=********************"
Environment="FLASK_SECRET_KEY=******************"
Environment="REDIS_PASSWORD=******************"
# **注意**：如下 ExecStart 的命令的换行和注释只是为了方便展示，
# * 使用的时候去掉命令包含的注释 和 换行符 和 '\'符号 以及 多余的空格
ExecStart=/opt/cloudchat/venv/bin/gunicorn \
   # 使用 Gevent 协程工作器
   --worker-class gevent \
   # 适合 2vCPU 的工作进程数（公式：CPU核心×2+1）
   --workers 2 \
   # 限制每个工作进程连接数为 50
   --worker-connections 50 \
   # worker 进程处理多少个请求后会被重启（防止内存泄漏，保持性能稳定）
   --max-requests 1000 \
   # 随机化重启阈值，避免同时重启
   --max-requests-jitter 50 \
   # 流式响应超时时间（5分钟）
   # 与 Nginx 的 `proxy_read_timeout 300s` 配合使用
   --timeout 300 \
   # 绑定端口
   --bind 0.0.0.0:5000 app:app

# 关键重启配置
Restart=always
RestartSec=3
KillSignal=SIGINT
ProtectSystem=full
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

参数说明：
```markdown
- `WorkingDirectory` 指向代码目录；
- `Environment` 中的密钥替换为实际值；
- `ExecStart` 使用 Gunicorn + Gevent 启动应用；
- `Restart` 相关配置保证服务异常后自动重启。
```

5. **启动并管理服务**

```bash
sudo systemctl daemon-reload        # 载入新服务
sudo systemctl start cloudchat      # 启动 CloudChat
sudo systemctl enable cloudchat     # 开机自启
sudo systemctl status cloudchat     # 查看运行状态
journalctl -u cloudchat.service -f  # 查看应用动态日志
```

修改 service 文件或代码后，可运行：
```bash
sudo systemctl daemon-reload
sudo systemctl restart cloudchat
```

如果你希望限制 systemd 的日志的保留时间或大小，
可以编辑 /etc/systemd/journald.conf 文件。
例如：
```bash
SystemMaxUse=100M  # 限制日志占用的最大磁盘空间为 100MB
MaxRetentionSec=7day  # 日志最多保留 7 天
```

修改后，重启 journald 服务：
```bash
sudo systemctl restart systemd-journald
```

6. **验证和监控**

检查工作进程：
```bash
# 应该看到 1 个 master 进程和 2 个 worker 进程
ps aux | grep gunicorn
```

测试接口：
```bash
curl -X POST localhost:5000/chat \
      -H "Content-Type: application/json" \
      -H "Referer: https://rendazhang.com" \
      -d '{"message": "Hello from curl!"}'
# 预期输出（分段）：
{"text": "Hello"}
{"text": "!"}
{"text": " It"}
{"text": "'s"}
{"text": " great to hear from"}
{"text": " you. How can"}
{"text": " I assist you today"}
{"text": "? \ud83d\ude0a"}
```

压力测试（安装 `siege` 后）：
```bash
siege -c 10 -t 30s http://localhost:5000/chat
```

内存监控：
```bash
htop
free -h
```

**内存不足处理**：
```markdown
如果内存使用接近 90%，可：
- 减少 `--workers` 到 1
- 降低 `--worker-connections` 值
```

---

## 📁 项目文件说明

| 文件名                | 功能描述                    |
| ------------------ | ----------------------- |
| `app.py`           | 主应用，提供聊天、DeepSeek 多轮对话、图像生成等接口 |
| `requirements.txt` | 依赖列表                    |
| `.python-version`  | 指定 Python 版本（如使用 pyenv） |
| `README.md`        | 中文说明文档                  |

### 📡 接口文档

[docs/api.md](docs/api.md): 主要描述了本服务提供的接口的请求与返回格式。

### 📘 Python 轻量级后端开发指南

[docs/lightweight_backend_development.md](docs/lightweight_backend_development.md): 涵盖会话存储、数据库优化、API 设计、缓存策略等多个方面。

---

## 相关项目

### 前端项目

* ✅ [Renda Zhang Web](https://github.com/RendaZhang/rendazhang.github.io)

### Nginx 项目

* ✅ [Nginx Conf](https://github.com/RendaZhang/nginx-conf)

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
* 邮箱：[952402967@qq.com](mailto:952402967@qq.com)
* 个人网站：[https://rendazhang.com](https://rendazhang.com)

> ⏰ **Maintainer**：@Renda — 如果本项目对你有帮助，请不要忘了点亮 ⭐️ Star 支持我们！
