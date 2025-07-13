<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [API 文档](#api-%E6%96%87%E6%A1%A3)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [POST `/chat`](#post-chat)
  - [POST `/generate_image`](#post-generate_image)
  - [POST `/deepseek_chat`](#post-deepseek_chat)
  - [POST `/reset_chat`](#post-reset_chat)
  - [GET `/test`](#get-test)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# API 文档

* **Last Updated:** July 14, 2025, 00:05 (UTC+8)
* **作者:** 张人大（Renda Zhang）

---

## 简介

本文档描述本服务提供的接口请求与返回格式。服务提供以下核心功能：

1. **多模型 AI 对话**
   支持主流大语言模型：
   - **DeepSeek-V3**（深度求索公司开发，128K上下文）
   - GPT-4-turbo（OpenAI）
   - Claude 3 Opus（Anthropic）

2. **图像生成**
   支持 DALL·E 3 和阿里通义万相图像生成模型

3. **技术特性**
   - 所有对话接口支持**流式输出**
   - 多轮对话状态管理（默认保留最近6轮）
   - 全接口强制验证 `Referer` 头（仅允许 `rendazhang.com` 域名）
   - 响应内容动态缓存控制

> 重要安全要求：所有接口必须携带 `Referer: https://www.rendazhang.com` 请求头

---

## POST `/chat`

- **功能**：与 AI 模型进行流式对话。

- **请求头**：`Content-Type: application/json`，`Referer: https://www.rendazhang.com`。

- **请求体示例**：

```json
{
  "message": "你好，请介绍一下自己"
}
```

- **返回**：服务器以分段 JSON 流形式返回回复文本。

- **调用示例**：

```bash
curl -X POST https://www.rendazhang.com/cloudchat/chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"message": "Hello from curl!"}'
```

- **返回示例**：

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

## POST `/generate_image`

- **功能**：根据提示词生成图像。

- **请求头**：`Content-Type: application/json`，`Referer: https://www.rendazhang.com`。

- **请求体示例**：

```json
{
  "prompt": "一只在阳光下打盹的橘猫"
}
```

- **返回**：生成的图像地址列表。

- **调用示例**：

```bash
curl -X POST https://www.rendazhang.com/cloudchat/generate_image \
     -H "Content-Type: application/json" \
     -H "Referer: https://www.rendazhang.com" \
     -d '{"prompt": "一只在阳光下打盹的橘猫"}'
```

- **返回示例**：

```json
{"image_urls": ["https://dashscope.aliyun.com/..."]}
```

---

## POST `/deepseek_chat`

- **功能**：使用 DeepSeek Chat 模型进行多轮流式对话，历史消息存储在 Redis 中。

- **请求头**：`Content-Type: application/json`，`Referer: https://www.rendazhang.com`。

- **请求体示例**：

```json
{
  "message": "你好，DeepSeek"
}
```

- **返回**：服务器以分段 JSON 流形式连续返回回复文本。

- **调用示例**：

```bash
curl -X POST https://www.rendazhang.com/cloudchat/deepseek_chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://www.rendazhang.com" \
     -d '{"message": "你好，DeepSeek，这是测试，请简单地用几个英文单词回答我"}'
```

- **返回示例**：

```json
{"text": "Hi"}
{"text": "!"}
{"text": " R"}
{"text": "enda"}
{"text": " Zhang"}
{"text": " here"}
{"text": "."}
{"text": " Test"}
{"text": " received"}
{"text": "."}
{"text": " All"}
{"text": " good"}
{"text": "!"}
```

- **说明**：会话默认保留最近 6 轮对话，如需清空历史可调用 [`/reset_chat`](#post-reset_chat)。

---

## POST `/reset_chat`

- **功能**：清空当前用户会话中的对话历史。

- **请求头**：`Content-Type: application/json`，`Referer: https://www.rendazhang.com`。

- **请求体示例**：空对象即可。

- **返回**：提示成功 Reset。

- **调用示例**：

```bash
curl -X POST https://www.rendazhang.com/cloudchat/reset_chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://www.rendazhang.com" \
     -d '{}'
```

- **返回示例**：

```json
{"status": "Reset chat history successfully"}
```

---

## GET `/test`

- **功能**：返回动态时间戳和随机 ID，用于测试 Nginx 缓存及 `X-Cache-Status` 头。

- **请求头**：`Referer: https://www.rendazhang.com`。

- **返回**：如果成功会返回 timestamp 和 request_id 信息。

- **调用示例**：

```bash
curl https://www.rendazhang.com/cloudchat/test -H "Referer: https://www.rendazhang.com"
```

- **返回示例**：

```json
{
  "timestamp": 1752421640.8777363,
  "request_id": "d8fc46ba-5279-4fba-8bb0-54a1ceb94ba2"
}
```

- **说明**：如果通过 Nginx 访问并启用 `proxy_cache`，重复请求应在响应头看到 `X-Cache-Status: HIT`。
