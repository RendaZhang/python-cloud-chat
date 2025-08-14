"""Utility helpers for sending transactional emails.

This module exposes lightweight wrappers around ``smtplib`` to deliver
plain‑text emails for various account related events.
"""

import os
import smtplib


def _smtp_config():
    """Load SMTP configuration from environment variables.

    Returns a dictionary containing connection parameters and defaults. A
    ``RuntimeError`` is raised if the host is missing so callers immediately
    notice misconfiguration during startup.
    """

    host = os.getenv("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP not configured (SMTP_HOST missing)")
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASS", ""),
        "use_tls": os.getenv("SMTP_TLS", "1") == "1",
        "from_addr": os.getenv("MAIL_FROM", os.getenv("SMTP_USER", "")),
        "sender_name": os.getenv("MAIL_SENDER_NAME", "RendaZhang"),
    }


def send_email(to: str, subject: str, body: str):
    """Send a plain - text email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Message body in UTF‑8.
    """

    cfg = _smtp_config()
    msg = (
        f"From: {cfg['sender_name']} <{cfg['from_addr']}>\r\n"
        f"To: <{to}>\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n" + body
    )
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as s:
        if cfg["use_tls"]:
            s.starttls()
        if cfg["user"]:
            s.login(cfg["user"], cfg["password"])
        s.sendmail(cfg["from_addr"], [to], msg.encode("utf-8"))


def send_reset_email(to: str, token: str, reset_link: str, ttl_seconds: int):
    """Send a password reset link to the user.

    Args:
        to: Recipient email address.
        token: Raw reset token for logging or debugging.
        reset_link: Fully qualified URL the user should visit to reset password.
        ttl_seconds: Token validity duration in seconds; used in the email body
            to inform the user of expiry time.
    """

    subj = "RendaZhang 网站 - 重置密码"
    mins = max(1, ttl_seconds // 60)
    body = (
        "你正在请求重置 RendaZhang 网站的密码。\n\n"
        f"重置链接（{mins} 分钟内有效）：\n{reset_link}\n\n"
        "如果你并未发起此请求，请忽略本邮件。"
    )
    send_email(to, subj, body)


def send_register_success_email(to: str):
    """Notify a user that registration succeeded."""

    subj = "RendaZhang 网站 - 注册成功"
    body = "你已成功注册 RendaZhang 网站。\n\n" "如果这不是你本人操作，请尽快联系我们。"
    send_email(to, subj, body)


def send_reset_success_email(to: str):
    """Confirm that the user's password has been reset."""

    subj = "RendaZhang 网站 - 密码重置成功"
    body = "你的密码已成功重置。\n\n" "如果这不是你本人操作，请尽快联系我们。"
    send_email(to, subj, body)
