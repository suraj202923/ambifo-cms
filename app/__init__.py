import csv
import json
import os
from pathlib import Path
from urllib.parse import quote_plus

from flask import Blueprint, Flask, flash, redirect, render_template, request, url_for
from flask.cli import with_appcontext
from flask_login import LoginManager
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, inspect, text
from werkzeug.utils import secure_filename

from config import Config
from app.models import Customer, OpportunityUpdateTag, User, db
from app.routes import crm_bp


login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


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
            _ensure_default_admin(app)
            db.session.remove()
            return True, None
        except Exception as exc:
            db.session.remove()
            return False, str(exc)


def _register_db_setup_blueprint(app):
    setup_bp = Blueprint("setup", __name__)

    @setup_bp.route("/")
    def setup_root():
        if app.config.get("DB_READY"):
            return redirect(url_for("crm.opportunity_list"))
        return redirect(url_for("setup.database_setup"))

    @setup_bp.route("/setup/database", methods=["GET", "POST"])
    def database_setup():
        if app.config.get("DB_READY"):
            return redirect(url_for("crm.opportunity_list"))

        defaults = _read_database_defaults(app)
        if request.method == "POST":
            action = (request.form.get("action") or "save").strip().lower()
            connection_url = (request.form.get("connection_url") or "").strip()
            host = (request.form.get("host") or "").strip()
            port = (request.form.get("port") or "").strip()
            name = (request.form.get("name") or "").strip()
            user = (request.form.get("user") or "").strip()
            password = request.form.get("password") or ""
            sslmode = (request.form.get("sslmode") or "prefer").strip() or "prefer"

            form_data = {
                "url": connection_url,
                "host": host,
                "port": port,
                "name": name,
                "user": user,
                "password": password,
                "sslmode": sslmode,
            }

            if connection_url:
                try:
                    _test_database_url_connection(connection_url)
                except Exception as exc:
                    flash(f"Connection failed: {exc}", "error")
                    return render_template("db_setup.html", form_data=form_data, db_error=app.config.get("DB_ERROR"))

                if action == "test":
                    flash("Connection successful.", "success")
                    return render_template("db_setup.html", form_data=form_data, db_error=None)

                try:
                    parsed_parts = _parse_database_url_parts(connection_url, defaults)
                except Exception:
                    parsed_parts = {
                        "host": host or defaults["host"],
                        "port": port or defaults["port"],
                        "name": name or defaults["name"],
                        "user": user or defaults["user"],
                        "password": password or defaults["password"],
                        "sslmode": sslmode or defaults["sslmode"],
                    }

                _save_database_settings(
                    app,
                    host=parsed_parts["host"],
                    port=parsed_parts["port"],
                    name=parsed_parts["name"],
                    user=parsed_parts["user"],
                    password=parsed_parts["password"],
                    sslmode=parsed_parts["sslmode"],
                    url=connection_url,
                )
                db_ready, db_error = _apply_database_settings_to_runtime(
                    app,
                    connection_url=connection_url,
                    host=parsed_parts["host"],
                    port=parsed_parts["port"],
                    name=parsed_parts["name"],
                    user=parsed_parts["user"],
                    password=parsed_parts["password"],
                    sslmode=parsed_parts["sslmode"],
                )

                if db_ready:
                    flash("Database settings saved and connected successfully.", "success")
                    return redirect(url_for("crm.login"))

                flash(f"Saved, but app bootstrap still failed: {db_error}", "error")
                return render_template("db_setup.html", form_data=form_data, db_error=db_error)

            if not all([host, port, name, user]):
                flash("Host, port, database name, and user are required.", "error")
                return render_template("db_setup.html", form_data=form_data, db_error=app.config.get("DB_ERROR"))

            try:
                _test_postgres_connection(host, port, name, user, password, sslmode)
            except Exception as exc:
                flash(f"Connection failed: {exc}", "error")
                return render_template("db_setup.html", form_data=form_data, db_error=app.config.get("DB_ERROR"))

            if action == "test":
                flash("Connection successful.", "success")
                return render_template("db_setup.html", form_data=form_data, db_error=None)

            _save_database_settings(app, host, port, name, user, password, sslmode, url="")
            db_ready, db_error = _apply_database_settings_to_runtime(
                app,
                connection_url="",
                host=host,
                port=port,
                name=name,
                user=user,
                password=password,
                sslmode=sslmode,
            )

            if db_ready:
                flash("Database settings saved and connected successfully.", "success")
                return redirect(url_for("crm.login"))

            flash(f"Saved, but app bootstrap still failed: {db_error}", "error")
            return render_template("db_setup.html", form_data=form_data, db_error=db_error)

        return render_template("db_setup.html", form_data=defaults, db_error=app.config.get("DB_ERROR"))

    app.register_blueprint(setup_bp)


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="templates")
    app.config.from_object(Config)

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
    app.config["DB_READY"] = db_ready
    app.config["DB_ERROR"] = db_error

    # IMPORTANT: register DB-gate before_request BEFORE blueprints so it runs first.
    @app.before_request
    def require_database_setup():
        if app.config.get("DB_READY"):
            return None
        endpoint = request.endpoint or ""
        if endpoint == "static" or endpoint.startswith("setup."):
            return None
        return redirect(url_for("setup.database_setup"))

    app.register_blueprint(crm_bp)
    _register_db_setup_blueprint(app)

    @app.errorhandler(500)
    def internal_error(exc):
        """Catch unhandled 500s and redirect to setup page if DB is not ready."""
        if not app.config.get("DB_READY"):
            return redirect(url_for("setup.database_setup"))
        return render_template("error_500.html"), 500

    @app.cli.command("init-db")
    @with_appcontext
    def init_db_command():
        db.create_all()
        _ensure_runtime_schema_updates()
        _ensure_default_admin(app)
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
