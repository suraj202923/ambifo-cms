use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::template::AppState;

#[derive(Deserialize)]
pub struct SowSection {
    pub title: String,
    pub body: String,
}

#[derive(Deserialize)]
pub struct DocumentRequest {
    pub company: Option<String>,
    #[allow(dead_code)]
    pub project_name: Option<String>,
    pub sow_title: Option<String>,
    pub sections: Option<Vec<SowSection>>,
}

#[derive(Serialize)]
pub struct DocumentResponse {
    pub filename: String,
    pub content: String,
    pub format: String,
}

pub fn generate_sow_html(req: &DocumentRequest) -> String {
    let title = req.sow_title.clone().unwrap_or_else(|| "Statement of Work".into());
    let company = req.company.clone().unwrap_or_default();
    let sections: &[SowSection] = req.sections.as_deref().unwrap_or(&[]);

    let mut html = String::new();
    html.push_str("<!DOCTYPE html><html><head><meta charset='utf-8'>");
    html.push_str(&format!("<title>{}</title>", escape_html(&title)));
    html.push_str("<style>");
    html.push_str("body{font-family:'Segoe UI',Arial,sans-serif;color:#1f2937;max-width:800px;margin:0 auto;padding:32px 24px;line-height:1.6;}");
    html.push_str("h1{color:#0f2f5f;border-bottom:2px solid #315b92;padding-bottom:8px;}");
    html.push_str("h2{color:#0f4fa8;margin-top:28px;}");
    html.push_str("p{margin:8px 0;}");
    html.push_str(".meta{font-size:13px;color:#64748b;margin-bottom:24px;}");
    html.push_str("</style></head><body>");
    html.push_str(&format!("<h1>{}</h1>", escape_html(&title)));

    if !company.is_empty() {
        html.push_str(&format!("<div class='meta'>Prepared for <strong>{}</strong></div>", escape_html(&company)));
    }

    for section in sections {
        html.push_str(&format!(
            "<h2>{}</h2>\n<p>{}</p>\n",
            escape_html(&section.title),
            escape_html(&section.body)
        ));
    }

    html.push_str("</body></html>");
    html
}

fn escape_html(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

pub async fn generate_handler(
    State(_state): State<Arc<AppState>>,
    Json(req): Json<DocumentRequest>,
) -> Result<Json<DocumentResponse>, (StatusCode, String)> {
    let content = generate_sow_html(&req);
    Ok(Json(DocumentResponse {
        filename: format!("{}.html", req.sow_title.clone().unwrap_or("SOW".into()).replace(' ', "_")),
        content,
        format: "html".into(),
    }))
}