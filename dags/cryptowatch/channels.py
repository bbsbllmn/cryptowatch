"""Notification channels behind one tiny interface. Adding WhatsApp/Telegram = one class with `send(digest)`,
registered in CHANNELS (see README); the DAG, ledger and formatters are untouched."""
from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Callable, Protocol

from .formatters import Digest, email_html, email_text, slack_payload


class ChannelError(RuntimeError):
    pass


class Channel(Protocol):
    name: str

    def send(self, digest: Digest) -> str: ...


class SlackChannel:
    name = "slack"

    def __init__(self, webhook_url: str, http_post: Callable | None = None, max_alerts: int = 10):
        if not webhook_url.startswith("https://hooks.slack.com/"):
            raise ChannelError("Slack webhook must be an https://hooks.slack.com/ URL")
        if http_post is None:
            import requests
            http_post = requests.post
        self._url, self._post, self.max_alerts = webhook_url, http_post, max_alerts

    def send(self, digest: Digest) -> str:
        r = self._post(self._url, data=json.dumps(slack_payload(digest, self.max_alerts)),
                       headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code != 200:
            raise ChannelError(f"Slack returned HTTP {r.status_code}")          # the body can echo the URL: not logged
        return "ok"


class EmailChannel:
    name = "email"

    def __init__(self, cfg: dict, smtp_factory: Callable | None = None):
        for k in ("host", "port", "user", "password", "from", "to"):
            if k not in cfg:
                raise ChannelError(f"SMTP config is missing '{k}'")
        self.cfg = cfg
        self._smtp = smtp_factory or self._default_smtp

    def _default_smtp(self):
        c = self.cfg
        if int(c["port"]) == 465:
            return smtplib.SMTP_SSL(c["host"], 465, timeout=30)
        s = smtplib.SMTP(c["host"], int(c["port"]), timeout=30)
        s.starttls()
        return s

    def send(self, digest: Digest) -> str:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = digest.subject, self.cfg["from"], ", ".join(self.cfg["to"])
        msg.set_content(email_text(digest))
        msg.add_alternative(email_html(digest), subtype="html")
        try:
            with self._smtp() as s:
                s.login(self.cfg["user"], self.cfg["password"])
                s.send_message(msg)
        except smtplib.SMTPException as exc:
            raise ChannelError(f"SMTP error: {type(exc).__name__}") from None
        return "ok"
