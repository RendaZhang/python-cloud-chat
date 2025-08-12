import os
import smtplib


def _smtp_config():
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
        "sender_name": os.getenv("MAIL_SENDER_NAME", "CloudChat"),
    }


def send_email(to: str, subject: str, body: str):
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
    subj = "CloudChat 重置密码"
    mins = max(1, ttl_seconds // 60)
    body = (
        "你正在请求重置 CloudChat 密码。\n\n"
        f"重置链接（{mins} 分钟内有效）：\n{reset_link}\n\n"
        "如果你并未发起此请求，请忽略本邮件。"
    )
    send_email(to, subj, body)
