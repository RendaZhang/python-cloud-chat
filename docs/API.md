<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [API 文档](#api-%E6%96%87%E6%A1%A3)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [通用规范](#%E9%80%9A%E7%94%A8%E8%A7%84%E8%8C%83)
    - [请求与响应](#%E8%AF%B7%E6%B1%82%E4%B8%8E%E5%93%8D%E5%BA%94)
    - [Cookie 与会话](#cookie-%E4%B8%8E%E4%BC%9A%E8%AF%9D)
    - [速率限制（后端内置）](#%E9%80%9F%E7%8E%87%E9%99%90%E5%88%B6%E5%90%8E%E7%AB%AF%E5%86%85%E7%BD%AE)
  - [鉴权接口（`/auth/*`）](#%E9%89%B4%E6%9D%83%E6%8E%A5%E5%8F%A3auth)
    - [注册用户 — `POST /auth/register`](#%E6%B3%A8%E5%86%8C%E7%94%A8%E6%88%B7--post-authregister)
    - [登录 — `POST /auth/login`](#%E7%99%BB%E5%BD%95--post-authlogin)
    - [登出 — `POST /auth/logout`](#%E7%99%BB%E5%87%BA--post-authlogout)
    - [当前用户 — `GET /auth/me`](#%E5%BD%93%E5%89%8D%E7%94%A8%E6%88%B7--get-authme)
    - [忘记密码 — `POST /auth/password/forgot`](#%E5%BF%98%E8%AE%B0%E5%AF%86%E7%A0%81--post-authpasswordforgot)
    - [重置密码 — `POST /auth/password/reset`](#%E9%87%8D%E7%BD%AE%E5%AF%86%E7%A0%81--post-authpasswordreset)
    - [健康检查 — `GET /auth/healthz`](#%E5%81%A5%E5%BA%B7%E6%A3%80%E6%9F%A5--get-authhealthz)
  - [聊天与工具接口](#%E8%81%8A%E5%A4%A9%E4%B8%8E%E5%B7%A5%E5%85%B7%E6%8E%A5%E5%8F%A3)
    - [DeepSeek 多轮对话（流式） — `POST /deepseek_chat`](#deepseek-%E5%A4%9A%E8%BD%AE%E5%AF%B9%E8%AF%9D%E6%B5%81%E5%BC%8F--post-deepseek_chat)
    - [重置聊天历史 — `POST /reset_chat`](#%E9%87%8D%E7%BD%AE%E8%81%8A%E5%A4%A9%E5%8E%86%E5%8F%B2--post-reset_chat)
    - [缓存测试 — `GET /test`](#%E7%BC%93%E5%AD%98%E6%B5%8B%E8%AF%95--get-test)
  - [前端对接要点（Astro + React + TS）](#%E5%89%8D%E7%AB%AF%E5%AF%B9%E6%8E%A5%E8%A6%81%E7%82%B9astro--react--ts)
    - [登录/注册页](#%E7%99%BB%E5%BD%95%E6%B3%A8%E5%86%8C%E9%A1%B5)
    - [个人信息（Profile / 顶栏）](#%E4%B8%AA%E4%BA%BA%E4%BF%A1%E6%81%AFprofile--%E9%A1%B6%E6%A0%8F)
    - [忘记/重置密码页](#%E5%BF%98%E8%AE%B0%E9%87%8D%E7%BD%AE%E5%AF%86%E7%A0%81%E9%A1%B5)
    - [DeepSeek 聊天页](#deepseek-%E8%81%8A%E5%A4%A9%E9%A1%B5)
    - [安全与网络](#%E5%AE%89%E5%85%A8%E4%B8%8E%E7%BD%91%E7%BB%9C)
  - [错误码一览](#%E9%94%99%E8%AF%AF%E7%A0%81%E4%B8%80%E8%A7%88)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# API 文档

- **作者**: 张人大（Renda Zhang）
- **最后更新**: August 15, 2025, 02:50 (UTC+08:00)

---

## 简介

* **Base URL（对外）**：`https://www.rendazhang.com/cloudchat`
* **统一前缀**：鉴权接口挂载在 `/cloudchat/auth/*`
* **鉴权模型**：基于 Cookie 的会话（`cc_auth`）+ 应用会话（`cc_app`）

---

## 通用规范

### 请求与响应

* **请求头**：`Content-Type: application/json`（除 GET）。
* **响应格式**：

  * 成功：`{ "ok": true, ... }`
  * 失败：`{ "ok": false, "error": "..." }`
* **缓存控制**：认证蓝图默认返回 `Cache-Control: no-store` 等安全头。
* **跨域**：同域部署；前端请求需带 `credentials: 'include'` 才能携带 Cookie。

### Cookie 与会话

* **`cc_auth`（认证 Cookie）**：

  * 设置于登录成功；`HttpOnly; SameSite=Lax; Secure=<生产开启>`；`Max-Age=604800(7d)`；`Path=/`。
  * Redis 存储：`sess:<sid> -> <user_id>`；密码重置成功后可强制下线（当前实现：扫描并删除该用户所有会话）。
* **`cc_app`（Flask-Session Cookie）**：

  * 用于应用侧会话（如聊天历史）；`HttpOnly; SameSite=Lax; Secure=<生产开启>`。

### 速率限制（后端内置）

| 场景   | 维度      | 配额        |
| ---- | ------- | --------- |
| 注册   | IP      | 10 / 小时   |
| 注册   | Email   | 3 / 小时    |
| 登录   | IP & 账号 | 10 / 10分钟 |
| 忘记密码 | IP      | 20 / 小时   |
| 忘记密码 | 账号      | 5 / 小时    |

> 触发限速返回 `429 Too Many Requests`（注册）或统一 401（登录场景防枚举）/ 200（忘记密码防枚举）。

---

## 鉴权接口（`/auth/*`）

> 对外完整路径需加前缀 `/cloudchat`。例如：`POST /cloudchat/auth/login`

### 注册用户 — `POST /auth/register`

* **Body**：

```json
{
  "email": "alice@example.com",   // 必填
  "phone": "+86-13800000000",    // 可选
  "password": "P@ssw0rd!",        // 必填，≥8 且至少包含两类字符（字母/数字/特殊）
  "display_name": "Alice"         // 可选
}
```

* **响应**：

  * `201 {"ok": true}`
  * `400 {"ok": false, "error": "Weak password | Invalid email | email required"}`
  * `409 {"ok": false, "error": "Email already registered | Phone already registered"}`
  * `429 {"ok": false, "error": "Too many requests"}`
* **说明**：Email 必填，服务端去空格并统一为小写；Phone 可选；同一 Email/Phone 只能注册一次。成功注册后系统会向邮箱发送一封欢迎邮件。

### 登录 — `POST /auth/login`

* **Body**：

```json
{ "identifier": "alice@example.com", "password": "P@ssw0rd!" }
```

* **成功**：`200 {"ok": true}`，并在响应头设置：

  * `Set-Cookie: cc_auth=<sid>; HttpOnly; SameSite=Lax; Secure(生产); Max-Age=604800; Path=/`
* **失败**：`401 {"ok": false, "error": "Invalid credentials"}`（统一文案，防账号枚举）。

### 登出 — `POST /auth/logout`

* **成功**：`200 {"ok": true}`，并清空 `cc_auth` Cookie。
* **说明**：幂等；无论是否已登录都返回 OK。

### 当前用户 — `GET /auth/me`

* **成功**：`200`

```json
{
  "ok": true,
  "user": {
    "id": 2,
    "uid": "b0b5d8f178f1",
    "email": "alice@example.com",
    "phone": null,
    "display_name": "Alice",
    "is_active": true
  }
}
```

* **失败**：`401 {"ok": false, "error": "Unauthorized"}`

### 忘记密码 — `POST /auth/password/forgot`

* **Body**：`{ "identifier": "alice@example.com" }`
* **响应**：
  * **始终** `200 {"ok": true}`（防枚举）；生产环境通过邮件发送重置链接。
  * 重置链接示例（15 分钟有效）：
    * `https://www.rendazhang.com/reset_password?token=<TOKEN>`

### 重置密码 — `POST /auth/password/reset`

* **Body**：

```json
{ "token": "<TOKEN>", "password": "NewP@ssw0rd42!" }
```

* **成功**：`200 {"ok": true, "revoked_sessions": 7}`（`revoked_sessions` 为被强制下线的会话数）并向用户发送密码重置成功邮件。
* **失败**：`400 {"ok": false, "error": "Token invalid or expired | Invalid token or weak password"}`

### 健康检查 — `GET /auth/healthz`

* **成功**：`200 {"ok": true, "redis": true, "db": true}`
* **失败**：`503 {"ok": false, "redis": false|true, "db": false|true}`

---

## 聊天与工具接口

> 这些接口默认在同一域下，无需额外鉴权即可调用；如需仅限已登录用户访问，可在后端增加校验 `cc_auth` 的装饰器。

### DeepSeek 多轮对话（流式） — `POST /deepseek_chat`

* **说明**：

  * 采用 **流式 JSON 行** 返回（`Transfer-Encoding: chunked`，`Content-Type: application/json`）。
  * 会话历史存储在 `cc_app`（Flask-Session）中，默认保留 **`MAX_HISTORY=6`** 轮；系统提示词可通过环境变量覆盖。
* **请求体**：

```json
{ "message": "你好，DeepSeek" }
```

* **返回示例**（每行一段）：

```json
{"text":"Hello"}
{"text":"!"}
{"text":" How are you?"}
```

### 重置聊天历史 — `POST /reset_chat`

* **返回**：`200 {"status": "Reset chat history successfully"}`

### 缓存测试 — `GET /test`

* **返回**：`200 {"timestamp": 1752421640.8777, "request_id": "uuid"}`（配合 Nginx 可观察 `X-Cache-Status`）。

---

## 前端对接要点（Astro + React + TS）

### 登录/注册页

* **注册**：提交上述 JSON；显示 400/409 具体错误文案；达到注册速率限制显示“稍后再试”。
* **登录**：成功后浏览器将接收 `cc_auth`，前端无需保存；失败统一展示“账号或密码错误”。

### 个人信息（Profile / 顶栏）

* 页面加载时请求 `GET /cloudchat/auth/me`：
  * 200：渲染用户信息（`display_name`/`email`），显示“登出”按钮。
  * 401：视为未登录，显示“登录/注册”。

### 忘记/重置密码页

* **页面**：`/reset_password`。
* **流程**：

  1. 从 `location.search` 解析 `token`。
  2. 前端对新密码做**同后端策略**校验（≥8 且至少两类字符）。
  3. `POST /cloudchat/auth/password/reset`，Body `{ token, password }`。
  4. 成功提示后引导去登录；失败（token 失效）提供“重新发送邮件”的入口 → `POST /cloudchat/auth/password/forgot`。

### DeepSeek 聊天页

* 发送消息：`POST /cloudchat/deepseek_chat`，读取 **流式**响应（逐行 `JSON.parse`，取 `text` 追加渲染）。
* 重置历史：`POST /cloudchat/reset_chat`。

### 安全与网络

* 前端所有 `fetch` 需设置 `credentials: 'include'`；
* 仅在 HTTPS 下工作（生产）。

---

## 错误码一览

| 代码 | 场景                |
| --- | -------------------- |
| 200 | 成功                 |
| 201 | 注册成功创建           |
| 400 | 参数错误/弱口令/重置 token 失效 |
| 401 | 未认证/登录失败（统一文案） |
| 409 | 冲突（Email/Phone 已存在） |
| 429 | 触发限速（注册）           |
| 503 | 健康检查失败               |
