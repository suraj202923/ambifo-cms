import csv
import json
import os
from pathlib import Path
from urllib.parse import quote_plus

from flask import Flask, render_template, send_from_directory
from flask.cli import with_appcontext
from flask_login import LoginManager
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, inspect, text
from werkzeug.utils import secure_filename

from config import Config
from app.models import Customer, OpportunityUpdateTag, User, db
from app.routes import crm_bp, ensure_default_system_email_templates


login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        # DB not ready (e.g. no connection configured yet on first deploy).
        return None


def _ensure_default_admin(app):
    username = app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
    password = app.config.get("DEFAULT_ADMIN_PASSWORD", "admin123")

    if not username or not password:
        return

    existing = User.query.filter_by(username=username).first()
    if existing:
        return

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f"Default admin created: {username}")


def _ensure_runtime_schema_updates():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    if "gathering_requests" not in existing_tables:
        pass

    if "gathering_requests" in existing_tables:
        existing_columns = {col["name"] for col in inspector.get_columns("gathering_requests")}
        desired_columns = {
            "expires_at": "ALTER TABLE gathering_requests ADD COLUMN expires_at TIMESTAMP",
            "access_key_hash": "ALTER TABLE gathering_requests ADD COLUMN access_key_hash VARCHAR(255)",
            "access_key_hint": "ALTER TABLE gathering_requests ADD COLUMN access_key_hint VARCHAR(8)",
            "access_verified_at": "ALTER TABLE gathering_requests ADD COLUMN access_verified_at TIMESTAMP",
            "is_locked": "ALTER TABLE gathering_requests ADD COLUMN is_locked BOOLEAN NOT NULL DEFAULT FALSE",
            "locked_at": "ALTER TABLE gathering_requests ADD COLUMN locked_at TIMESTAMP",
            "locked_by": "ALTER TABLE gathering_requests ADD COLUMN locked_by VARCHAR(80)",
        }

        for column_name, ddl in desired_columns.items():
            if column_name in existing_columns:
                continue
            db.session.execute(text(ddl))

    if "opportunity_histories" in existing_tables:
        history_columns = {col["name"] for col in inspector.get_columns("opportunity_histories")}
        if "tag_name" not in history_columns:
            db.session.execute(text("ALTER TABLE opportunity_histories ADD COLUMN tag_name VARCHAR(40)"))

    if "meeting_availability_requests" in existing_tables:
        mar_columns = {col["name"] for col in inspector.get_columns("meeting_availability_requests")}
        mar_desired = {
            "customer_option_1_at": "ALTER TABLE meeting_availability_requests ADD COLUMN customer_option_1_at TIMESTAMP",
            "customer_option_2_at": "ALTER TABLE meeting_availability_requests ADD COLUMN customer_option_2_at TIMESTAMP",
            "customer_option_3_at": "ALTER TABLE meeting_availability_requests ADD COLUMN customer_option_3_at TIMESTAMP",
            "extra_recipients": "ALTER TABLE meeting_availability_requests ADD COLUMN extra_recipients TEXT",
            "customer_note": "ALTER TABLE meeting_availability_requests ADD COLUMN customer_note TEXT",
            "customer_submitted_at": "ALTER TABLE meeting_availability_requests ADD COLUMN customer_submitted_at TIMESTAMP",
        }
        for column_name, ddl in mar_desired.items():
            if column_name in mar_columns:
                continue
            db.session.execute(text(ddl))

    if "customers" in existing_tables:
        customer_columns = {col["name"] for col in inspector.get_columns("customers")}
        if "cloud" not in customer_columns:
            db.session.execute(text("ALTER TABLE customers ADD COLUMN cloud VARCHAR(80)"))
        if "main_page_address" not in customer_columns:
            db.session.execute(text("ALTER TABLE customers ADD COLUMN main_page_address VARCHAR(255)"))
        if "billing" not in customer_columns:
            db.session.execute(text("ALTER TABLE customers ADD COLUMN billing VARCHAR(255)"))

    if "customer_sows" in existing_tables:
        sow_columns = {col["name"] for col in inspector.get_columns("customer_sows")}
        if "master_template_id" not in sow_columns:
            db.session.execute(text("ALTER TABLE customer_sows ADD COLUMN master_template_id INTEGER"))
        if "selected_diagram_ids" not in sow_columns:
            db.session.execute(text("ALTER TABLE customer_sows ADD COLUMN selected_diagram_ids TEXT"))

    if "sow_master_templates" in existing_tables:
        master_columns = {col["name"] for col in inspector.get_columns("sow_master_templates")}
        master_desired = {
            "template_name": "ALTER TABLE sow_master_templates ADD COLUMN template_name VARCHAR(120)",
            "section_about": "ALTER TABLE sow_master_templates ADD COLUMN section_about TEXT",
            "section_offerings": "ALTER TABLE sow_master_templates ADD COLUMN section_offerings TEXT",
            "section_business_background": "ALTER TABLE sow_master_templates ADD COLUMN section_business_background TEXT",
            "section_project_overview": "ALTER TABLE sow_master_templates ADD COLUMN section_project_overview TEXT",
            "section_problem_statement": "ALTER TABLE sow_master_templates ADD COLUMN section_problem_statement TEXT",
            "section_document_objective": "ALTER TABLE sow_master_templates ADD COLUMN section_document_objective TEXT",
            "section_success_criteria": "ALTER TABLE sow_master_templates ADD COLUMN section_success_criteria TEXT",
            "section_proposed_solution": "ALTER TABLE sow_master_templates ADD COLUMN section_proposed_solution TEXT",
            "section_scope_schedule": "ALTER TABLE sow_master_templates ADD COLUMN section_scope_schedule TEXT",
            "section_project_governance": "ALTER TABLE sow_master_templates ADD COLUMN section_project_governance TEXT",
            "section_commercials_signoff": "ALTER TABLE sow_master_templates ADD COLUMN section_commercials_signoff TEXT",
        }
        for column_name, ddl in master_desired.items():
            if column_name in master_columns:
                continue
            db.session.execute(text(ddl))

    if "sow_master_template_sections" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE sow_master_template_sections ("
            "id SERIAL PRIMARY KEY, "
            "template_id INTEGER NOT NULL, "
            "section_name VARCHAR(160) NOT NULL, "
            "sequence_no INTEGER NOT NULL DEFAULT 1, "
            "content_html TEXT NOT NULL, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_sow_master_template_sections_template_id ON sow_master_template_sections (template_id)"))

    if "customer_diagrams" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE customer_diagrams ("
            "id SERIAL PRIMARY KEY, "
            "customer_id INTEGER NOT NULL, "
            "diagram_name VARCHAR(160) NOT NULL, "
            "macro_key VARCHAR(80) NOT NULL, "
            "diagram_content TEXT NOT NULL, "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
            "created_by VARCHAR(80), "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_customer_diagrams_customer_id ON customer_diagrams (customer_id)"))

    if "email_logs" in existing_tables:
        email_log_columns = {col["name"]: col for col in inspector.get_columns("email_logs")}
        customer_col = email_log_columns.get("customer_id")
        if customer_col and customer_col.get("nullable") is False:
            db.session.execute(text("ALTER TABLE email_logs ALTER COLUMN customer_id DROP NOT NULL"))

    if "email_unsubscribes" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE email_unsubscribes ("
            "id SERIAL PRIMARY KEY, "
            "email VARCHAR(255) NOT NULL UNIQUE, "
            "source VARCHAR(80), "
            "unsubscribed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))

    if "email_bulk_csv_executions" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE email_bulk_csv_executions ("
            "id SERIAL PRIMARY KEY, "
            "template_id INTEGER, "
            "uploaded_filename VARCHAR(255) NOT NULL, "
            "bad_log_filename VARCHAR(500) NOT NULL, "
            "success_log_filename VARCHAR(500) NOT NULL, "
            "total_rows INTEGER NOT NULL DEFAULT 0, "
            "unsubscribed_rows INTEGER NOT NULL DEFAULT 0, "
            "invalid_rows INTEGER NOT NULL DEFAULT 0, "
            "sent_rows INTEGER NOT NULL DEFAULT 0, "
            "failed_rows INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))

    if "partner_reference_contacts" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE partner_reference_contacts ("
            "id SERIAL PRIMARY KEY, "
            "customer_id INTEGER, "
            "partner_name VARCHAR(120) NOT NULL, "
            "contact_name VARCHAR(160) NOT NULL, "
            "designation VARCHAR(120), "
            "email VARCHAR(255), "
            "phone VARCHAR(100), "
            "city VARCHAR(120), "
            "notes TEXT, "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_partner_reference_contacts_customer_id ON partner_reference_contacts (customer_id)"))
    else:
        ref_columns = {col["name"]: col for col in inspector.get_columns("partner_reference_contacts")}
        customer_col = ref_columns.get("customer_id")
        if customer_col and customer_col.get("nullable") is False:
            db.session.execute(text("ALTER TABLE partner_reference_contacts ALTER COLUMN customer_id DROP NOT NULL"))

    if "partner_reference_activities" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE partner_reference_activities ("
            "id SERIAL PRIMARY KEY, "
            "reference_contact_id INTEGER NOT NULL, "
            "customer_id INTEGER NOT NULL, "
            "activity_type VARCHAR(40) NOT NULL DEFAULT 'note', "
            "activity_date TIMESTAMP, "
            "summary VARCHAR(255) NOT NULL, "
            "details TEXT, "
            "next_action VARCHAR(255), "
            "created_by VARCHAR(80), "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_partner_reference_activities_contact_id ON partner_reference_activities (reference_contact_id)"))
        db.session.execute(text("CREATE INDEX idx_partner_reference_activities_customer_id ON partner_reference_activities (customer_id)"))

    if "partner_reference_opportunities" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE partner_reference_opportunities ("
            "id SERIAL PRIMARY KEY, "
            "reference_contact_id INTEGER NOT NULL, "
            "customer_id INTEGER NOT NULL, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_partner_reference_opportunities_ref_id ON partner_reference_opportunities (reference_contact_id)"))
        db.session.execute(text("CREATE INDEX idx_partner_reference_opportunities_customer_id ON partner_reference_opportunities (customer_id)"))
        db.session.execute(text("CREATE UNIQUE INDEX uq_ref_contact_customer ON partner_reference_opportunities (reference_contact_id, customer_id)"))

    if "leads" not in existing_tables:
        db.session.execute(text(
            "CREATE TABLE leads ("
            "id SERIAL PRIMARY KEY, "
            "lead_name VARCHAR(160), "
            "email VARCHAR(255) UNIQUE, "
            "phone VARCHAR(100), "
            "company VARCHAR(160), "
            "city VARCHAR(120), "
            "source VARCHAR(120), "
            "tags VARCHAR(255), "
            "notes TEXT, "
            "raw_payload TEXT, "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
            "lead_status VARCHAR(40) NOT NULL DEFAULT 'new', "
            "last_emailed_at TIMESTAMP, "
            "last_email_status VARCHAR(40), "
            "converted_at TIMESTAMP, "
            "converted_customer_id INTEGER, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        db.session.execute(text("CREATE INDEX idx_leads_email ON leads (email)"))
    else:
        lead_columns = {col["name"] for col in inspector.get_columns("leads")}
        if "lead_status" not in lead_columns:
            db.session.execute(text("ALTER TABLE leads ADD COLUMN lead_status VARCHAR(40) NOT NULL DEFAULT 'new'"))
        if "converted_at" not in lead_columns:
            db.session.execute(text("ALTER TABLE leads ADD COLUMN converted_at TIMESTAMP"))
        if "converted_customer_id" not in lead_columns:
            db.session.execute(text("ALTER TABLE leads ADD COLUMN converted_customer_id INTEGER"))

    default_tags = [
        ("important", "#c0392b"),
        ("email", "#1d4ed8"),
        ("meeting", "#2563eb"),
        ("gathering", "#0f766e"),
        ("status", "#7c3aed"),
        ("segment", "#d97706"),
        ("assign", "#0891b2"),
        ("update", "#374151"),
    ]
    for tag_name, color in default_tags:
        existing = OpportunityUpdateTag.query.filter_by(name=tag_name).first()
        if existing:
            continue
        db.session.add(OpportunityUpdateTag(name=tag_name, color=color, is_active=True))

    db.session.commit()


def _database_settings_file(app):
    return Path(app.root_path).parent / "appsettings.json"


def _read_database_defaults(app):
    settings_file = _database_settings_file(app)
    defaults = {
        "url": "",
        "host": "localhost",
        "port": "5432",
        "name": "ambifo_crm",
        "user": "postgres",
        "password": "",
        "sslmode": "prefer",
    }
    if not settings_file.exists():
        return defaults

    try:
        with settings_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return defaults

    db_data = data.get("Database") or {}
    defaults["url"] = str(db_data.get("Url", defaults["url"]))
    defaults["host"] = str(db_data.get("Host", defaults["host"]))
    defaults["port"] = str(db_data.get("Port", defaults["port"]))
    defaults["name"] = str(db_data.get("Name", defaults["name"]))
    defaults["user"] = str(db_data.get("User", defaults["user"]))
    defaults["password"] = str(db_data.get("Password", defaults["password"]))
    defaults["sslmode"] = str(db_data.get("SSLMode", defaults["sslmode"]))
    return defaults


def _save_database_settings(app, host, port, name, user, password, sslmode, url=""):
    settings_file = _database_settings_file(app)
    data = {}

    if settings_file.exists():
        try:
            with settings_file.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}

    data.setdefault("Database", {})
    data["Database"].update(
        {
            "Host": host,
            "Port": int(port),
            "Name": name,
            "User": user,
            "Password": password,
            "SSLMode": sslmode,
            "Url": (url or "").strip(),
        }
    )

    with settings_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _build_postgres_url(host, port, name, user, password, sslmode):
    return (
        f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{name}"
        f"?sslmode={sslmode}"
    )


def _test_postgres_connection(host, port, name, user, password, sslmode):
    db_url = _build_postgres_url(host, port, name, user, password, sslmode)
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _test_database_url_connection(db_url):
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _apply_database_settings_to_runtime(app, connection_url, host, port, name, user, password, sslmode):
    runtime_url = (connection_url or "").strip() or _build_postgres_url(host, port, name, user, password, sslmode)
    app.config["SQLALCHEMY_DATABASE_URI"] = runtime_url
    os.environ["DATABASE_URL"] = runtime_url

    # Rebind Flask-SQLAlchemy to the new URL without restarting the service.
    ext = app.extensions.get("sqlalchemy")
    if ext:
        existing_engines = ext._app_engines.get(app, {})
        current_engine = existing_engines.get(None)
        if current_engine is not None:
            current_engine.dispose()
        ext._app_engines[app] = {None: create_engine(runtime_url)}

    db.session.remove()

    db_ready, db_error = _bootstrap_database(app)
    app.config["DB_READY"] = db_ready
    app.config["DB_ERROR"] = db_error
    return db_ready, db_error


def _parse_database_url_parts(db_url, defaults):
    parsed = make_url(db_url)
    query = parsed.query or {}
    return {
        "host": parsed.host or defaults["host"],
        "port": str(parsed.port or defaults["port"]),
        "name": (parsed.database or defaults["name"]),
        "user": (parsed.username or defaults["user"]),
        "password": (parsed.password or defaults["password"]),
        "sslmode": str(query.get("sslmode") or defaults["sslmode"]),
    }


def _bootstrap_database(app):
    with app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
            db.create_all()
            _ensure_runtime_schema_updates()
            ensure_default_system_email_templates()
            _ensure_default_admin(app)
            db.session.commit()
            db.session.remove()
            return True, None
        except Exception as exc:
            db.session.remove()
            return False, str(exc)


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="templates")
    app.config.from_object(Config)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

    upload_path = Path(app.config["UPLOAD_FOLDER"])
    if not upload_path.is_absolute():
        upload_path = Path(app.root_path).parent / upload_path
    upload_path.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_path)

    docs_path = Path(app.config["DOCUMENTS_FOLDER"])
    if not docs_path.is_absolute():
        docs_path = Path(app.root_path).parent / docs_path
    docs_path.mkdir(parents=True, exist_ok=True)
    app.config["DOCUMENTS_FOLDER"] = str(docs_path)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "crm.login"
    login_manager.login_message = "Please login to continue."
    login_manager.login_message_category = "error"

    db_ready, db_error = _bootstrap_database(app)
    if not db_ready:
        raise RuntimeError(f"Database bootstrap failed: {db_error}")

    app.register_blueprint(crm_bp)

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.after_request
    def add_noindex_headers(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet, noimageindex"
        return response

    @app.errorhandler(500)
    def internal_error(exc):
        """Catch unhandled 500s and show error page."""
        return render_template("error_500.html"), 500

    @app.cli.command("init-db")
    @with_appcontext
    def init_db_command():
        db.create_all()
        _ensure_runtime_schema_updates()
        ensure_default_system_email_templates()
        _ensure_default_admin(app)
        db.session.commit()
        print("Database tables created.")

    @app.cli.command("import-master-tracker")
    @with_appcontext
    def import_master_tracker_command():
        project_root = Path(app.root_path).parent
        csv_path = project_root / "Master Tracker(Sheet1).csv"
        if not csv_path.exists():
            print("Master Tracker(Sheet1).csv not found.")
            return

        with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            count = 0
            for row in reader:
                email = (row.get("Email") or "").strip()
                account_name = (row.get("Account Name") or row.get("Account Name ") or "").strip()
                customer_name = (row.get("Cusotmer Name") or row.get("Customer Name") or "").strip()

                if not email and not customer_name and not account_name:
                    continue

                existing = Customer.query.filter_by(email=email).first() if email else None
                if existing:
                    continue

                customer = Customer(
                    account_name=account_name,
                    customer_name=customer_name,
                    email=email,
                    phone=(row.get("Phone Number") or "").strip(),
                    city=(row.get("City") or "").strip(),
                    aws_id=(row.get("AWS ID") or "").strip(),
                    opportunity_id=(row.get("Opportunity ID") or "").strip(),
                    segment=(row.get("Segment") or row.get("Segment ") or "").strip(),
                    deal_status=(row.get("Deal Status") or row.get("Deal Status ") or "").strip(),
                    comment=(row.get("Comment") or row.get("Comment ") or "").strip(),
                    next_action_planned=(row.get("Next Action Planned") or row.get("Next Action Planned ") or "").strip(),
                )
                db.session.add(customer)
                count += 1

            db.session.commit()
            print(f"Imported {count} customers from master tracker.")

    return app


# Expose a module-level WSGI app for servers configured as `gunicorn app:app`.
app = create_app()
