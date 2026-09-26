use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::sync::Mutex;

use crate::template::AppState;

#[derive(Deserialize, Clone)]
pub struct EmailJob {
    pub to: String,
    pub subject: String,
    #[allow(dead_code)]
    pub body: String,
    #[allow(dead_code)]
    pub smtp_host: Option<String>,
    #[allow(dead_code)]
    pub smtp_port: Option<u16>,
    #[allow(dead_code)]
    pub smtp_username: Option<String>,
    #[allow(dead_code)]
    pub smtp_password: Option<String>,
    #[allow(dead_code)]
    pub from: Option<String>,
}

#[derive(Serialize, Clone)]
pub struct QueueResult {
    pub accepted: u32,
    pub queued: u32,
    pub rejected: u32,
    pub errors: Vec<String>,
}

static QUEUE_COUNT: Mutex<u32> = Mutex::new(0);

pub async fn enqueue_handler(
    State(_state): State<Arc<AppState>>,
    Json(jobs): Json<Vec<EmailJob>>,
) -> Json<QueueResult> {
    let mut count = QUEUE_COUNT.lock().unwrap_or_else(|p| p.into_inner());
    let mut accepted = 0u32;
    let mut rejected = 0u32;
    let mut errors: Vec<String> = Vec::new();

    for job in &jobs {
        if job.to.trim().is_empty() {
            rejected += 1;
            errors.push(format!("rejected: empty recipient for subject '{}'", job.subject));
            continue;
        }
        if job.subject.trim().is_empty() {
            rejected += 1;
            errors.push(format!("rejected: empty subject for recipient '{}'", job.to));
            continue;
        }
        if !job.to.contains('@') {
            rejected += 1;
            errors.push(format!("rejected: invalid email '{}' for subject '{}'", job.to, job.subject));
            continue;
        }
        tracing::info!("email queued -> {} | {}", job.to, job.subject);
        accepted += 1;
    }

    *count += accepted;
    Json(QueueResult { accepted, queued: accepted, rejected, errors })
}