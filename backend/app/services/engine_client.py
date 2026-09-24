from fastapi import HTTPException, status

import httpx

from ..config import settings


class EngineClient:
    """HTTP bridge to the Rust engine (heavy compute service)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.engine_url

    def health(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=3.0)
            return resp.status_code == 200 and resp.text.strip() == "ok"
        except httpx.HTTPError:
            return False

    def render_template(self, template: str, context: dict) -> str:
        resp = httpx.post(
            f"{self.base_url}/api/template/render",
            json={"template": template, "context": context},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["rendered"]

    def parse_csv(self, content: str, contains_header: bool = True) -> dict:
        resp = httpx.post(
            f"{self.base_url}/api/import/csv",
            json={"content": content, "contains_header": contains_header},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()

    def generate_sow(self, payload: dict) -> dict:
        resp = httpx.post(
            f"{self.base_url}/api/docs/generate",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()

    def generate_diagram(self, payload: dict) -> dict:
        resp = httpx.post(
            f"{self.base_url}/api/diagrams/generate",
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def enqueue_emails(self, jobs: list[dict]) -> dict:
        resp = httpx.post(
            f"{self.base_url}/api/email/queue",
            json=jobs,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def ai_generate(
        self, provider: str, prompt: str, api_key: str, model: str | None = None
    ) -> str:
        resp = httpx.post(
            f"{self.base_url}/api/ai/generate",
            json={
                "provider": provider,
                "prompt": prompt,
                "api_key": api_key,
                "model": model,
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()["content"]


engine_client = EngineClient()