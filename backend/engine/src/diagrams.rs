use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::template::AppState;

#[derive(Deserialize)]
pub struct DiagramRequest {
    pub title: Option<String>,
    pub entities: Option<Vec<String>>,
    pub ai_generated: Option<String>,
}

#[derive(Serialize)]
pub struct DiagramResponse {
    pub mermaid: String,
}

/// Builds a Mermaid flowchart from a list of entities (e.g. infrastructure
/// components). Falls back to the AI-generated definition if provided.
pub fn build_mermaid(req: &DiagramRequest) -> String {
    if let Some(ai) = &req.ai_generated {
        return ai.clone();
    }
    let title = req.title.clone().unwrap_or_else(|| "Architecture".into());
    let entities = req.entities.clone().unwrap_or_default();
    if entities.is_empty() {
        return format!("flowchart LR\n    A[{}]\n", title);
    }

    let mut out = String::from("flowchart LR\n");
    let node_id = |i: usize| -> char { (b'A' + i as u8) as char };

    // Title node → first entity
    out.push_str(&format!(
        "    {}[{}] --> {}[{}]\n",
        node_id(0),
        title,
        node_id(1),
        label(&entities[0])
    ));

    // Chain remaining entities linearly
    for (i, e) in entities.iter().enumerate().skip(1) {
        out.push_str(&format!(
            "    {}[{}] --> {}[{}]\n",
            node_id(i),
            label(&entities[i - 1]),
            node_id(i + 1),
            label(e)
        ));
    }
    out
}

fn label(s: &str) -> String {
    if s.is_empty() { "root".to_string() } else { s.to_string() }
}

pub async fn generate_handler(
    State(_state): State<Arc<AppState>>,
    Json(req): Json<DiagramRequest>,
) -> Json<DiagramResponse> {
    Json(DiagramResponse { mermaid: build_mermaid(&req) })
}