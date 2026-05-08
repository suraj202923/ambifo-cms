"""DocuSign eSignature integration service.

Flow summary (JWT Grant):
  1. Ambifo generates your document as HTML → converts to PDF bytes.
  2. We call DocuSign API: upload PDF + signer name/email → DocuSign creates an envelope.
  3. DocuSign sends the signing email to your customer automatically (you don't send it).
  4. Customer clicks the link in their email and signs in the browser (no DocuSign account needed).
  5. DocuSign notifies us via webhook when signed (status = completed).
  6. We download the completed signed PDF and store it.
"""

import base64
import json
import time
import urllib.error
import urllib.request


class DocuSignResult:
    def __init__(self, success, envelope_id=None, error=None):
        self.success = success
        self.envelope_id = envelope_id
        self.error = error


class DocuSignService:
    """Lightweight DocuSign REST API client using JWT impersonation grant.

    Does NOT depend on the docusign-esign SDK — uses plain urllib so there
    are no extra install requirements beyond the standard library.
    """

    _token_cache = {}   # { account_id: { "access_token": str, "expires_at": float } }
    _base_uri_cache = {}  # { account_id: "https://na4.docusign.net" }

    def __init__(self, app):
        self.app = app

    # ── Settings helpers ───────────────────────────────────────────────

    def _cfg(self, key, fallback=""):
        """Read DocuSign setting from SystemSetting DB first, then app config."""
        from app.models import SystemSetting
        return (SystemSetting.get_value(f"docusign.{key}", self.app.config.get(f"DOCUSIGN_{key.upper().replace('.', '_')}", fallback)) or "").strip()

    def _is_configured(self):
        return bool(self._cfg("integration_key") and self._cfg("account_id") and self._cfg("user_id"))

    # ── Token acquisition (JWT) ────────────────────────────────────────

    def _get_access_token(self):
        """Obtain (or return cached) DocuSign JWT access token.

        Uses the RSA private key stored in the 'docusign.private_key' setting
        (PEM text).  Falls back to the DOCUSIGN_PRIVATE_KEY environment variable.
        """
        account_id = self._cfg("account_id")
        cached = self._token_cache.get(account_id)
        if cached and cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]

        integration_key = self._cfg("integration_key")
        user_id = self._cfg("user_id")
        base_url = self._cfg("base_url", "https://account-d.docusign.com")
        private_key_pem = self._cfg("private_key")

        if not private_key_pem:
            raise RuntimeError("DocuSign private key is not configured.")

        try:
            import jwt as pyjwt
        except ImportError:
            raise RuntimeError(
                "PyJWT is required for DocuSign JWT auth. Add 'PyJWT>=2.8.0 cryptography>=41.0' to requirements.txt."
            )

        now = int(time.time())
        payload = {
            "iss": integration_key,
            "sub": user_id,
            "aud": base_url.replace("https://", "").split("/")[0],
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        }

        jwt_token = pyjwt.encode(payload, private_key_pem, algorithm="RS256")

        token_url = f"{base_url.rstrip('/')}/oauth/token"
        data = f"grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion={jwt_token}".encode()
        req = urllib.request.Request(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise RuntimeError(f"DocuSign token request failed ({exc.code}): {detail}") from exc

        access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        self._token_cache[account_id] = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }
        return access_token

    # ── Core API helpers ────────────────────────────────────────────────

    def _get_rest_base_uri(self, token=None):
        account_id = self._cfg("account_id")
        cached = self._base_uri_cache.get(account_id)
        if cached:
            return cached

        token = token or self._get_access_token()
        auth_base = self._cfg("base_url", "https://account-d.docusign.com").rstrip("/")
        req = urllib.request.Request(
            f"{auth_base}/oauth/userinfo",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise RuntimeError(f"DocuSign userinfo request failed ({exc.code}): {detail}") from exc

        accounts = body.get("accounts") or []
        target = next((a for a in accounts if str(a.get("account_id")) == str(account_id)), None)
        if not target and accounts:
            target = next((a for a in accounts if a.get("is_default")), None) or accounts[0]

        if not target:
            raise RuntimeError("No DocuSign account found for this user.")

        base_uri = (target.get("base_uri") or "").strip()
        if not base_uri:
            raise RuntimeError("DocuSign userinfo did not return base_uri.")
        self._base_uri_cache[account_id] = base_uri
        return base_uri

    def _api_base(self, token=None):
        account_id = self._cfg("account_id")
        rest_base_uri = self._get_rest_base_uri(token=token)
        return f"{rest_base_uri.rstrip('/')}/restapi/v2.1/accounts/{account_id}"

    def _json_request(self, method, path, payload=None, token=None):
        token = token or self._get_access_token()
        url = self._api_base(token=token) + path
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise RuntimeError(f"DocuSign API {method} {path} failed ({exc.code}): {detail}") from exc

    # ── Public API ──────────────────────────────────────────────────────

    def send_envelope(self, pdf_bytes, document_name, signer_name, signer_email, email_subject=None, email_body=None):
        """Upload a PDF and send it to the signer via DocuSign.

        DocuSign emails the signer automatically — you do not need to send
        any email from Ambifo yourself.

        Returns DocuSignResult with envelope_id on success.
        """
        if not self._is_configured():
            return DocuSignResult(success=False, error="DocuSign is not configured. Please add credentials in Configuration → DocuSign.")

        try:
            token = self._get_access_token()
            doc_b64 = base64.b64encode(pdf_bytes).decode()
            subject = email_subject or f"Please sign: {document_name}"
            message = email_body or (
                "Please review and sign the attached document at your earliest convenience."
            )

            envelope_payload = {
                "emailSubject": subject,
                "emailBlurb": message,
                "documents": [
                    {
                        "documentBase64": doc_b64,
                        "name": document_name,
                        "fileExtension": "pdf",
                        "documentId": "1",
                    }
                ],
                "recipients": {
                    "signers": [
                        {
                            "email": signer_email,
                            "name": signer_name,
                            "recipientId": "1",
                            "routingOrder": "1",
                            "tabs": {
                                # DocuSign will ask the signer to place their own signature
                                # (signHereTabs = auto-place at end of doc).
                                "signHereTabs": [
                                    {
                                        "documentId": "1",
                                        "pageNumber": "1",
                                        "xPosition": "100",
                                        "yPosition": "700",
                                        "anchorIgnoreIfNotPresent": "true",
                                    }
                                ]
                            },
                        }
                    ]
                },
                "status": "sent",
            }

            result = self._json_request("POST", "/envelopes", envelope_payload, token=token)
            envelope_id = result.get("envelopeId")
            return DocuSignResult(success=True, envelope_id=envelope_id)

        except Exception as exc:
            return DocuSignResult(success=False, error=str(exc))

    def get_envelope_status(self, envelope_id):
        """Return current DocuSign status string for an envelope."""
        try:
            result = self._json_request("GET", f"/envelopes/{envelope_id}")
            return result.get("status", "unknown")
        except Exception as exc:
            return f"error: {exc}"

    def void_envelope(self, envelope_id, reason="Voided by sender"):
        """Void (cancel) an envelope that has not yet been completed."""
        try:
            self._json_request(
                "PUT",
                f"/envelopes/{envelope_id}",
                {"status": "voided", "voidedReason": reason},
            )
            return True, None
        except Exception as exc:
            return False, str(exc)

    def download_signed_document(self, envelope_id):
        """Download the combined signed PDF bytes for a completed envelope."""
        token = self._get_access_token()
        url = self._api_base(token=token) + f"/envelopes/{envelope_id}/documents/combined"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/pdf",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise RuntimeError(f"Download signed doc failed ({exc.code}): {detail}") from exc
