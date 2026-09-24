import re
import smtplib
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from html import escape
from urllib.parse import urlparse

from itsdangerous import BadSignature, URLSafeSerializer

from ..config import settings as app_settings
from ..models.email import EmailUnsubscribe
from .settings import get_app_base_url, get_smtp_settings

COMPANY_ADDRESS = (
    "Building No 674, 18th Main, 3rd Phase, Front of New Land ISRO Quarter, "
    "Domlur, Bangalore - 560071"
)
LINKEDIN_URL = "https://www.linkedin.com/company/ambifo-technology"
WEBSITE_URL = "https://www.ambifo.com"
SUPPORT_EMAIL = "support@ambifo.com"
SUPPORT_PHONE = "+91 9148419502"

_HTML_TAG_RE = re.compile(r"<[a-zA-Z][a-zA-Z0-9]*[^>]*>")


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().strip("<>").lower()


def body_to_html(body: str) -> str:
    """Convert plain-text bodies to HTML; pass HTML through untouched."""
    text = (body or "").strip()
    if not text:
        return ""
    if _HTML_TAG_RE.search(text) and text.lstrip().startswith("<"):
        return text
    paragraphs = re.split(r"\r?\n\s*\r?\n", text)
    parts = []
    for para in paragraphs:
        inline = escape(para).replace("\r\n", "<br/>").replace("\n", "<br/>").replace("\r", "<br/>")
        parts.append(f'<p style="margin:0 0 12px 0;">{inline}</p>')
    return "".join(parts)


def _unsubscribe_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(app_settings.secret_key, salt="email-unsubscribe")


def build_unsubscribe_token(recipient_email: str | None) -> str:
    normalized = _normalize_email(recipient_email)
    if not normalized:
        return ""
    return _unsubscribe_serializer().dumps({"email": normalized})


def resolve_unsubscribe_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _unsubscribe_serializer().loads(token)
    except (BadSignature, TypeError):
        return None
    email = (data or {}).get("email")
    if not email:
        return None
    return _normalize_email(str(email)) or None


def build_unsubscribe_url(db, recipient_email: str | None) -> str:
    token = build_unsubscribe_token(recipient_email)
    if not token:
        return ""
    base_url = get_app_base_url(db)
    return f"{base_url}/api/public/email/unsubscribe?token={token}"


def is_unsubscribed(db, recipient_email: str | None) -> bool:
    normalized = _normalize_email(recipient_email)
    if not normalized:
        return False
    return db.query(EmailUnsubscribe).filter(EmailUnsubscribe.email == normalized).first() is not None


@dataclass
class EmailResult:
    success: bool
    status: str
    error: str | None = None
    detail: dict = field(default_factory=dict)


def _wrap_with_ambifo_branding(db, html_body: str, recipient_email: str | None) -> str:
    base_url = get_app_base_url(db)
    logo_url = f"{base_url}/static/ambifologo.png"
    unsubscribe_url = build_unsubscribe_url(db, recipient_email)
    unsubscribe_html = (
        f'<div style="margin-top:12px;"><a href="{escape(unsubscribe_url)}" '
        'style="display:inline-block;padding:6px 12px;border:1px solid #d0d7e2;border-radius:6px;'
        'font-size:12px;color:#475569;text-decoration:none;background:#ffffff;">Unsubscribe</a></div>'
        if unsubscribe_url
        else ""
    )

    return f"""
<div style="background:#f5f7fb;padding:18px 12px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #e7ecf3;border-radius:10px;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;color:#1f2937;">
        <tr>
            <td style="padding:16px 20px;border-bottom:1px solid #dbe7f6;background:linear-gradient(135deg,#f8fbff 0%,#ecf4ff 100%);text-align:center;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tr>
                        <td style="vertical-align:middle;text-align:center;">
                            <img src="{escape(logo_url)}" alt="Ambifo" style="height:42px;max-width:220px;display:block;margin:0 auto;">
                            <div style="margin-top:8px;font-size:13px;font-weight:700;color:#0f2f5f;letter-spacing:0.02em;">AMBIFO TECHNOLOGY PVT LTD</div>
                            <div style="margin-top:6px;font-size:11px;color:#315b92;line-height:1.5;">
                                <span style="display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;">Cloud Strategy</span>
                                <span style="display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;">Migration &amp; Modernization</span>
                                <span style="display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;">DevOps</span>
                                <span style="display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;">AI/ML</span>
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr>
            <td style="padding:20px;line-height:1.6;font-size:14px;">{body_to_html(html_body)}</td>
        </tr>
        <tr>
            <td style="padding:16px 20px;border-top:1px solid #edf2f7;background:#fbfcfe;font-size:13px;line-height:1.75;color:#1f2937;">
                <div><strong>Website:</strong> <a href="{WEBSITE_URL}" style="color:#0f4fa8;text-decoration:none;">{WEBSITE_URL.replace('https://', '')}</a></div>
                <div><strong>Email:</strong> <a href="mailto:{SUPPORT_EMAIL}" style="color:#0f4fa8;text-decoration:none;">{SUPPORT_EMAIL}</a></div>
                <div><strong>Phone:</strong> {SUPPORT_PHONE}</div>
                <div><strong>Address:</strong> {escape(COMPANY_ADDRESS)}</div>
                <div style="margin-top:8px;">
                    <a href="{escape(LINKEDIN_URL)}" target="_blank" rel="noopener" title="LinkedIn" aria-label="LinkedIn" style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;background:#0a66c2;color:#ffffff;text-decoration:none;font-weight:700;font-size:13px;line-height:1;">in</a>
                </div>
                {unsubscribe_html}
            </td>
        </tr>
    </table>
</div>
"""


def _sender_address(sender: str | None, username: str | None) -> str:
    if sender and "@" in sender:
        return sender.strip()
    if username and "@" in username:
        return username.strip()
    return ""


def _open_smtp_client(host: str, port: int, use_tls: bool) -> smtplib.SMTP:
    if use_tls and port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=60)
        smtp.ehlo()
        return smtp
    smtp = smtplib.SMTP(host, port, timeout=60)
    smtp.ehlo()
    if use_tls:
        smtp.starttls()
        smtp.ehlo()
    return smtp


def send_html_email(
    db,
    to_email: str,
    subject: str,
    html_body: str,
    cc_emails: list[str] | None = None,
    bcc_emails: list[str] | None = None,
) -> EmailResult:
    recipient = to_email or None
    if not _normalize_email(recipient):
        return EmailResult(False, "failed", "Recipient email is empty")

    if is_unsubscribed(db, to_email):
        return EmailResult(False, "unsubscribed", "Recipient has unsubscribed from email communications.")

    smtp = get_smtp_settings(db)
    smtp_host = str(smtp["smtp_host"] or "").strip()
    if not smtp_host:
        return EmailResult(True, "dev-mode", "SMTP host missing. Email not sent, but request was logged.")

    sender_addr = _sender_address(smtp["smtp_mail_from"], smtp["smtp_username"])
    if not sender_addr:
        return EmailResult(
            False, "failed", "SMTP sender email is missing. Set SMTP Mail From or SMTP Username as a valid email."
        )

    cc_list = [_normalize_email(e) for e in (cc_emails or []) if _normalize_email(e) != _normalize_email(to_email) and _normalize_email(e)]
    bcc_list = [_normalize_email(e) for e in (bcc_emails or []) if _normalize_email(e)]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_addr
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.attach(MIMEText("This email contains HTML content. Please view in an HTML-compatible email client.", "plain", "utf-8"))
    msg.attach(MIMEText(_wrap_with_ambifo_branding(db, html_body, to_email), "html", "utf-8"))

    try:
        with _open_smtp_client(smtp_host, int(smtp["smtp_port"]), bool(smtp["smtp_use_tls"])) as smtp_client:
            if smtp["smtp_username"] and smtp["smtp_password"]:
                smtp_client.login(smtp["smtp_username"], smtp["smtp_password"])
            recipients = [to_email] + cc_list + bcc_list
            smtp_client.sendmail(sender_addr, recipients, msg.as_string())
        return EmailResult(True, "sent")
    except Exception as exc:  # noqa: BLE001
        return EmailResult(False, "failed", str(exc))


def effective_base_url_preview(db) -> str:
    current = get_app_base_url(db)
    try:
        parsed = urlparse(current)
        return parsed.hostname or current
    except Exception:  # noqa: BLE001
        return current