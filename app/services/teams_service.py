import json
from datetime import datetime, timedelta, timezone
from urllib import error, parse, request

from app.models import SystemSetting


class TeamsMeetingResult:
    def __init__(self, success, join_url=None, start_utc=None, end_utc=None, error_message=None):
        self.success = success
        self.join_url = join_url
        self.start_utc = start_utc
        self.end_utc = end_utc
        self.error_message = error_message


class TeamsService:
    def __init__(self, app):
        self.app = app

    def _settings(self):
        def _setting(key, fallback):
            return str(SystemSetting.get_value(key, fallback) or "").strip()

        return {
            "tenant_id": _setting("teams.tenant_id", self.app.config.get("TEAMS_TENANT_ID")),
            "client_id": _setting("teams.client_id", self.app.config.get("TEAMS_CLIENT_ID")),
            "client_secret": _setting("teams.client_secret", self.app.config.get("TEAMS_CLIENT_SECRET")),
            "organizer_id": _setting("teams.organizer_id", self.app.config.get("TEAMS_ORGANIZER_ID")),
            "duration_minutes": int(_setting("teams.default_duration_minutes", self.app.config.get("TEAMS_DEFAULT_DURATION_MINUTES") or 60) or 60),
        }

    def is_configured(self):
        cfg = self._settings()
        return all([cfg["tenant_id"], cfg["client_id"], cfg["client_secret"], cfg["organizer_id"]])

    def _to_utc_iso(self, dt_value):
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        else:
            dt_value = dt_value.astimezone(timezone.utc)
        return dt_value.isoformat().replace("+00:00", "Z")

    def _get_access_token(self, tenant_id, client_id, client_secret):
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload = parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }
        ).encode("utf-8")
        req = request.Request(token_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("access_token")

    def create_online_meeting(self, subject, start_at=None):
        cfg = self._settings()
        if not self.is_configured():
            return TeamsMeetingResult(
                success=False,
                error_message="Teams settings are incomplete. Configure tenant, client, secret, and organizer.",
            )

        if start_at is None:
            start_at = datetime.utcnow() + timedelta(hours=1)
        end_at = start_at + timedelta(minutes=max(15, cfg["duration_minutes"]))

        start_iso = self._to_utc_iso(start_at)
        end_iso = self._to_utc_iso(end_at)

        try:
            token = self._get_access_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])
            if not token:
                return TeamsMeetingResult(success=False, error_message="Unable to get Microsoft Graph token.")

            organizer = parse.quote(cfg["organizer_id"], safe="")
            meeting_url = f"https://graph.microsoft.com/v1.0/users/{organizer}/onlineMeetings"
            body = json.dumps(
                {
                    "subject": subject,
                    "startDateTime": start_iso,
                    "endDateTime": end_iso,
                }
            ).encode("utf-8")

            req = request.Request(meeting_url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")

            with request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            join_url = payload.get("joinWebUrl")
            if not join_url:
                return TeamsMeetingResult(success=False, error_message="Teams response missing joinWebUrl.")

            return TeamsMeetingResult(
                success=True,
                join_url=join_url,
                start_utc=start_iso,
                end_utc=end_iso,
            )
        except error.HTTPError as exc:
            err_text = exc.read().decode("utf-8", errors="ignore")
            return TeamsMeetingResult(success=False, error_message=f"Graph API error: {exc.code} {err_text}")
        except Exception as exc:
            return TeamsMeetingResult(success=False, error_message=str(exc))