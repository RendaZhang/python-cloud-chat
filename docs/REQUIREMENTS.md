<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [项目需求清单](#%E9%A1%B9%E7%9B%AE%E9%9C%80%E6%B1%82%E6%B8%85%E5%8D%95)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [🚀 核心功能](#-%E6%A0%B8%E5%BF%83%E5%8A%9F%E8%83%BD)
  - [🔧 技术需求](#-%E6%8A%80%E6%9C%AF%E9%9C%80%E6%B1%82)
  - [🌱 未来计划](#-%E6%9C%AA%E6%9D%A5%E8%AE%A1%E5%88%92)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# 项目需求清单

- **负责人**: 张人大（Renda Zhang）
- **最后更新**: July 18, 2025, 17:30 (UTC+8)
- **项目状态**: 稳定运行，持续开发中

---

## 简介

Python Cloud Chat 是一个基于 Flask 的轻量级后端服务，提供 AI 对话和图像生成能力。
项目使用 Gunicorn + Gevent 在小内存服务器上部署，支持多轮对话的会话管理。

---

## 🚀 核心功能

1. **多模型 AI 对话**
   - [x] `/chat` 接口：使用 Qwen 模型进行流式对话
   - [x] `/deepseek_chat` 接口：使用 DeepSeek 模型并保存历史会话至 Redis
   - [x] `/reset_chat` 接口：重置当前会话的历史记录
2. **AI 图像生成**
   - [x] `/generate_image` 接口：基于 Stable Diffusion 生成图片
3. **系统监控与测试**
   - [x] APScheduler 每分钟记录系统和 Redis 内存情况
   - [x] `/test` 接口：返回时间戳和请求 ID 供缓存验证

---

## 🔧 技术需求

- [x] pre-commit 自动执行 doctoc 更新文档目录
- [ ] 完善单元测试并集成到 CI
- [ ] 实现简单的 API 限流和身份验证
- [ ] Docker 化部署与环境配置

---

## 🌱 未来计划

- 支持更多模型及参数自定义
- 提供前端界面与 OAuth 登录
- 自动化监控与告警
