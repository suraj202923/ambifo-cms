from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.models import OpportunityUpdateTag, User, db
from app.services.admin_notification_service import (
    CORE_HISTORY_TAGS,
    load_admin_history_notification_subscriptions,
    save_admin_history_notification_subscriptions,
)


ADMIN_USERS_ANCHOR = "#admin-users-config"


def _admin_redirect():
    return redirect(url_for("crm.configuration") + ADMIN_USERS_ANCHOR)


def handle_configuration_admin_action(action):
    if action == "add_admin_user":
        username = (request.form.get("admin_username") or "").strip()
        email = (request.form.get("admin_email") or "").strip().lower()
        password = request.form.get("admin_password") or ""

        if not username:
            flash("Admin username is required.", "error")
            return _admin_redirect()
        if not email or "@" not in email:
            flash("Valid admin email is required.", "error")
            return _admin_redirect()
        if len(password) < 6:
            flash("Admin password must be at least 6 characters.", "error")
            return _admin_redirect()
        if User.query.filter_by(username=username).first():
            flash("Admin username already exists.", "error")
            return _admin_redirect()
        if User.query.filter_by(email=email).first():
            flash("Admin email already exists.", "error")
            return _admin_redirect()

        user = User(username=username, email=email, is_active_user=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Admin user added.", "success")
        return _admin_redirect()

    if action == "reset_all_admin_passwords":
        new_password = request.form.get("admin_reset_password") or ""
        if len(new_password) < 6:
            flash("Reset password must be at least 6 characters.", "error")
            return _admin_redirect()

        admin_users_for_reset = User.query.filter_by(is_active_user=True).all()
        if not admin_users_for_reset:
            flash("No active admin users found.", "error")
            return _admin_redirect()

        for admin_user in admin_users_for_reset:
            admin_user.set_password(new_password)
        db.session.commit()
        flash(f"Password reset completed for {len(admin_users_for_reset)} admin user(s).", "success")
        return _admin_redirect()

    if action == "reset_admin_password":
        user_id = request.form.get("reset_user_id", type=int)
        new_password = request.form.get("reset_user_password") or ""

        user = User.query.get(user_id) if user_id else None
        if not user:
            flash("Admin user not found.", "error")
            return _admin_redirect()

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return _admin_redirect()

        user.set_password(new_password)
        db.session.commit()
        flash(f"Password reset for admin user {user.username}.", "success")
        return _admin_redirect()

    if action == "delete_admin_user":
        user_id = request.form.get("delete_user_id", type=int)
        user = User.query.get(user_id) if user_id else None
        if not user:
            flash("Admin user not found.", "error")
            return _admin_redirect()

        if current_user and current_user.is_authenticated and int(current_user.id) == int(user.id):
            flash("You cannot delete your own currently logged-in admin user.", "error")
            return _admin_redirect()

        active_admin_count = User.query.filter_by(is_active_user=True).count()
        if user.is_active_user and active_admin_count <= 1:
            flash("At least one active admin user must remain.", "error")
            return _admin_redirect()

        subscriptions = load_admin_history_notification_subscriptions()
        if user.id in subscriptions:
            subscriptions.pop(user.id, None)
            save_admin_history_notification_subscriptions(subscriptions)

        db.session.delete(user)
        db.session.commit()
        flash(f"Admin user {user.username} removed.", "success")
        return _admin_redirect()

    if action == "save_admin_notification_subscription":
        user_id = request.form.get("notification_user_id", type=int)
        user = User.query.get(user_id) if user_id else None
        if not user:
            flash("Admin user not found.", "error")
            return _admin_redirect()

        enabled = bool(request.form.get("notification_enabled"))
        allowed_tags = {
            (tag.name or "").strip().lower()
            for tag in OpportunityUpdateTag.query.filter_by(is_active=True).all()
            if (tag.name or "").strip()
        }
        allowed_tags.update(CORE_HISTORY_TAGS)

        selected_tags = []
        for raw_tag in request.form.getlist("notification_tags"):
            tag_name = (raw_tag or "").strip().lower()
            if tag_name and tag_name in allowed_tags and tag_name not in selected_tags:
                selected_tags.append(tag_name)

        subscriptions = load_admin_history_notification_subscriptions()
        subscriptions[user.id] = {
            "enabled": enabled,
            "tags": selected_tags,
        }
        save_admin_history_notification_subscriptions(subscriptions)
        db.session.commit()
        flash(f"Notification subscription updated for {user.username}.", "success")
        return _admin_redirect()

    return None
