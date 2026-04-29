# Ambifo CRM (Flask + PostgreSQL)

Lightweight CRM starter built for your requirements:

- Customer list page and add customer form
- Import customers from `Master Tracker(Sheet1).csv`
- Email template creation with macros
- Send email by selecting customer + template
- Send gathering request email with form link
- Customer-facing gathering form with optional sheet upload
- PostgreSQL backend

## Tech Choice

- **Language:** Python
- **Framework:** Flask (lightweight, fast to build)
- **Database:** PostgreSQL
- **Email:** SMTP (`smtplib`)

This stack is lightweight, easy to host, and simpler than heavier frameworks for your current CRM scope.

## 1) Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` from `.env.example` and update values.

You can also configure the app using `appsettings.json`.
Priority order is: environment variable > appsettings.json > code default.

## 2) PostgreSQL

Create DB user and DB with password authentication:

```sql
CREATE USER crm_app WITH PASSWORD 'StrongPassword';
CREATE DATABASE ambifo_crm;
GRANT ALL PRIVILEGES ON DATABASE ambifo_crm TO crm_app;
```

Set authentication values in .env using one approach:

Option A (single URL):

DATABASE_URL=postgresql+psycopg2://crm_app:StrongPassword@localhost:5432/ambifo_crm?sslmode=prefer

Option B (split values):

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ambifo_crm
POSTGRES_USER=crm_app
POSTGRES_PASSWORD=StrongPassword
POSTGRES_SSLMODE=prefer

## 3) Initialize DB

```powershell
$env:FLASK_APP = "run.py"
flask init-db
```

## 4) Import Customer Data From Master Tracker

```powershell
$env:FLASK_APP = "run.py"
flask import-master-tracker
```

## 5) Run App

```powershell
python run.py
```

Open: `http://127.0.0.1:5000`

## Login and Session

This app now uses database-backed authentication with session management via Flask-Login.

- Login URL: `/login`
- Logout: available in the top header after login

Default admin user is created during `flask init-db`:

- Username: `admin`
- Password: `admin123`

Change these defaults in `appsettings.json` under `Auth` (or by env vars):

- `Auth.DefaultAdminUsername`
- `Auth.DefaultAdminPassword`

## Main Routes

- `/customers` - Customer list
- `/customers/new` - Add customer
- `/templates` - List templates
- `/templates/new` - Create template (with macros)
- `/emails/send` - Send email using template + customer
- `/gathering/send` - Send gathering request email
- `/gathering/form/<token>` - Customer form page

## Macros Supported

Use in template subject/body:

- `{{customer_name}}`
- `{{account_name}}`
- `{{email}}`
- `{{phone}}`
- `{{city}}`
- `{{segment}}`
- `{{deal_status}}`
- `{{today}}`
- `{{gathering_form_link}}` (used in gathering emails)

## Notes

- If `SMTP_HOST` is empty, app runs in safe dev mode and logs the email request with status `dev-mode`.
- Uploaded files are stored in `uploads/`.
- Logo is served from `static/ambifologo.png`.

## Teams Auto Meeting Links

The Opportunity Edit page now supports auto generation of Microsoft Teams links from the Meeting Links tab.

Required configuration (via `.env` or `appsettings.json`):

- `TEAMS_TENANT_ID`
- `TEAMS_CLIENT_ID`
- `TEAMS_CLIENT_SECRET`
- `TEAMS_ORGANIZER_ID` (user principal name or object id used to create meetings)
- `TEAMS_DEFAULT_DURATION_MINUTES` (optional, default `60`)

Azure app registration requirements:

- Microsoft Graph application permission: `OnlineMeetings.ReadWrite.All`
- Admin consent granted for the tenant

If Teams settings are missing, manual Teams links can still be pasted and sent.

## Deploy On Render (Free Plan)

This repository includes [render.yaml](render.yaml) for one-click Render Blueprint deployment.

### A) Prepare Git Repository (first time)

```powershell
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

### B) Connect GitHub in Render

1. Login to Render.
2. Go to Account Settings > Connected Accounts > GitHub and authorize Render.
3. In Render, click New + > Blueprint.
4. Select your GitHub repo.

### C) Deploy with Blueprint

1. Render will detect [render.yaml](render.yaml).
2. This blueprint auto-creates a free PostgreSQL database (`ambifo-cms-db`).
3. `DATABASE_URL` is automatically injected from the managed database connection string.
4. In the web service Environment tab, fill these required values:

- `APP_BASE_URL` (for example `https://your-app-name.onrender.com`)
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `SMTP_HOST`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`

Optional Teams auto-link values:

- `TEAMS_TENANT_ID`
- `TEAMS_CLIENT_ID`
- `TEAMS_CLIENT_SECRET`
- `TEAMS_ORGANIZER_ID`
- `TEAMS_DEFAULT_DURATION_MINUTES`

Render-specific production notes:

- `render.yaml` is configured to bind Gunicorn to `0.0.0.0:$PORT` (required by Render).
- Health checks use `/login`.
- `SECRET_KEY` is auto-generated by Render on first deploy.
- `DATABASE_URL` comes from Render managed Postgres automatically via blueprint.
- Local folders such as `uploads/` and `documents/` are ephemeral on free web services. Persist files using object storage (S3/Azure) for production use.

Post-deploy quick check:

1. Open `https://your-app-name.onrender.com/login`.
2. Login with `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD` you set in Render.
3. Open Configuration page and verify SMTP and Teams values.
4. Send one test template email and one gathering request.

Notes:

- Free web service may sleep when idle.
- Startup can take longer on free plan.
- Database schema creation and runtime updates happen automatically on app start.
