from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user
from ..models.user import User
from ..schemas.engine import AiGenerateIn, AiGenerateOut
from ..services.engine_client import engine_client

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/generate", response_model=AiGenerateOut)
def ai_generate(
    payload: AiGenerateIn,
    _user: User = Depends(get_current_user),
):
    """Proxy to the Rust engine's AI orchestrator (OpenAI or Gemini)."""
    try:
        content = engine_client.ai_generate(
            provider=payload.provider,
            prompt=payload.prompt,
            api_key=payload.api_key,
            model=payload.model,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Engine AI generation failed: {exc}") from exc
    return AiGenerateOut(content=content)