import json
import re
from urllib import parse
from urllib import error, request

from app.models import SystemSetting


class AIService:
    def __init__(self, app):
        self.app = app

    def _settings(self):
        active_provider = (
            SystemSetting.get_value("ai.active_provider", None)
            or SystemSetting.get_value("ai.provider", "openai")
            or "openai"
        )
        active_provider = active_provider.strip().lower()
        return {
            "active_provider": active_provider,
            "openai_base_url": (SystemSetting.get_value("ai.openai.base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1").strip(),
            "openai_model": (SystemSetting.get_value("ai.openai.model", "gpt-4o-mini") or "gpt-4o-mini").strip(),
            "openai_api_key": (
                SystemSetting.get_value("ai.openai.api_key", None)
                or SystemSetting.get_value("ai.api_key", "")
                or ""
            ).strip(),
            "gemini_base_url": (SystemSetting.get_value("ai.gemini.base_url", "https://generativelanguage.googleapis.com/v1beta") or "https://generativelanguage.googleapis.com/v1beta").strip(),
            "gemini_model": (SystemSetting.get_value("ai.gemini.model", "gemini-1.5-flash") or "gemini-1.5-flash").strip(),
            "gemini_api_key": (SystemSetting.get_value("ai.gemini.api_key", "") or "").strip(),
        }

    def is_configured(self):
        settings = self._settings()
        if settings["active_provider"] == "gemini":
            return bool(settings.get("gemini_api_key"))
        return bool(settings.get("openai_api_key"))

    def _ambifo_prompt_prefix(self):
        return (
            "You are writing for Ambifo Technology Pvt Ltd. "
            "Ambifo is an AWS and Azure cloud consulting and managed services company, with strengths in "
            "cloud migration, modernization, DevOps, security, data/AI solutions, and enterprise transformation. "
            "Keep content specific, practical, professional, and business-ready for Ambifo client communication."
        )

    def _extract_json_object(self, text):
        if not text:
            return None
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _chat(self, system_prompt, user_prompt, temperature=0.35, max_tokens=1400):
        settings = self._settings()
        provider = settings.get("active_provider", "openai")

        if provider == "gemini":
            return self._chat_gemini(system_prompt, user_prompt, temperature, max_tokens, settings)
        return self._chat_openai(system_prompt, user_prompt, temperature, max_tokens, settings)

    def _chat_openai(self, system_prompt, user_prompt, temperature, max_tokens, settings):
        if not settings.get("openai_api_key"):
            return {"success": False, "error": "OpenAI API key is not configured."}

        endpoint = f"{settings['openai_base_url'].rstrip('/')}/chat/completions"
        payload = {
            "model": settings["openai_model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings['openai_api_key']}",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=80) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            content = (((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if not content:
                return {"success": False, "error": "AI response was empty."}
            return {"success": True, "content": content}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
            return {"success": False, "error": f"OpenAI API error: {detail[:400]}"}
        except Exception as exc:
            return {"success": False, "error": f"AI request failed: {exc}"}

    def _chat_gemini(self, system_prompt, user_prompt, temperature, max_tokens, settings):
        if not settings.get("gemini_api_key"):
            return {"success": False, "error": "Gemini API key is not configured."}

        base = settings["gemini_base_url"].rstrip("/")
        model = parse.quote(settings["gemini_model"], safe="")
        endpoint = f"{base}/models/{model}:generateContent?key={parse.quote(settings['gemini_api_key'])}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt}
                    ]
                }
            ],
            "system_instruction": {
                "parts": [
                    {"text": system_prompt}
                ]
            },
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=80) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            candidates = parsed.get("candidates") or []
            parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts") or [])
            content = "\n".join((part.get("text") or "").strip() for part in parts if (part.get("text") or "").strip())
            if not content:
                return {"success": False, "error": "AI response was empty."}
            return {"success": True, "content": content}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
            return {"success": False, "error": f"Gemini API error: {detail[:400]}"}
        except Exception as exc:
            return {"success": False, "error": f"AI request failed: {exc}"}

    def generate_email_template(self, business_context, objective, tone):
        system_prompt = (
            f"{self._ambifo_prompt_prefix()} "
            "You create B2B email templates for CRM systems. "
            "Return ONLY valid JSON with keys: template_name, subject_template, body_template. "
            "body_template must be compact HTML with <p>, <ul>, <li>, and placeholders like {{customer_name}}."
        )
        user_prompt = (
            f"Objective: {objective or 'Introduce services and request next meeting'}\n"
            f"Tone: {tone or 'professional'}\n"
            f"Context:\n{business_context or 'No context provided'}"
        )
        result = self._chat(system_prompt, user_prompt, temperature=0.45, max_tokens=1200)
        if not result["success"]:
            return result

        payload = self._extract_json_object(result["content"])
        if not payload:
            return {"success": False, "error": "AI output was not valid JSON."}

        return {
            "success": True,
            "template_name": (payload.get("template_name") or "AI Generated Template").strip()[:120],
            "subject_template": (payload.get("subject_template") or "Hello {{customer_name}}").strip()[:255],
            "body_template": (payload.get("body_template") or "<p>Hello {{customer_name}},</p>").strip(),
        }

    def generate_document_content(self, customer_context, objective):
        system_prompt = (
            f"{self._ambifo_prompt_prefix()} "
            "You generate professional Statement of Work / project proposal HTML body content. "
            "Return HTML only (no markdown). Use <h1>, <h2>, <p>, <ul>, <li>. "
            "Do not include <html> or <body> tags."
        )
        user_prompt = (
            f"Objective:\n{objective or 'Create a complete first draft with scope, architecture approach, timeline and risks.'}\n\n"
            f"Customer context:\n{customer_context}"
        )
        result = self._chat(system_prompt, user_prompt, temperature=0.35, max_tokens=2200)
        if not result["success"]:
            return result

        html_content = result["content"].strip()
        return {"success": True, "content_html": html_content}

    def generate_architecture_diagram(self, customer_context, use_case):
        system_prompt = (
            f"{self._ambifo_prompt_prefix()} "
            "You create architecture diagrams for cloud migration/use-case discussions. "
            "Return ONLY valid JSON with keys: diagram_name, macro_key, diagram_content. "
            "diagram_content must be HTML including a Mermaid block like "
            "<pre class='mermaid'>graph TD; A-->B;</pre> plus a short explanatory paragraph."
        )
        user_prompt = (
            f"Use case: {use_case or 'Cloud migration architecture'}\n"
            f"Customer context:\n{customer_context}"
        )
        result = self._chat(system_prompt, user_prompt, temperature=0.3, max_tokens=1500)
        if not result["success"]:
            return result

        payload = self._extract_json_object(result["content"])
        if not payload:
            return {"success": False, "error": "AI output was not valid JSON."}

        macro_key = re.sub(r"[^a-zA-Z0-9_]", "_", (payload.get("macro_key") or "ai_architecture").strip().lower())
        macro_key = re.sub(r"_+", "_", macro_key).strip("_") or "ai_architecture"

        return {
            "success": True,
            "diagram_name": (payload.get("diagram_name") or "AI Architecture Diagram").strip()[:160],
            "macro_key": macro_key,
            "diagram_content": (payload.get("diagram_content") or "<pre class='mermaid'>graph TD; A-->B;</pre>").strip(),
        }
