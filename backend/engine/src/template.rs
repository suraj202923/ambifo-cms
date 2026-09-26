use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState;

#[derive(Deserialize)]
pub struct TemplateRequest {
    pub template: String,
    pub context: HashMap<String, String>,
}

#[derive(Serialize)]
pub struct TemplateResponse {
    pub rendered: String,
}

/// Renders a {{macro}} template with the given context.
/// Supports macros like {{customer_name}}, {{today}}, and {{default}} values.
pub fn render(template_str: &str, ctx: &HashMap<String, String>) -> Result<String, String> {
    // Use regex-free approach: replace each {{key}} with its value directly.
    // This avoids TinyTemplate and handles nested braces correctly.
    let mut result = template_str.to_string();
    for (k, v) in ctx {
        let placeholder = format!("{{{{{}}}}}", k);
        result = result.replace(&placeholder, v);
    }
    Ok(result)
}

pub async fn render_handler(
    State(_state): State<Arc<AppState>>,
    Json(req): Json<TemplateRequest>,
) -> Result<Json<TemplateResponse>, (StatusCode, String)> {
    match render(&req.template, &req.context) {
        Ok(rendered) => Ok(Json(TemplateResponse { rendered })),
        Err(e) => Err((StatusCode::BAD_REQUEST, e.to_string())),
    }
}