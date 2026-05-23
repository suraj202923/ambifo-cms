from datetime import datetime, timedelta

from flask import jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, load_only

from app.models import Customer, MeetingInvite, OpportunityHistory, OpportunityUpdateTag, User


def register_dashboard_routes(bp, *, derive_tag_from_action, tag_color_map):
    if getattr(bp, "_dashboard_routes_registered", False):
        return
    setattr(bp, "_dashboard_routes_registered", True)

    def _dashboard_period_bounds(period, start_raw=None, end_raw=None):
        now = datetime.utcnow()
        period = (period or "monthly").strip().lower()

        if period == "weekly":
            start = now - timedelta(days=7)
            end = now
        elif period == "quarterly":
            start = now - timedelta(days=90)
            end = now
        elif period == "yearly":
            start = now - timedelta(days=365)
            end = now
        elif period == "custom":
            try:
                start = datetime.strptime((start_raw or "").strip(), "%Y-%m-%d")
                end = datetime.strptime((end_raw or "").strip(), "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                start = now - timedelta(days=30)
                end = now
        else:
            start = now - timedelta(days=30)
            end = now
        return start, end

    def _split_city_country(city_value):
        raw = (city_value or "").strip()
        if not raw:
            return "Unknown", "Unknown"
        if "," in raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) >= 2:
                return parts[0], parts[-1]
        if "-" in raw:
            parts = [p.strip() for p in raw.split("-") if p.strip()]
            if len(parts) >= 2:
                return parts[0], parts[-1]
        return raw, "Unknown"

    def _build_dashboard_graph_payload(start_dt, end_dt):
        assign_rows = (
            Customer.query
            .outerjoin(User, Customer.assign_to_user_id == User.id)
            .with_entities(func.coalesce(User.username, "Unassigned"), func.count(Customer.id))
            .filter(Customer.created_at >= start_dt, Customer.created_at < end_dt)
            .group_by(func.coalesce(User.username, "Unassigned"))
            .all()
        )
        segment_rows = (
            Customer.query
            .with_entities(func.coalesce(func.nullif(func.trim(Customer.segment), ""), "Not Set"), func.count(Customer.id))
            .filter(Customer.created_at >= start_dt, Customer.created_at < end_dt)
            .group_by(func.coalesce(func.nullif(func.trim(Customer.segment), ""), "Not Set"))
            .all()
        )
        status_rows = (
            Customer.query
            .with_entities(func.coalesce(func.nullif(func.trim(Customer.deal_status), ""), "Not Set"), func.count(Customer.id))
            .filter(Customer.created_at >= start_dt, Customer.created_at < end_dt)
            .group_by(func.coalesce(func.nullif(func.trim(Customer.deal_status), ""), "Not Set"))
            .all()
        )
        city_values = (
            Customer.query
            .with_entities(Customer.city)
            .filter(Customer.created_at >= start_dt, Customer.created_at < end_dt)
            .all()
        )
        total_opportunities = (
            Customer.query
            .filter(Customer.created_at >= start_dt, Customer.created_at < end_dt)
            .count()
        )

        assign_counts = {label: count for label, count in assign_rows}
        segment_counts = {label: count for label, count in segment_rows}
        status_counts = {label: count for label, count in status_rows}
        country_counts = {}
        city_counts = {}

        for (city_value,) in city_values:
            city, country = _split_city_country(city_value)
            country_counts[country] = country_counts.get(country, 0) + 1
            city_counts[city] = city_counts.get(city, 0) + 1

        top_cities = sorted(city_counts.items(), key=lambda kv: kv[1], reverse=True)[:12]

        return {
            "summary": {
                "total_opportunities": total_opportunities,
                "from": start_dt.strftime("%Y-%m-%d"),
                "to": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            },
            "assign": {
                "labels": list(assign_counts.keys()),
                "values": list(assign_counts.values()),
            },
            "segment": {
                "labels": list(segment_counts.keys()),
                "values": list(segment_counts.values()),
            },
            "status": {
                "labels": list(status_counts.keys()),
                "values": list(status_counts.values()),
            },
            "country": {
                "labels": list(country_counts.keys()),
                "values": list(country_counts.values()),
            },
            "city": {
                "labels": [c for c, _ in top_cities],
                "values": [v for _, v in top_cities],
            },
        }

    @bp.route("/dashboard")
    @login_required
    def dashboard():
        tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
        return render_template(
            "dashboard.html",
            update_tags=tags,
        )

    @bp.route("/dashboard/graph-data", methods=["GET"])
    @login_required
    def dashboard_graph_data():
        period = (request.args.get("period") or "monthly").strip().lower()
        start_raw = request.args.get("start")
        end_raw = request.args.get("end")
        start_dt, end_dt = _dashboard_period_bounds(period, start_raw, end_raw)
        payload = _build_dashboard_graph_payload(start_dt, end_dt)
        payload["period"] = period
        return jsonify(success=True, data=payload)

    @bp.route("/dashboard/history-data", methods=["GET"])
    @login_required
    def dashboard_history_data():
        tag_filter = (request.args.get("tag") or "important").strip().lower()
        limit = request.args.get("limit", 25, type=int)
        if limit < 1:
            limit = 25
        if limit > 200:
            limit = 200

        query = (
            OpportunityHistory.query
            .options(
                load_only(
                    OpportunityHistory.id,
                    OpportunityHistory.customer_id,
                    OpportunityHistory.changed_by,
                    OpportunityHistory.action,
                    OpportunityHistory.tag_name,
                    OpportunityHistory.changes_summary,
                    OpportunityHistory.remark,
                    OpportunityHistory.created_at,
                ),
                joinedload(OpportunityHistory.customer).load_only(Customer.id, Customer.customer_name),
            )
            .order_by(OpportunityHistory.created_at.desc())
        )
        if tag_filter != "all":
            query = query.filter(OpportunityHistory.tag_name == tag_filter)
        rows = query.limit(limit).all()

        tag_colors = tag_color_map()
        items = []
        for h in rows:
            tag = (h.tag_name or derive_tag_from_action(h.action)).lower()
            items.append(
                {
                    "created_at": h.created_at.strftime("%Y-%m-%d %H:%M"),
                    "customer_id": h.customer_id,
                    "customer_name": h.customer.customer_name if h.customer else "Unknown",
                    "changed_by": h.changed_by or "system",
                    "action": h.action,
                    "tag": tag,
                    "tag_color": tag_colors.get(tag, "#6b7280"),
                    "changes_summary": h.changes_summary,
                    "remark": h.remark or "",
                }
            )

        tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
        return jsonify(
            success=True,
            applied_tag=tag_filter,
            available_tags=[{"name": "all", "color": "#4b5563"}] + [{"name": t.name, "color": t.color} for t in tags],
            items=items,
        )

    @bp.route("/dashboard/upcoming-meetings-data", methods=["GET"])
    @login_required
    def dashboard_upcoming_meetings_data():
        tag_filter = (request.args.get("tag") or "all").strip().lower()
        limit = request.args.get("limit", 20, type=int)
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100

        if tag_filter not in {"all", "meeting"}:
            return jsonify(success=True, items=[])

        now = datetime.utcnow()
        rows = (
            MeetingInvite.query
            .options(
                load_only(
                    MeetingInvite.id,
                    MeetingInvite.customer_id,
                    MeetingInvite.recipient_email,
                    MeetingInvite.subject,
                    MeetingInvite.meeting_link,
                    MeetingInvite.scheduled_at,
                    MeetingInvite.created_by,
                ),
                joinedload(MeetingInvite.customer).load_only(Customer.id, Customer.customer_name),
            )
            .filter(MeetingInvite.scheduled_at.isnot(None), MeetingInvite.scheduled_at >= now)
            .order_by(MeetingInvite.scheduled_at.asc())
            .limit(limit)
            .all()
        )

        items = []
        for m in rows:
            items.append(
                {
                    "id": m.id,
                    "customer_id": m.customer_id,
                    "customer_name": m.customer.customer_name if m.customer else "Unknown",
                    "recipient_email": m.recipient_email,
                    "subject": m.subject,
                    "meeting_link": m.meeting_link,
                    "scheduled_at": m.scheduled_at.strftime("%Y-%m-%d %H:%M") if m.scheduled_at else "TBD",
                    "created_by": m.created_by or "system",
                }
            )

        return jsonify(success=True, items=items)
