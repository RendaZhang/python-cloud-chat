<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [API 文档](#api-%E6%96%87%E6%A1%A3)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [POST `/chat`](#post-chat)
  - [POST `/generate_image`](#post-generate_image)
  - [POST `/reset_chat`](#post-reset_chat)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# API 文档

* **Last Updated:** July 8, 2025, 21:40 (UTC+8)
* **作者:** 张人大（Renda Zhang）

---

## 简介

本文档描述了本服务提供的接口的请求与返回格式。

---

## POST `/chat`

- **功能**：与 AI 模型进行流式对话。
- **请求头**：`Content-Type: application/json`
- **请求体示例**：

```json
{
  "message": "你好，请介绍一下自己"
}
```

- **返回**：服务器以分段 JSON 流形式返回回复文本，例如：

```json
{"text": "你好，我是..."}
```

- **调用示例**：

```bash
curl -X POST localhost:5000/chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"message": "Hello from curl!"}'
```

- **预期输出（分段）**：

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

- **功能**：使用 DeepSeek Chat 模型进行多轮流式对话，历史消息存储在 Redis 中。
- **注意**：调用前请按 README 中的步骤安装并配置 Redis。
- **请求头**：`Content-Type: application/json`
- **请求体示例**：

```json
{
  "message": "你好，DeepSeek"
}
```

- **返回**：服务器以分段 JSON 流形式连续返回回复文本：

```json
{"text": "你好"}
{"text": "，我是 DeepSeek"}
```

- **调用示例**：

```bash
curl -X POST localhost:5000/deepseek_chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"message": "你好，DeepSeek"}'
```

- **说明**：会话默认保留最近 6 轮对话，如需清空历史可调用 [`/reset_chat`](#post-reset_chat)。

---

## POST `/generate_image`

- **功能**：根据提示词生成图像。
- **请求头**：`Content-Type: application/json`
- **请求体示例**：

```json
{
  "prompt": "一只在阳光下打盹的橘猫"
}
```

- **返回**：生成的图像地址列表。

```json
{
  "image_urls": ["https://dashscope.aliyun.com/..."]
}
```

- **调用示例**：

```bash
curl -X POST localhost:5000/generate_image \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"prompt": "一只在阳光下打盹的橘猫"}'
```

- **预期输出**：

```json
{"image_urls": ["https://dashscope.aliyun.com/..."]}
```

---

## POST `/reset_chat`

- **功能**：清空当前用户会话中的对话历史。
- **请求头**：`Content-Type: application/json`
- **请求体示例**：空对象即可。

```json
{}
```

- **返回示例**：

```json
{"status": "对话历史已重置"}
```
