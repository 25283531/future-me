"""Outgoing email (stdlib smtplib only) for verification / reset codes.

SMTP settings live in the admin settings table (host, port, TLS/SSL,
username, password, from address) — never in env vars, never in logs.
When SMTP is not configured, registration and login still work; only
the verification/reset emails cannot be sent (the admin console shows
the SMTP status clearly).

Default provider (user decision 2026-11-20): 阿里企业邮箱 —
smtp.qiye.aliyun.com:465 with implicit SSL. Aliyun enterprise mail
does NOT offer port 587 / STARTTLS.
"""
import smtplib
from email.message import EmailMessage

from . import database

APP_NAME = "未来我"


def smtp_configured() -> bool:
    """True when a verification email can actually be sent."""
    return bool(database.get_setting("smtp.host", "").strip()) and bool(
        database.get_setting("smtp.from_address", "").strip()
    )


def smtp_status() -> dict:
    """What the admin console shows (password never leaves the server)."""
    return {
        "configured": smtp_configured(),
        "host": database.get_setting("smtp.host", ""),
        "port": database.get_setting("smtp.port", "587"),
        "security": database.get_setting("smtp.security", "tls"),
        "username": database.get_setting("smtp.username", ""),
        "from_address": database.get_setting("smtp.from_address", ""),
        "password_set": bool(database.get_setting("smtp.password", "")),
    }


def send_email(to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns False on any failure
    (misconfiguration, network, auth) — the caller degrades gracefully.
    The SMTP password is never logged."""
    host = database.get_setting("smtp.host", "").strip()
    from_address = database.get_setting("smtp.from_address", "").strip()
    if not host or not from_address:
        return False
    try:
        port = int(database.get_setting("smtp.port", "587") or "587")
    except ValueError:
        return False
    security = database.get_setting("smtp.security", "tls").strip().lower()
    username = database.get_setting("smtp.username", "").strip()
    password = database.get_setting("smtp.password", "")

    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    server = None
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if security == "tls":
                server.starttls()
        if username:
            server.login(username, password)
        server.send_message(msg)
        return True
    except Exception:
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


def send_verification_email(to: str, code: str) -> bool:
    return send_email(
        to,
        f"【{APP_NAME}】邮箱验证码",
        f"你好，你正在验证「{APP_NAME}」的邮箱。\n\n"
        f"验证码：{code}\n\n"
        f"验证码 10 分钟内有效，请勿告诉他人。\n"
        f"如果你没有注册「{APP_NAME}」，请忽略这封邮件。\n",
    )


def send_reset_email(to: str, code: str) -> bool:
    return send_email(
        to,
        f"【{APP_NAME}】重置密码验证码",
        f"你好，你正在重置「{APP_NAME}」的密码。\n\n"
        f"验证码：{code}\n\n"
        f"验证码 10 分钟内有效，请勿告诉他人。\n"
        f"如果你没有申请重置密码，请忽略这封邮件，你的密码不会被改动。\n",
    )


def send_test_email(to: str) -> tuple[bool, str]:
    """Admin test-send: returns (ok, detail). Detail never contains the
    SMTP password."""
    if not smtp_configured():
        return False, "SMTP 未配置：请先在后台填写发件服务器和发件人地址"
    if send_email(
        to,
        f"【{APP_NAME}】后台测试邮件",
        f"这是一封来自「{APP_NAME}」后台的测试邮件。\n\n"
        "如果你收到这封邮件，说明邮件配置可以正常发信，"
        "用户注册验证和密码找回的邮件也能正常发送。\n",
    ):
        return True, "测试邮件已发送"
    return False, "发送失败：请检查服务器地址、端口、加密方式、账号密码是否正确"
