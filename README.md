<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Python 后端服务](#python-%E5%90%8E%E7%AB%AF%E6%9C%8D%E5%8A%A1)
  - [介绍](#%E4%BB%8B%E7%BB%8D)
    - [功能描述](#%E5%8A%9F%E8%83%BD%E6%8F%8F%E8%BF%B0)
    - [技术栈](#%E6%8A%80%E6%9C%AF%E6%A0%88)
    - [关联项目](#%E5%85%B3%E8%81%94%E9%A1%B9%E7%9B%AE)
      - [前端：](#%E5%89%8D%E7%AB%AF)
      - [Nginx：](#nginx)
  - [安装与部署](#%E5%AE%89%E8%A3%85%E4%B8%8E%E9%83%A8%E7%BD%B2)
    - [本地开发（macOS / Windows / Linux）](#%E6%9C%AC%E5%9C%B0%E5%BC%80%E5%8F%91macos--windows--linux)
    - [生产部署（Ubuntu 24 + Nginx + systemd）](#%E7%94%9F%E4%BA%A7%E9%83%A8%E7%BD%B2ubuntu-24--nginx--systemd)
  - [环境变量](#%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F)
  - [数据库与会话](#%E6%95%B0%E6%8D%AE%E5%BA%93%E4%B8%8E%E4%BC%9A%E8%AF%9D)
  - [接口快速测试](#%E6%8E%A5%E5%8F%A3%E5%BF%AB%E9%80%9F%E6%B5%8B%E8%AF%95)
  - [故障排查](#%E6%95%85%E9%9A%9C%E6%8E%92%E6%9F%A5)
  - [安全基线](#%E5%AE%89%E5%85%A8%E5%9F%BA%E7%BA%BF)
  - [变更日志](#%E5%8F%98%E6%9B%B4%E6%97%A5%E5%BF%97)
    - [2025-08](#2025-08)
  - [项目文档](#%E9%A1%B9%E7%9B%AE%E6%96%87%E6%A1%A3)
    - [接口文档](#%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3)
    - [Python 轻量级后端开发指南](#python-%E8%BD%BB%E9%87%8F%E7%BA%A7%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
    - [故障排查及 BUG 追踪](#%E6%95%85%E9%9A%9C%E6%8E%92%E6%9F%A5%E5%8F%8A-bug-%E8%BF%BD%E8%B8%AA)
    - [开发需求](#%E5%BC%80%E5%8F%91%E9%9C%80%E6%B1%82)
  - [🤝 贡献指南](#-%E8%B4%A1%E7%8C%AE%E6%8C%87%E5%8D%97)
  - [🔐 License](#-license)
  - [📬 联系方式](#-%E8%81%94%E7%B3%BB%E6%96%B9%E5%BC%8F)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Python 后端服务

- **作者**: 张人大（Renda Zhang）
- **最后更新**: June 21, 2026, 21:35 (UTC+08:00)

---

## 介绍

本项目部署在阿里云轻量级服务器（Ubuntu 24，2 vCPU / 1 GB RAM / 40 GB SSD）并在线运行。服务通过 **Nginx 反向代理** 提供对外路径 `/cloudchat/*`，后端由 **Gunicorn + Gevent** 承载。

### 功能描述

* **用户认证**：注册、登录、登出、`/me`；Redis 会话（Cookie：`cc_auth`）。
* **密码找回**：`/auth/password/forgot|reset`，邮件通过 **阿里云 DirectMail (SMTP)** 发送；重置后支持**会话强制下线（简单版）**。
* **健康检查**：`/auth/healthz` 同时探测 Redis 与 PostgreSQL。
* **聊天能力**：`/deepseek_chat`（流式 JSON 行）与 `reset_chat`；应用会话 Cookie：`cc_app`。
* **路由前缀**：对内蓝图前缀 `/auth`；对外经 Nginx 为 `/cloudchat/auth/*`。
* **计划**：Google / WeChat 登录、MFA、会话索引优化（避免扫描）。

### 技术栈

* **语言/框架**：Python 3.13，Flask 3.x
* **认证/密码**：argon2-cffi（Argon2id）
* **数据库**：PostgreSQL 16 + PgBouncer（transaction 模式）+ SQLAlchemy；驱动 **psycopg2**
* **缓存/会话/限速**：Redis（allkeys-lru，AOF/RDB 关闭，小内存优化）
* **WSGI/并发**：Gunicorn + gevent（流式响应）
* **邮件**：Aliyun DirectMail（SMTP STARTTLS:80 或 SSL:465）

### 关联项目

#### 前端：

* 📁 [Renda Zhang Web](https://github.com/RendaZhang/rendazhang)（Astro + React + TS）

#### Nginx：

* 📁 [Nginx Conf](https://github.com/RendaZhang/nginx-conf)（统一反代与安全头/HSTS/CDN 接入）

---

## 安装与部署

### 本地开发（macOS / Windows / Linux）

```bash
# 1) 克隆
git clone https://gitee.com/RendaZhang/python-cloud-chat.git
cd python-cloud-chat

# 2) 虚拟环境
python3.13 -m venv venv
source venv/bin/activate    # Windows: .\venv\Scripts\Activate.ps1

# 3) 依赖
pip install -r requirements.txt

# 4) 基础环境（示例）
export FLASK_SECRET_KEY=dev_secret
export REDIS_PASSWORD=dev_redis_pass
export DASHSCOPE_API_KEY=...
export DEEPSEEK_API_KEY=...

# 5) 运行（开发）
python app.py  # 或自行配置 debug server
```

### 生产部署（Ubuntu 24 + Nginx + systemd）

* **反代**：Nginx 挂载 `/cloudchat/*` 到后端 `127.0.0.1:5000`
* **服务**：`/etc/systemd/system/cloudchat.service`（使用 venv 与 EnvironmentFile）
* **内存优化**：Redis/CloudChat/PostgreSQL/PgBouncer 均设置 `MemoryMax` 与 OOM 分级
* **会话**：Redis 本机；PostgreSQL 本机 5432；PgBouncer 监听 6432

> 详细的运维参数、systemd override、内核与 journald 优化，见 Nginx 项目下的文档内容 ：📄 [CloudChat 服务器配置运行手册](https://github.com/RendaZhang/nginx-conf/blob/master/docs/SERVER_RUNBOOK.md)。

---

## 环境变量

> 生产环境建议集中保存在：`/etc/cloudchat/cloudchat.env`（权限 600）

```bash
# 基础
PATH=/opt/cloudchat/venv/bin
FLASK_SECRET_KEY=***

# 模型/第三方
OPENAI_API_KEY=***
DEEPSEEK_API_KEY=***
DASHSCOPE_API_KEY=***

# Redis
REDIS_PASSWORD=***

# 数据库（通过 PgBouncer 6432；psycopg2 驱动）
DATABASE_URL=postgresql+psycopg2://cloudchat:***@127.0.0.1:6432/cloudchat

# 会话/Cookie
AUTH_COOKIE_NAME=cc_auth
APP_SESSION_COOKIE_NAME=cc_app
COOKIE_SECURE=1                 # 生产必须 1
SESSION_TTL_SECONDS=604800

# 密码找回
PWRESET_TOKEN_TTL=900
PWRESET_REVOKE_SESSIONS=1
DEBUG_RETURN_RESET_TOKEN=0      # 生产关闭

# 邮件（DirectMail，新加坡示例）
SMTP_HOST=smtpdm-ap-southeast-1.aliyuncs.com
SMTP_PORT=80
SMTP_USER=noreply@mail.rendazhang.com
SMTP_PASS=***
SMTP_TLS=1
MAIL_FROM=noreply@mail.rendazhang.com
MAIL_SENDER_NAME=CloudChat
FRONTEND_BASE_URL=https://www.rendazhang.com
```

---

## 数据库与会话

* **Schema**：三表（`users` / `credentials` / `sessions`）— 详见 `schema.sql`

  * 唯一约束：`users.email/phone/uid`；`credentials(user_id,type)`；`(provider,provider_uid)`
  * 索引：`lower(email)`、`sessions(user_id)`、`sessions(expires_at)`
* **连接池**：PgBouncer（`pool_mode=transaction`，`default_pool_size=10`）
* **SQLAlchemy**：推荐创建 Engine 时使用 `pool_pre_ping=True, pool_recycle=1800`
* **会话**：Redis 键 `sess:<sid> -> user_id`；密码重置后**全端下线**（扫描删除，后续可升级为集合索引）

---

## 接口快速测试

> 对外统一前缀：`https://www.rendazhang.com/cloudchat`

```bash
# 注册
curl -X POST https://www.rendazhang.com/cloudchat/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"P@ssw0rd!","display_name":"Alice"}'

# 登录（保存 Cookie）
curl -i -c cookies.txt -X POST https://www.rendazhang.com/cloudchat/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"alice@example.com","password":"P@ssw0rd!"}'

# 当前用户
auth='-b cookies.txt'
curl $auth https://www.rendazhang.com/cloudchat/auth/me

# 忘记密码（邮件带重置链接）
curl -X POST https://www.rendazhang.com/cloudchat/auth/password/forgot \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"alice@example.com"}'

# 健康检查
curl -s https://www.rendazhang.com/cloudchat/auth/healthz
```

---

## 故障排查

* **健康检查失败（503）**：确认 Redis/PostgreSQL 服务；查看 `journalctl -u cloudchat` 与 `pgbouncer.log`。
* **邮件未达**：检查 DirectMail 域验证（SPF/DKIM/DMARC）、端口（推荐 80+STARTTLS）、SMTP 用户/密码是否为**发件地址**。
* **登录正常但聊天异常**：确认前端 `fetch` 均设置 `credentials: 'include'`，并检查 Nginx 是否正确透传 `Set-Cookie` 与流式响应头。
* **高并发**：根据 Redis/数据库负载调节 PgBouncer 池与 Gunicorn worker 数；必要时放宽 `MemoryMax`。

---

## 安全基线

* 强制 HTTPS（HSTS 已启用）与 `COOKIE_SECURE=1`
* 认证蓝图响应 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`
* 失败统一文案（登录/忘记密码防枚举）；注册/忘记密码限速
* Argon2id；登录成功可按需 `check_needs_rehash` 平滑升级哈希

---

## 变更日志

### 2025-08

* 新增：注册/登录/登出/`/me`；Redis 会话 Cookie `cc_auth`；应用 Cookie `cc_app`
* 新增：`/auth/password/forgot|reset` + DirectMail 邮件发送；重置后强制下线（简单版）
* 新增：`/auth/healthz` 同时探测 Redis + PostgreSQL
* 更新：`DATABASE_URL` 指向 PgBouncer（`postgresql+psycopg2://...@127.0.0.1:6432/cloudchat`）
* 更新：Nginx 对外统一前缀 `/cloudchat/*`；后端蓝图前缀 `/auth`

> 目前，未登录用户是可以使用聊天相关的接口。
>
> 如需仅允许已登录用户使用聊天相关接口，可在后端给 `/deepseek_chat` 与 `/reset_chat` 添加对 `cc_auth` 的检查（例如读取并校验 `sess:<sid>`）。

---

## 项目文档

### 接口文档

主要描述了本服务提供的接口的请求与返回格式，详细情况参考文档内容：📄 [API 文档](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/API.md#api-%E6%96%87%E6%A1%A3)

### Python 轻量级后端开发指南

涵盖会话存储、数据库优化、API 设计、缓存策略等多个方面，具体请参考文档内容：📄 [轻量级后端开发指南](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/LIGHTWEIGHT_BACKEND_DEVELOPMENT.md#python-%E8%BD%BB%E9%87%8F%E7%BA%A7%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)

### 故障排查及 BUG 追踪

BUG 记录和修复状态请查看文档：📄 [后端 BUG 跟踪数据库](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/TROUBLESHOOTING.md#%E5%90%8E%E7%AB%AF-bug-%E8%B7%9F%E8%B8%AA%E6%95%B0%E6%8D%AE%E5%BA%93)

### 开发需求

详情参考文档：📄 [需求文档](https://github.com/RendaZhang/python-cloud-chat/blob/master/docs/REQUIREMENTS.md#%E9%A1%B9%E7%9B%AE%E9%9C%80%E6%B1%82%E6%B8%85%E5%8D%95)

---

## 🤝 贡献指南

- Fork & clone this repo.
- 进入虚拟环境：
   ```bash
   # 如果还没安装虚拟环境，执行命令：python -m venv venv
   source venv/bin/activate
   ```
- 安装依赖并启用 **pre-commit**:
   ```bash
   pip install pre-commit
   pre-commit install
   ```
- 在每次提交前，钩子会自动运行。
- README 和 docs 下的文档会自动更新 Doctoc 目录（若本地未安装则跳过）。
- 你也可以手动触发：
  ```bash
  pre-commit run --all-files
  ```

> ✅ 所有提交必须通过 pre-commit 检查；CI 会阻止不符合规范的 PR。

---

## 🔐 License

本项目以 **MIT License** 发布，你可以自由使用与修改。请在分发时保留原始许可证声明。

---

## 📬 联系方式

* 联系人：张人大（Renda Zhang）
* 📧 邮箱：[952402967@qq.com](mailto:952402967@qq.com)

> ⏰ **Maintainer**：@Renda — 如果本项目对你有帮助，请不要忘了点亮 ⭐️ Star 支持我们！
