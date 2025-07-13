<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Python 轻量级后端开发指南](#python-%E8%BD%BB%E9%87%8F%E7%BA%A7%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [轻量级会话存储方案（针对小内存服务器）](#%E8%BD%BB%E9%87%8F%E7%BA%A7%E4%BC%9A%E8%AF%9D%E5%AD%98%E5%82%A8%E6%96%B9%E6%A1%88%E9%92%88%E5%AF%B9%E5%B0%8F%E5%86%85%E5%AD%98%E6%9C%8D%E5%8A%A1%E5%99%A8)
    - [方案 A: 文件系统存储（最简单，零依赖）](#%E6%96%B9%E6%A1%88-a-%E6%96%87%E4%BB%B6%E7%B3%BB%E7%BB%9F%E5%AD%98%E5%82%A8%E6%9C%80%E7%AE%80%E5%8D%95%E9%9B%B6%E4%BE%9D%E8%B5%96)
    - [方案 B: Redis 存储（更高效，但需要额外服务）](#%E6%96%B9%E6%A1%88-b-redis-%E5%AD%98%E5%82%A8%E6%9B%B4%E9%AB%98%E6%95%88%E4%BD%86%E9%9C%80%E8%A6%81%E9%A2%9D%E5%A4%96%E6%9C%8D%E5%8A%A1)
    - [方案 C: SQLite 数据库（轻量级数据库）](#%E6%96%B9%E6%A1%88-c-sqlite-%E6%95%B0%E6%8D%AE%E5%BA%93%E8%BD%BB%E9%87%8F%E7%BA%A7%E6%95%B0%E6%8D%AE%E5%BA%93)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Python 轻量级后端开发指南

* **Last Updated:** July 14, 2025, 00:30 (UTC+8)
* **作者:** 张人大（Renda Zhang）

---

## 简介

本文档旨在为 Python 轻量级后端开发提供全面的指南，涵盖会话存储、数据库优化、API 设计、缓存策略等多个方面。通过模块化的结构，开发者可以根据需求灵活查阅相关内容。

---

## 轻量级会话存储方案（针对小内存服务器）

### 方案 A: 文件系统存储（最简单，零依赖）


需要定期清理旧会话，否则会话文件会随着时间的推移不断积累，占用大量磁盘空间。

清理策略：

- 基于时间的清理：使用文件的修改时间（mtime）来判断文件是否过期。
- 基于数量的清理：按文件修改时间排序，保留最新的 N 个文件。
- 混合策略：先删除过期的文件，再保留最近的 N 个文件。

使用文件系统存储：

```python
from flask import Flask
from flask_session import Session

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default-secret-key')

# 文件系统会话存储配置
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'  # 使用临时目录
app.config['SESSION_FILE_THRESHOLD'] = 100  # 限制最大会话数量
app.config['SESSION_PERMANENT'] = False  # 浏览器关闭时过期

# 初始化会话扩展
Session(app)
```

创建会话目录：

```bash
# 存储在 /tmp 目录：
mkdir -p /tmp/flask_sessions
```

限制对话历史长度：

```python
# 在添加消息前检查历史长度
MAX_HISTORY = 5  # 只保留最近5轮对话

if len(session['messages']) > MAX_HISTORY * 2 + 1:  # 系统消息 + 5轮对话
    # 保留系统消息和最近的对话
    session['messages'] = [session['messages'][0]] + session['messages'][-MAX_HISTORY*2:]
```

如果用户量增长，可以考虑升级服务器或迁移到 Redis 会话存储。

### 方案 B: Redis 存储（更高效，但需要额外服务）

Redis 是基于内存的存储系统，如果会话数据不断积累，可能导致内存耗尽。

清理策略：

- 基于时间的清理：为每个会话设置过期时间（TTL），Redis 会自动删除过期的键。
- 基于数量的清理：使用 Redis 的 LPUSH 和 LTRIM 命令来维护一个固定长度的列表。
- 混合策略：先删除过期的会话，再保留最近的 N 个会话。

虽然 Redis 是高性能选择，但考虑到服务器内存有限，如果使用 Redis，具体操作步骤可以参考 Nginx 项目的文档内容：[安装并配置 Redis](https://github.com/RendaZhang/nginx-conf/blob/master/docs/MIGRATION_GUIDE.md#%E5%AE%89%E8%A3%85%E5%B9%B6%E9%85%8D%E7%BD%AE-redis)

### 方案 C: SQLite 数据库（轻量级数据库）

会话数据不断积累会占用磁盘空间，并且 数据量过大会影响 SQLite 的查询性能。

清理策略：

- 基于时间的清理：使用 SQL 查询删除过期的会话记录。
- 基于数量的清理：使用 SQL 查询删除超出数量的旧会话记录。
- 混合策略：先删除过期的会话，再保留最近的 N 个会话。

使用 SQLite 数据库：

```python
import sqlite3
from flask_session import Session

app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = 'sqlite:////tmp/sessions.db'
app.config['SESSION_SQLALCHEMY_TABLE'] = 'sessions'

Session(app)
```

限制对话历史长度：

```python
import sqlite3

MAX_HISTORY = 5  # 只保留最近5轮对话

# 连接到 SQLite 数据库
conn = sqlite3.connect('sessions.db')
cursor = conn.cursor()

# 假设会话消息存储在 messages 表中
session_id = 123

# 删除超过历史长度的旧记录
cursor.execute('''
    DELETE FROM messages
    WHERE session_id = ?
    AND id NOT IN (
        SELECT id FROM messages
        WHERE session_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    )
''', (session_id, session_id, MAX_HISTORY * 2 + 1))

conn.commit()
conn.close()
```
