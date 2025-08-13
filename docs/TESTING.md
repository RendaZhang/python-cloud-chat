<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [CloudChat 后端测试手册](#cloudchat-%E5%90%8E%E7%AB%AF%E6%B5%8B%E8%AF%95%E6%89%8B%E5%86%8C)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [速览](#%E9%80%9F%E8%A7%88)
  - [前置条件](#%E5%89%8D%E7%BD%AE%E6%9D%A1%E4%BB%B6)
  - [业务与接口矩阵](#%E4%B8%9A%E5%8A%A1%E4%B8%8E%E6%8E%A5%E5%8F%A3%E7%9F%A9%E9%98%B5)
  - [测试用例总表（可作为 Checklist）](#%E6%B5%8B%E8%AF%95%E7%94%A8%E4%BE%8B%E6%80%BB%E8%A1%A8%E5%8F%AF%E4%BD%9C%E4%B8%BA-checklist)
    - [认证主流程](#%E8%AE%A4%E8%AF%81%E4%B8%BB%E6%B5%81%E7%A8%8B)
    - [密码找回（Debug/生产双形态）](#%E5%AF%86%E7%A0%81%E6%89%BE%E5%9B%9Edebug%E7%94%9F%E4%BA%A7%E5%8F%8C%E5%BD%A2%E6%80%81)
    - [速率限制](#%E9%80%9F%E7%8E%87%E9%99%90%E5%88%B6)
    - [健康检查/观测](#%E5%81%A5%E5%BA%B7%E6%A3%80%E6%9F%A5%E8%A7%82%E6%B5%8B)
    - [聊天接口（流式）](#%E8%81%8A%E5%A4%A9%E6%8E%A5%E5%8F%A3%E6%B5%81%E5%BC%8F)
  - [分场景脚本（可直接执行）](#%E5%88%86%E5%9C%BA%E6%99%AF%E8%84%9A%E6%9C%AC%E5%8F%AF%E7%9B%B4%E6%8E%A5%E6%89%A7%E8%A1%8C)
    - [注册（A1）](#%E6%B3%A8%E5%86%8Ca1)
    - [登录/登出/我是谁（A2/A3/A4）](#%E7%99%BB%E5%BD%95%E7%99%BB%E5%87%BA%E6%88%91%E6%98%AF%E8%B0%81a2a3a4)
    - [忘记/重置密码（A5/A6）](#%E5%BF%98%E8%AE%B0%E9%87%8D%E7%BD%AE%E5%AF%86%E7%A0%81a5a6)
      - [Debug 模式（`DEBUG_RETURN_RESET_TOKEN=1`）](#debug-%E6%A8%A1%E5%BC%8Fdebug_return_reset_token1)
      - [生产模式（`DEBUG_RETURN_RESET_TOKEN=0`）](#%E7%94%9F%E4%BA%A7%E6%A8%A1%E5%BC%8Fdebug_return_reset_token0)
    - [健康检查（A7）](#%E5%81%A5%E5%BA%B7%E6%A3%80%E6%9F%A5a7)
    - [聊天接口（C1/C2/C3）](#%E8%81%8A%E5%A4%A9%E6%8E%A5%E5%8F%A3c1c2c3)
  - [速率限制与边界用例](#%E9%80%9F%E7%8E%87%E9%99%90%E5%88%B6%E4%B8%8E%E8%BE%B9%E7%95%8C%E7%94%A8%E4%BE%8B)
  - [观测与排障](#%E8%A7%82%E6%B5%8B%E4%B8%8E%E6%8E%92%E9%9A%9C)
  - [数据清理（测试环境）](#%E6%95%B0%E6%8D%AE%E6%B8%85%E7%90%86%E6%B5%8B%E8%AF%95%E7%8E%AF%E5%A2%83)
  - [扩展方式（新增接口时怎么补用例）](#%E6%89%A9%E5%B1%95%E6%96%B9%E5%BC%8F%E6%96%B0%E5%A2%9E%E6%8E%A5%E5%8F%A3%E6%97%B6%E6%80%8E%E4%B9%88%E8%A1%A5%E7%94%A8%E4%BE%8B)
    - [用例模板（Markdown）](#%E7%94%A8%E4%BE%8B%E6%A8%A1%E6%9D%BFmarkdown)
    - [分层建议](#%E5%88%86%E5%B1%82%E5%BB%BA%E8%AE%AE)
  - [验收标准（通过/不通过）](#%E9%AA%8C%E6%94%B6%E6%A0%87%E5%87%86%E9%80%9A%E8%BF%87%E4%B8%8D%E9%80%9A%E8%BF%87)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# CloudChat 后端测试手册

- **作者**: 张人大 (Renda Zhang)
- **最后更新**: August 13, 2025, 18:20 (UTC+08:00)

---

## 简介

**目的**：为测试/前端/运维提供一份可复制、可扩展的端到端测试指南，覆盖当前全部已实现接口（认证、密码找回、健康检查、聊天流式接口），并可按模板新增更多用例。

---

## 速览

* **对外 Base URL**：`https://www.rendazhang.com/cloudchat`
* **认证 Cookie**：`cc_auth`（登录成功由后端设置）
* **应用会话 Cookie**：`cc_app`（用于聊天历史）
* **重要开关**（写入 `/etc/cloudchat/cloudchat.env`）：

  * `DEBUG_RETURN_RESET_TOKEN=1|0`（Debug/生产）
  * `PWRESET_TOKEN_TTL=900`（单位秒）
  * `FRONTEND_BASE_URL=https://www.rendazhang.com`

> 切换开关后：`sudo systemctl restart cloudchat`

---

## 前置条件

```bash
# 健康检查：依赖（Redis + PostgreSQL）在线
curl -s https://www.rendazhang.com/cloudchat/auth/healthz
# 期望：{"ok":true,"redis":true,"db":true}
```

* DirectMail 已配置（生产模式需能正常收邮件）。
* 本机/CI 可使用 `curl+jq`、或 Postman/Bruno/Insomnia 导入本文命令。

---

## 业务与接口矩阵

| 编号 | 模块    | 接口                      | 方法   | 典型返回                                              | 认证        | 备注                     |
| -- | ----- | ----------------------- | ---- | ------------------------------------------------- | --------- | ---------------------- |
| A1 | 注册    | `/auth/register`        | POST | 201 `{ok:true}`/ 409/400/429                      | 否         | Email 唯一、密码强度校验、注册限速   |
| A2 | 登录    | `/auth/login`           | POST | 200 `{ok:true}` + `Set-Cookie: cc_auth=...` / 401 | 否         | 失败统一文案、防枚举、登录限速        |
| A3 | 登出    | `/auth/logout`          | POST | 200 `{ok:true}`                                   | `cc_auth` | 幂等、清空 Cookie           |
| A4 | 我是谁   | `/auth/me`              | GET  | 200 `{ok:true,user:{...}}` / 401                  | `cc_auth` | 用户基本信息                 |
| A5 | 忘记密码  | `/auth/password/forgot` | POST | 200 `{ok:true}`（Debug 额外附 `debug_token`）     | 否         | 发邮件/返回 token；忘记密码限速    |
| A6 | 重置密码  | `/auth/password/reset`  | POST | 200 `{ok:true,revoked_sessions:n}` / 400          | 否         | 一次性 token、强制下线旧会话      |
| A7 | 健康检查  | `/auth/healthz`         | GET  | 200 或 503                                         | 否         | 探测 Redis + PostgreSQL  |
| C1 | 聊天（流） | `/deepseek_chat`        | POST | `chunked` JSON 行                                  | 可选        | 依赖 `cc_app` 维护历史；非必须登录 |
| C2 | 重置聊天  | `/reset_chat`           | POST | 200 `{status:"..."}`                              | 可选        | 清空聊天历史                 |
| C3 | 缓存测试  | `/test`                 | GET  | 200 `{timestamp, request_id}`                     | 否         | 配合 Nginx/X‑Cache       |

> 全部对外路径需加 `/cloudchat` 前缀。

---

## 测试用例总表（可作为 Checklist）

### 认证主流程

* [ ] **注册**：新邮箱 → 201；重复 → 409；弱口令 → 400；超配额 → 429
* [ ] **登录**：正确凭证 → 200 且设置 `cc_auth`；错误 → 401（统一文案）
* [ ] **/me**：带 `cc_auth` → 200；不带/失效 → 401
* [ ] **登出**：无论是否登录 → 200，Cookie 置空

### 密码找回（Debug/生产双形态）

* [ ] Debug：`forgot` 返回 `debug_token`；`reset` 第一次 200、第二次 400；旧会话 401、旧密码 401、新密码 200
* [ ] 生产：`forgot` 始终 200；收到邮件链接 `/reset_password?token=...`；使用 token 成功 200；过期/非法 token 400

### 速率限制

* [ ] 注册：IP ≥ 11 次/小时 → 429；单 email ≥ 4 次/小时 → 429
* [ ] 登录：同 IP 或同 identifier 连续 ≥ 11 次/10 分钟 → 401（统一文案）
* [ ] 忘记密码：IP ≥ 21 次/小时 → **仍 200**；identifier ≥ 6 次/小时 → **仍 200**

### 健康检查/观测

* [ ] `/auth/healthz` 为 200；故意停 Redis/DB → 503

### 聊天接口（流式）

* [ ] `/deepseek_chat` 返回**逐行 JSON**；历史截断在 `MAX_HISTORY`；`/reset_chat` 可清空

---

## 分场景脚本（可直接执行）

> 以下命令默认在 **本机开发**（`http://localhost:5000`）与**线上**（`https://www.rendazhang.com/cloudchat`）都可执行；把前缀换一下即可。

### 注册（A1）

```bash
# 成功（201）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"P@ssw0rd!","display_name":"Alice"}'

# 重复（409）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"P@ssw0rd!"}'

# 弱口令（400）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"weak@example.com","password":"abcd1234"}'
```

### 登录/登出/我是谁（A2/A3/A4）

```bash
# 登录成功 → 保存 Cookie
authcookies='-c auth.txt'
curl -i $authcookies -X POST https://www.rendazhang.com/cloudchat/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"alice@example.com","password":"P@ssw0rd!"}'

# 我是谁（200）
curl -i -b auth.txt https://www.rendazhang.com/cloudchat/auth/me

# 登出（200 且清空 Cookie）
curl -i -b auth.txt -X POST https://www.rendazhang.com/cloudchat/auth/logout

# 失效后访问 /me（401）
curl -i -b auth.txt https://www.rendazhang.com/cloudchat/auth/me
```

### 忘记/重置密码（A5/A6）

#### Debug 模式（`DEBUG_RETURN_RESET_TOKEN=1`）

```bash
# 申请重置（返回 debug_token）
resp=$(curl -s -X POST https://www.rendazhang.com/cloudchat/auth/password/forgot \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"alice@example.com"}')
TOKEN=$(python - <<'PY' ;import sys,json;print(json.load(sys.stdin).get('debug_token','')); PY)

echo "TOKEN=$TOKEN"

# 用 token 重置（200）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/password/reset \
  -H 'Content-Type: application/json' \
  -d '{"token":"'"$TOKEN"'","password":"NewP@ssw0rd43!"}'

# 重放同一 token（400）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/password/reset \
  -H 'Content-Type: application/json' \
  -d '{"token":"'"$TOKEN"'","password":"Whatever123!"}'
```

#### 生产模式（`DEBUG_RETURN_RESET_TOKEN=0`）

```bash
# 申请重置（始终 200；收邮件）
curl -s -X POST https://www.rendazhang.com/cloudchat/auth/password/forgot \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"alice@example.com"}'
# 邮件链接示例： https://www.rendazhang.com/reset_password?token=...

# 手动把邮件中的 token 粘到命令里：
TOKEN='<PASTE_FROM_EMAIL>'

# 用 token 重置（200）
curl -i -X POST https://www.rendazhang.com/cloudchat/auth/password/reset \
  -H 'Content-Type: application/json' \
  -d '{"token":"'"$TOKEN"'","password":"NewP@ssw0rd43!"}'
```

### 健康检查（A7）

```bash
curl -i https://www.rendazhang.com/cloudchat/auth/healthz
# 200: {"ok":true,"redis":true,"db":true}
# 503: 任一 false
```

### 聊天接口（C1/C2/C3）

```bash
# 发送一条并流式读取（建议加 --no-buffer）
curl --no-buffer -s -X POST https://www.rendazhang.com/cloudchat/deepseek_chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请简短回答。"}' | jq -Rc 'fromjson? | .text // empty'

# 重置聊天历史
curl -s -X POST https://www.rendazhang.com/cloudchat/reset_chat
```

---

## 速率限制与边界用例

> 速率限制依赖 `X-Forwarded-For`；如需模拟不同来源 IP，可自定义该头部。

```bash
# 注册超配额（期望 429）
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H 'X-Forwarded-For: 10.0.0.1' \
    -X POST https://www.rendazhang.com/cloudchat/auth/register \
    -H 'Content-Type: application/json' \
    -d '{"email":"u'$i'@example.com","password":"P@ssw0rd!"}';
done
```

更多边界：

* 登录：错误 11 次/10 分钟，HTTP 仍为 401（与普通失败一致，防枚举）。
* 忘记密码：高频触发仍 200；但应观察服务端日志是否出现限流记录。
* 密码强度：`abcd1234` 应被拒（400）。

---

## 观测与排障

```bash
# 后端日志
journalctl -u cloudchat -e --no-pager

# PgBouncer（若异常连接）
sudo systemctl status pgbouncer --no-pager
sudo tail -f /var/log/postgresql/pgbouncer.log

# Redis（调试 token/会话，生产谨慎）
redis-cli -a $REDIS_PASSWORD KEYS 'pwreset:*'
redis-cli -a $REDIS_PASSWORD TTL 'pwreset:<token>'
redis-cli -a $REDIS_PASSWORD KEYS 'sess:*' | wc -l
```

---

## 数据清理（测试环境）

```sql
-- psql 连接后执行：按邮箱清理用户及其会话/凭据
DELETE FROM sessions   WHERE user_id IN (SELECT id FROM users WHERE email='alice@example.com');
DELETE FROM credentials WHERE user_id IN (SELECT id FROM users WHERE email='alice@example.com');
DELETE FROM users       WHERE email='alice@example.com';
```

清理速率限制键：

```bash
# 慎用，仅测试环境
redis-cli -a $REDIS_PASSWORD KEYS 'rl:*' | xargs -r redis-cli -a $REDIS_PASSWORD DEL
```

---

## 扩展方式（新增接口时怎么补用例）

### 用例模板（Markdown）

```md
### <模块名> - <接口名>（<方法>）
**路径**：/cloudchat/<path>
**前置**：<需要的账号/状态>
**请求**：curl ...
**期望**：
- HTTP <code>
- Body: { ok:true, ... }
- Cookie/头：<可选>
**异常**：<常见 4xx/5xx>
```

### 分层建议

* **单元**：直接调用函数/模块（例如密码校验函数、邮件发送包装），断言返回值或异常。
* **集成**：在本机 `localhost:5000` 以 curl 跑通依赖（Redis/DB 可本地）。
* **端到端**：生产域名 + Nginx + DirectMail；对照本文脚本执行。

---

## 验收标准（通过/不通过）

* 认证：A1–A4 全通过；错误路径返回码准确，错误文案遵循统一策略。
* 密码找回：Debug/生产两形态均通过；token 一次性；旧会话全部失效；弱口令拒绝。
* 聊天：流式输出逐行 JSON；历史条数受限；可重置历史。
* 健康：`/auth/healthz` 200；任一依赖异常返回 503。
* 安全：全程 HTTPS；响应头含 `Cache-Control: no-store` 等；日志无明文 token/密码。
