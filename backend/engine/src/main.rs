use axum::{routing::{get, post}, Router};
use tower_http::cors::CorsLayer;
use tracing_subscriber::EnvFilter;

mod ai;
mod docs;
mod email_queue;
mod parsers;
mod template;
mod diagrams;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| "info".into()))
        .init();

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/template/render", post(template::render_handler))
        .route("/api/email/queue", post(email_queue::enqueue_handler))
        .route("/api/ai/generate", post(ai::generate_handler))
        .route("/api/import/csv", post(parsers::csv_handler))
        .route("/api/docs/generate", post(docs::generate_handler))
        .route("/api/diagrams/generate", post(diagrams::generate_handler))
        .layer(CorsLayer::permissive())
        .with_state(std::sync::Arc::new(template::AppState));

    let port = std::env::var("ENGINE_PORT").unwrap_or_else(|_| "8081".into());
    // Loopback only. The engine has no authentication and CORS is permissive,
    // and /api/ai/generate spends the configured OpenAI/Gemini key, so it must
    // not be reachable from outside the host. The API reaches it server-side
    // over ENGINE_URL, so nothing else needs a wider bind.
    let addr = format!("127.0.0.1:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("bind failed");
    tracing::info!("ambifo_engine listening on {addr}");
    axum::serve(listener, app).await.expect("server error");
}

async fn health() -> &'static str {
    "ok"
}