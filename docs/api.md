# API 文档

本文档描述了本服务提供的三个 HTTP 接口的请求与返回格式。

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
curl -X POST localhost:8080/chat \
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

## POST `/deepseek_chat`

- **功能**：使用 DeepSeek Chat 模型进行流式对话。
- **请求头**：`Content-Type: application/json`
- **请求体示例**：

```json
{
  "message": "你好，DeepSeek"
}
```

- **返回**：服务器以分段 JSON 流形式返回回复文本，例如：

```json
{"text": "你好，我是 DeepSeek"}
```

- **调用示例**：

```bash
curl -X POST localhost:8080/deepseek_chat \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"message": "你好，DeepSeek"}'
```

- **预期输出（分段）**：

```json
{"text": "你好"}
{"text": "，我是 DeepSeek"}
```

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
curl -X POST localhost:8080/generate_image \
     -H "Content-Type: application/json" \
     -H "Referer: https://rendazhang.com" \
     -d '{"prompt": "一只在阳光下打盹的橘猫"}'
```

- **预期输出**：

```json
{"image_urls": ["https://dashscope.aliyun.com/..."]}
```
