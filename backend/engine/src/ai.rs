use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::template::AppState;

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AiProvider {
    Openai,
    Gemini,
}

#[derive(Deserialize)]
pub struct AiGenerateRequest {
    pub provider: AiProvider,
    pub prompt: String,
    pub api_key: String,
    pub model: Option<String>,
    pub max_tokens: Option<u32>,
}

#[derive(Serialize)]
pub struct AiGenerateResponse {
    pub content: String,
}

pub async fn generate_handler(
    State(_state): State<Arc<AppState>>,
    Json(req): Json<AiGenerateRequest>,
) -> Result<Json<AiGenerateResponse>, (StatusCode, String)> {
    let content = match req.provider {
        AiProvider::Openai => call_openai(&req).await?,
        AiProvider::Gemini => call_gemini(&req).await?,
    };
    Ok(Json(AiGenerateResponse { content }))
}

async fn call_openai(req: &AiGenerateRequest) -> Result<String, (StatusCode, String)> {
    let model = req.model.clone().unwrap_or_else(|| "gpt-4o-mini".into());
    let body = serde_json::json!({
        "model": model,
        "messages": [{"role": "user", "content": req.prompt}],
        "max_tokens": req.max_tokens.unwrap_or(1000),
    });
    let client = reqwest::Client::new();
    let resp = client
        .post("https://api.openai.com/v1/chat/completions")
        .bearer_auth(&req.api_key)
        .json(&body)
        .send()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("openai call failed: {e}")))?;
    let status = resp.status();
    let json: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("openai parse failed: {e}")))?;
    if !status.is_success() {
        return Err((StatusCode::BAD_GATEWAY, format!("openai error {status}: {json}")));
    }
    let content = json["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string();
    Ok(content)
}

async fn call_gemini(req: &AiGenerateRequest) -> Result<String, (StatusCode, String)> {
    let model = req.model.clone().unwrap_or_else(|| "gemini-1.5-flash".into());
    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={}",
        req.api_key
    );
    let body = serde_json::json!({
        "contents": [{"parts": [{"text": req.prompt}]}],
    });
    let client = reqwest::Client::new();
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("gemini call failed: {e}")))?;
    let status = resp.status();
    let json: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("gemini parse failed: {e}")))?;
    if !status.is_success() {
        return Err((StatusCode::BAD_GATEWAY, format!("gemini error {status}: {json}")));
    }
    let content = json["candidates"][0]["content"]["parts"][0]["text"]
        .as_str()
        .unwrap_or("")
        .to_string();
    Ok(content)
}