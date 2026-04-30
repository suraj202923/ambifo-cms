import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from html import escape

from app.models import SystemSetting


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

    def _get_effective_app_base_url(self):
        configured = (SystemSetting.get_value("app.base_url", "") or "").strip()
        if configured:
            return configured.rstrip("/")
        return (self.app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")

    def _wrap_with_ambifo_branding(self, html_body):
        base_url = self._get_effective_app_base_url()
        logo_url = f"{base_url}/static/ambifologo.png"
        body_html = html_body or ""
        company_address = "Building No 674, 18th Main, 3rd Phase, Front of New Land ISRO Quarter, Domlur, Bangalore - 560071"
        linkedin_url = "https://www.linkedin.com/company/ambifo-technology"

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
                <div><strong>Phone:</strong> +91 9148419502</div>
                <div><strong>Address:</strong> {escape(company_address)}</div>
                <div style=\"margin-top:8px;\">
                    <a href=\"{escape(linkedin_url)}\" target=\"_blank\" rel=\"noopener\" title=\"LinkedIn\" aria-label=\"LinkedIn\" style=\"display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;background:#0a66c2;color:#ffffff;text-decoration:none;font-weight:700;font-size:13px;line-height:1;\">in</a>
                </div>
            </td>
        </tr>
    </table>
</div>
"""

    def send_html_email(self, to_email, subject, html_body, cc_emails=None, bcc_emails=None):
        host, username, password, port, use_tls, sender = self._get_effective_smtp_settings()

        if not host:
            return EmailResult(
                success=True,
                status="dev-mode",
                error="SMTP host missing. Email not sent, but request was logged.",
            )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        cc_list = [e for e in (cc_emails or []) if e]
        bcc_list = [e for e in (bcc_emails or []) if e]
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg.attach(MIMEText(self._wrap_with_ambifo_branding(html_body), "html", "utf-8"))

        try:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if username and password:
                    smtp.login(username, password)
                recipients = [to_email] + cc_list + bcc_list
                smtp.sendmail(sender, recipients, msg.as_string())
            return EmailResult(success=True, status="sent")
        except Exception as exc:
            return EmailResult(success=False, status="failed", error=str(exc))

    def send_html_email_with_attachment(self, to_email, subject, html_body,
                                        attachment_bytes, attachment_filename,
                                        attachment_mime="application/octet-stream"):
        """Send HTML email with a binary file attachment."""
        host, username, password, port, use_tls, sender = self._get_effective_smtp_settings()

        if not host:
            return EmailResult(
                success=True,
                status="dev-mode",
                error="SMTP host missing. Email not sent, but request was logged.",
            )

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.attach(MIMEText(self._wrap_with_ambifo_branding(html_body), "html", "utf-8"))

        part = MIMEBase(*attachment_mime.split("/", 1))
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

        try:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if username and password:
                    smtp.login(username, password)
                smtp.sendmail(sender, [to_email], msg.as_string())
            return EmailResult(success=True, status="sent")
        except Exception as exc:
            return EmailResult(success=False, status="failed", error=str(exc))
