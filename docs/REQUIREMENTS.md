<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [项目需求清单](#%E9%A1%B9%E7%9B%AE%E9%9C%80%E6%B1%82%E6%B8%85%E5%8D%95)
  - [简介](#%E7%AE%80%E4%BB%8B)
  - [实现的功能](#%E5%AE%9E%E7%8E%B0%E7%9A%84%E5%8A%9F%E8%83%BD)
  - [待完成需求](#%E5%BE%85%E5%AE%8C%E6%88%90%E9%9C%80%E6%B1%82)
  - [🌱 未来计划](#-%E6%9C%AA%E6%9D%A5%E8%AE%A1%E5%88%92)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# 项目需求清单

- **作者**: 张人大 (Renda Zhang)
- **最后更新**: August 14, 2025,01:20 (UTC+08:00)

---

## 简介

Python Cloud Chat 是一个基于 Flask 的轻量级后端服务，提供用户认证、AI 对话和图像生成能力。
项目使用 Gunicorn + Gevent 在小内存服务器上部署，支持多轮对话和用户会话管理。

---

## 实现的功能

1. **用户认证与注册**
   - [x] `/auth/register`：邮箱必填、手机号可选，按 IP 和邮箱限速
   - [x] `/auth/login`、`/auth/logout`、`/auth/me`
   - [x] `/auth/password/forgot` 与 `/auth/password/reset` 完成密码重置
   - [x] 数据库层面强制 `email` 非空唯一，`phone` 可空
   - [x] 实现简单的 API 限流和身份验证
   - [x] 环境变量启用真实邮件发送
   - [x] 为发信域配置 SPF/DKIM/DMARC
   - [x] 投递验证：向多个不同域的收件箱测试
   - [x] 安全复核：生产保持 `COOKIE_SECURE=1`、HSTS 开启
   - [x] 密码重置后强制终止当前会话

2. **多模型 AI 对话**
   - [x] `/chat` 接口：使用 Qwen 模型进行流式对话
   - [x] `/deepseek_chat` 接口：使用 DeepSeek 模型并保存历史会话至 Redis
   - [x] `/reset_chat` 接口：重置当前会话的历史记录
   - [x] 聊天接口添加登录认证保护

3. **AI 图像生成**
   - [x] `/generate_image` 接口：基于 Stable Diffusion 生成图片

4. **系统监控与测试**
   - [x] 仅主进程执行资源监控任务
   - [x] `/test` 接口：返回时间戳和请求 ID 供缓存验证
   - [x] pre-commit 自动执行 doctoc 更新文档目录
   - [x] 邮件发送失败日志记录

---

## 待完成需求

- [ ] 优化会话吊销：实现 `user_sess:<uid>` 反向索引
- [ ] 完善单元测试并集成到 CI
- [ ] Docker 化部署与环境配置
- [ ] 增加 JWT 签名验证密码重置 token
- [ ] 敏感操作(密码修改)前要求重新认证
- [ ] 添加请求 ID 用于链路追踪

---

## 🌱 未来计划

- 支持更多模型及参数自定义
- 提供前端界面与 OAuth 登录
- 自动化监控与告警
- 完善邮箱验证与多因素认证
- 实现用户会话的定期清理 cronjob
