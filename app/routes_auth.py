from flask import current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.models import EmailUnsubscribe, User, db
from app.services.email_service import EmailService


def register_auth_routes(bp):
    if getattr(bp, "_auth_routes_registered", False):
        return
    setattr(bp, "_auth_routes_registered", True)

    @bp.before_app_request
    def require_login_for_crm_routes():
        endpoint = request.endpoint or ""
        g.user = current_user

        allowed_endpoints = {
            "crm.login",
            "crm.email_unsubscribe",
            "crm.gathering_form",
            "crm.gathering_form_sample_xlsx",
            "crm.gathering_form_sample_server_csv",
            "crm.gathering_form_sample_file_nas_csv",
            "crm.gathering_form_sample_block_storage_csv",
            "crm.meeting_availability_select",
            "crm.meeting_availability_form",
            "static",
        }

        if endpoint in allowed_endpoints:
            return

        if endpoint.startswith("crm.") and not current_user.is_authenticated:
            return redirect(url_for("crm.login", next=request.path))

    @bp.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("crm.dashboard"))

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password) and user.is_active_user:
                login_user(user)
                next_url = request.args.get("next") or url_for("crm.dashboard")
                flash("Login successful.", "success")
                return redirect(next_url)

            flash("Invalid username or password.", "error")

        return render_template("login.html")

    @bp.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("Logged out successfully.", "success")
        return redirect(url_for("crm.login"))

    @bp.route("/email/unsubscribe", methods=["GET"])
    def email_unsubscribe():
        token = (request.args.get("token") or "").strip()
        svc = EmailService(current_app)
        email = svc.resolve_unsubscribe_token(token)

        if not email:
            return render_template(
                "email_unsubscribe.html",
                success=False,
                already=False,
                email="",
                message="Invalid or expired unsubscribe link.",
            )

        existing = EmailUnsubscribe.query.filter_by(email=email).first()
        if existing:
            return render_template(
                "email_unsubscribe.html",
                success=True,
                already=True,
                email=email,
                message="This email is already unsubscribed.",
            )

        db.session.add(EmailUnsubscribe(email=email, source="footer-link"))
        db.session.commit()
        return render_template(
            "email_unsubscribe.html",
            success=True,
            already=False,
            email=email,
            message="You have been unsubscribed successfully.",
        )

    @bp.route("/")
    def index():
        return redirect(url_for("crm.dashboard"))
