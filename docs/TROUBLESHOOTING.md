<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [后端 BUG 跟踪数据库](#%E5%90%8E%E7%AB%AF-bug-%E8%B7%9F%E8%B8%AA%E6%95%B0%E6%8D%AE%E5%BA%93)
  - [文档说明](#%E6%96%87%E6%A1%A3%E8%AF%B4%E6%98%8E)
    - [BUG 记录模板](#bug-%E8%AE%B0%E5%BD%95%E6%A8%A1%E6%9D%BF)
  - [BUG 详情](#bug-%E8%AF%A6%E6%83%85)
    - [BUG-001: 用户登录接口抛出 DetachedInstanceError](#bug-001-%E7%94%A8%E6%88%B7%E7%99%BB%E5%BD%95%E6%8E%A5%E5%8F%A3%E6%8A%9B%E5%87%BA-detachedinstanceerror)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# 后端 BUG 跟踪数据库

- **作者**: 张人大 (Renda Zhang)
- **最后更新**: August 12, 2025, 23:20 (UTC+08:00)

---

## 文档说明

本文档用于跟踪后端服务的 BUG，包括问题描述、根本原因、解决方案及修复状态。

1. **目的**：建立可追溯的 BUG 知识库，避免重复问题
2. **更新流程**：
   - 新 BUG 发现后 24 小时内记录
   - 解决后更新状态和解决方案
3. **严重等级**：
   - ⚠️ 紧急（阻塞核心功能）
   - ⚠️ 高（影响用户体验）
   - ⚠️ 中（非核心功能问题）
   - ⚠️ 低（视觉/文案问题）

### BUG 记录模板

统一的记录格式便于后续检索和统计，可以参考如下的模版：
```markdown
### BUG-<编号>: <标题>

- **问题状态**：新建 (New) | 已确认 (Confirmed) | 进行中 (In Progress) | 已解决 (Resolved) | 已验证 (Verified) | 重新打开 (Reopened) | 已关闭 (Closed) | 已拒绝 (Rejected) | 已延期 (Deferred) | 已阻塞 (Blocked) | 已取消 (Cancelled)
- **发现日期**：YYYY-MM-DD
- **重现环境**：XXX
- **问题现象**：
  - 描述 1
  - 描述 2
- **根本原因**：
  - 原因 1
- **解决方案**：
  - 步骤 1
- **验证结果**：XXX
- **经验总结**：可选的额外说明
```

---

## BUG 详情

### BUG-001: 用户登录接口抛出 DetachedInstanceError

- **问题状态**：已关闭 (Closed)
- **发现日期**：2025-08-12
- **重现环境**：
  - Ubuntu 服务器本地（`localhost:5000`）
  - Windows 电脑通过域名（`https://www.rendazhang.com/cloudchat`）
- **问题现象**：
  - 用户通过 `/auth/login` 接口登录时返回 **500 Internal Server Error**。
  - 服务器日志显示 `DetachedInstanceError` 错误，提示 `User` 对象未绑定到数据库会话。
- **根本原因**：
  - SQLAlchemy 的 `Session` 上下文管理器在 `with get_session() as s:` 块结束后自动关闭。
  - 在会话关闭后访问 `user.id`，导致 SQLAlchemy 尝试刷新对象属性时失败。
- **解决方案**：
  - 在会话生命周期内提前提取 `user.id` 并存储为独立变量：
    ```python
    with get_session() as s:
        user = q.first()
        if not user or not user.is_active:
            return jsonify({"ok": False, "error": "Invalid credentials"}), 401
        user_id = user.id  # 提前提取 user.id
    sid = _issue_session(user_id)  # 会话关闭后使用 user_id
    ```
- **验证结果**：
  - 重启 `cloudchat` 服务后，通过 `curl` 和浏览器测试 `/auth/login` 接口，均返回 200 状态码且无错误日志。
  - `journalctl` 日志确认无 `DetachedInstanceError` 报错。
- **经验总结**：
  - SQLAlchemy 的会话管理需严格遵守上下文生命周期，避免在会话关闭后访问模型对象的属性。
  - 对于关键字段（如 `id`），应在会话内提前提取并缓存，防止延迟加载引发异常。
