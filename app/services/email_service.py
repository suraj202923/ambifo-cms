import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from email.utils import formatdate

from html import escape
from urllib.parse import urlparse
from itsdangerous import BadSignature, URLSafeSerializer

from flask import has_request_context, request

from app.models import EmailUnsubscribe, SystemSetting


class EmailResult:
    def __init__(self, success, status, error=None):
        self.success = success
        self.status = status
        self.error = error


class EmailService:
    def __init__(self, app):
        self.app = app

    def _get_effective_smtp_settings(self):
        host = SystemSetting.get_value("smtp.host", self.app.config.get("SMTP_HOST"))
        username = SystemSetting.get_value("smtp.username", self.app.config.get("SMTP_USERNAME"))
        password = SystemSetting.get_value("smtp.password", self.app.config.get("SMTP_PASSWORD"))

        port_raw = SystemSetting.get_value("smtp.port", str(self.app.config.get("SMTP_PORT")))
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = int(self.app.config.get("SMTP_PORT"))

        tls_raw = str(SystemSetting.get_value("smtp.use_tls", str(self.app.config.get("SMTP_USE_TLS"))))
        use_tls = tls_raw.lower() in ("true", "1", "yes", "on")

        sender = SystemSetting.get_value("smtp.mail_from", self.app.config.get("MAIL_FROM"))
        return host, username, password, port, use_tls, sender

    def _get_sender_address(self, sender, username):
        # Prefer explicit configured sender; fallback to SMTP username when it looks like an email.
        if sender and "@" in str(sender):
            return str(sender).strip()
        if username and "@" in str(username):
            return str(username).strip()
        return ""

    def _open_smtp_client(self, host, port, use_tls):
        # Common provider pattern: port 465 expects implicit SSL, while 587 uses STARTTLS.
        if use_tls and int(port) == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=60)
            smtp.ehlo()
            return smtp

        smtp = smtplib.SMTP(host, port, timeout=60)
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        return smtp

    def _get_effective_app_base_url(self):
        configured = (SystemSetting.get_value("app.base_url", "") or "").strip()
        if configured:
            return configured.rstrip("/")

        base_url = (self.app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")

        try:
            parsed = urlparse(base_url)
            host = (parsed.hostname or "").lower()
        except Exception:
            host = ""

        # If configured base URL is localhost, prefer the actual incoming host for email links/images.
        if host in {"localhost", "127.0.0.1", "0.0.0.0"} and has_request_context():
            req_host = (request.host or "").lower()
            if req_host and not req_host.startswith("localhost") and not req_host.startswith("127.0.0.1"):
                scheme = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
                return f"{scheme}://{request.host}".rstrip("/")

        return base_url

    def _logo_file_path(self):
        return Path(self.app.root_path).parent / "static" / "ambifologo.png"

    def _unsubscribe_serializer(self):
        secret_key = self.app.config.get("SECRET_KEY") or "ambifo-crm"
        return URLSafeSerializer(secret_key, salt="email-unsubscribe")

    def _build_unsubscribe_token(self, recipient_email):
        normalized = (recipient_email or "").strip().lower()
        if not normalized:
            return ""
        return self._unsubscribe_serializer().dumps({"email": normalized})

    def resolve_unsubscribe_token(self, token):
        if not token:
            return None
        try:
            data = self._unsubscribe_serializer().loads(token)
        except BadSignature:
            return None
        email = (data or {}).get("email")
        if not email:
            return None
        normalized = str(email).strip().lower()
        return normalized if normalized else None

    def _build_unsubscribe_url(self, recipient_email):
        token = self._build_unsubscribe_token(recipient_email)
        if not token:
            return ""
        base_url = self._get_effective_app_base_url()
        return f"{base_url}/email/unsubscribe?token={token}"

    def _is_unsubscribed(self, recipient_email):
        normalized = (recipient_email or "").strip().lower()
        if not normalized:
            return False
        return EmailUnsubscribe.query.filter_by(email=normalized).first() is not None

    def _build_inline_logo_part(self):
        logo_path = self._logo_file_path()
        if not logo_path.exists():
            return None, None

        try:
            logo_bytes = logo_path.read_bytes()
        except OSError:
            return None, None

        logo_cid = "ambifo-logo"
        logo_part = MIMEImage(logo_bytes)
        logo_part.add_header("Content-ID", f"<{logo_cid}>")
        logo_part.add_header("Content-Disposition", "inline", filename="ambifologo.png")
        return logo_part, logo_cid

    def _build_plain_text_fallback(self, html_body):
        body = (html_body or "").strip()
        if not body:
            return "Ambifo CRM email"
        # Keep simple fallback text for clients that prefer plain text.
        return "This email contains HTML content. Please view in an HTML-compatible email client."

    def _wrap_with_ambifo_branding(self, html_body, logo_src=None, recipient_email=None):
        base_url = self._get_effective_app_base_url()
        logo_url = logo_src or f"{base_url}/static/ambifologo.png"
        body_html = html_body or ""
        company_address = "Building No 674, 18th Main, 3rd Phase, Front of New Land ISRO Quarter, Domlur, Bangalore - 560071"
        linkedin_url = "https://www.linkedin.com/company/ambifo-technology"
        unsubscribe_url = self._build_unsubscribe_url(recipient_email)
        unsubscribe_html = (
            f'<div style="margin-top:10px;"><a href="{escape(unsubscribe_url)}" '
            'style="display:inline-block;padding:6px 10px;border:1px solid #d0d7e2;border-radius:6px;'
            'font-size:12px;color:#475569;text-decoration:none;background:#ffffff;">Unsubscribe</a></div>'
            if unsubscribe_url else ""
        )

        return f"""
<div style=\"background:#f5f7fb;padding:18px 12px;\">
    <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"100%\" style=\"max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #e7ecf3;border-radius:10px;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;color:#1f2937;\">
        <tr>
            <td style=\"padding:16px 20px;border-bottom:1px solid #dbe7f6;background:linear-gradient(135deg,#f8fbff 0%,#ecf4ff 100%);text-align:center;\">
                <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"100%\">
                    <tr>
                        <td style=\"vertical-align:middle;text-align:center;\">
                            <img src=\"{escape(logo_url)}\" alt=\"Ambifo\" style=\"height:42px;max-width:220px;display:block;margin:0 auto;\">
                            <div style=\"margin-top:8px;font-size:13px;font-weight:700;color:#0f2f5f;letter-spacing:0.02em;\">AMBIFO TECHNOLOGY PVT LTD</div>
                            <div style=\"margin-top:6px;font-size:11px;color:#315b92;line-height:1.5;\">
                                <span style=\"display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;\">Cloud Strategy</span>
                                <span style=\"display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;\">Migration & Modernization</span>
                                <span style=\"display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;margin-right:6px;\">DevOps</span>
                                <span style=\"display:inline-block;padding:2px 8px;border:1px solid #b9d1f2;border-radius:999px;background:#ffffff;\">AI/ML</span>
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr>
            <td style=\"padding:20px;line-height:1.6;font-size:14px;\">{body_html}</td>
        </tr>
        <tr>
            <td style=\"padding:16px 20px;border-top:1px solid #edf2f7;background:#fbfcfe;font-size:13px;line-height:1.75;color:#1f2937;\">
                <div><strong>Website:</strong> <a href=\"https://www.ambifo.com\" style=\"color:#0f4fa8;text-decoration:none;\">www.ambifo.com</a></div>
                <div><strong>Email:</strong> <a href=\"mailto:support@ambifo.com\" style=\"color:#0f4fa8;text-decoration:none;\">support@ambifo.com</a></div>
                <div><strong>Phone:</strong> +91 9827135213</div>
                <div><strong>Address:</strong> {escape(company_address)}</div>
                <div style=\"margin-top:8px;\">
                    <a href=\"{escape(linkedin_url)}\" target=\"_blank\" rel=\"noopener\" title=\"LinkedIn\" aria-label=\"LinkedIn\" style=\"display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;background:#0a66c2;color:#ffffff;text-decoration:none;font-weight:700;font-size:13px;line-height:1;\">in</a>
                </div>
                {unsubscribe_html}
            </td>
        </tr>
    </table>
</div>
"""

    def send_html_email(self, to_email, subject, html_body, cc_emails=None, bcc_emails=None):
        host, username, password, port, use_tls, sender = self._get_effective_smtp_settings()

        if self._is_unsubscribed(to_email):
            return EmailResult(
                success=False,
                status="unsubscribed",
                error="Recipient has unsubscribed from email communications.",
            )

        if not host:
            return EmailResult(
                success=True,
                status="dev-mode",
                error="SMTP host missing. Email not sent, but request was logged.",
            )

        sender_addr = self._get_sender_address(sender, username)
        if not sender_addr:
            return EmailResult(
                success=False,
                status="failed",
                error="SMTP sender email is missing. Set SMTP Mail From or SMTP Username as a valid email.",
            )

        msg = MIMEMultipart("related")
        alt_part = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_addr
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        cc_list = [e for e in (cc_emails or []) if e]
        bcc_list = [e for e in (bcc_emails or []) if e]
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        logo_part, logo_cid = self._build_inline_logo_part()
        logo_src = f"cid:{logo_cid}" if logo_cid else None
        alt_part.attach(MIMEText(self._build_plain_text_fallback(html_body), "plain", "utf-8"))
        alt_part.attach(MIMEText(self._wrap_with_ambifo_branding(html_body, logo_src=logo_src, recipient_email=to_email), "html", "utf-8"))
        msg.attach(alt_part)
        if logo_part is not None:
            msg.attach(logo_part)

        try:
            with self._open_smtp_client(host, port, use_tls) as smtp:
                if username and password:
                    smtp.login(username, password)
                recipients = [to_email] + cc_list + bcc_list
                smtp.sendmail(sender_addr, recipients, msg.as_string())
            return EmailResult(success=True, status="sent")
        except Exception as exc:
            return EmailResult(success=False, status="failed", error=str(exc))

    def send_html_email_with_attachment(self, to_email, subject, html_body,
                                        attachment_bytes, attachment_filename,
                                        attachment_mime="application/octet-stream"):
        """Send HTML email with a binary file attachment."""
        host, username, password, port, use_tls, sender = self._get_effective_smtp_settings()

        if self._is_unsubscribed(to_email):
            return EmailResult(
                success=False,
                status="unsubscribed",
                error="Recipient has unsubscribed from email communications.",
            )

        if not host:
            return EmailResult(
                success=True,
                status="dev-mode",
                error="SMTP host missing. Email not sent, but request was logged.",
            )

        sender_addr = self._get_sender_address(sender, username)
        if not sender_addr:
            return EmailResult(
                success=False,
                status="failed",
                error="SMTP sender email is missing. Set SMTP Mail From or SMTP Username as a valid email.",
            )

        # mixed(related(alternative(plain, html), inline-logo), attachment)
        msg = MIMEMultipart("mixed")
        related_part = MIMEMultipart("related")
        alt_part = MIMEMultipart("alternative")

        msg["Subject"] = subject
        msg["From"] = sender_addr
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)

        logo_part, logo_cid = self._build_inline_logo_part()
        logo_src = f"cid:{logo_cid}" if logo_cid else None

        alt_part.attach(MIMEText(self._build_plain_text_fallback(html_body), "plain", "utf-8"))
        alt_part.attach(MIMEText(self._wrap_with_ambifo_branding(html_body, logo_src=logo_src, recipient_email=to_email), "html", "utf-8"))
        related_part.attach(alt_part)
        if logo_part is not None:
            related_part.attach(logo_part)
        msg.attach(related_part)

        part = MIMEBase(*attachment_mime.split("/", 1))
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

        try:
            with self._open_smtp_client(host, port, use_tls) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.sendmail(sender_addr, [to_email], msg.as_string())
            return EmailResult(success=True, status="sent")
        except Exception as exc:
            return EmailResult(success=False, status="failed", error=str(exc))
