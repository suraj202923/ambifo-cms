import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
        msg.attach(MIMEText(html_body, "html", "utf-8"))

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
