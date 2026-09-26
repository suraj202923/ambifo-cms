use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::template::AppState;

#[derive(Deserialize)]
pub struct CsvImportRequest {
    pub content: String,
    pub contains_header: Option<bool>,
}

#[derive(Serialize)]
pub struct CsvImportResponse {
    pub headers: Vec<String>,
    pub rows: Vec<Vec<String>>,
    pub row_count: usize,
}

pub fn parse_csv(content: &str, has_header: bool) -> CsvImportResponse {
    let mut rdr = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(content.as_bytes());
    let headers: Vec<String> = rdr
        .headers()
        .map(|h| h.iter().map(|s| s.to_string()).collect())
        .unwrap_or_default();
    let mut rows = Vec::new();
    for record in rdr.records() {
        if let Ok(rec) = record {
            rows.push(rec.iter().map(|s| s.to_string()).collect());
        }
    }
    let (final_headers, final_rows) = if has_header {
        (headers.clone(), rows)
    } else {
        (Vec::new(), {
            let mut all = Vec::with_capacity(rows.len() + 1);
            if !headers.is_empty() {
                all.push(headers);
            }
            all.extend(rows);
            all
        })
    };
    let row_count = final_rows.len();
    CsvImportResponse { headers: final_headers, rows: final_rows, row_count }
}

pub async fn csv_handler(
    State(_state): State<Arc<AppState>>,
    Json(req): Json<CsvImportRequest>,
) -> Json<CsvImportResponse> {
    Json(parse_csv(&req.content, req.contains_header.unwrap_or(true)))
}