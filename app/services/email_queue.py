import logging
import threading

logger = logging.getLogger(__name__)

_worker_thread = None
_stop_event = threading.Event()
_work_event = threading.Event()


def wake_queue_worker():
    _work_event.set()


def start_email_queue_worker(app):
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _work_event.clear()
    _worker_thread = threading.Thread(target=_run_queue_loop, args=(app,), daemon=True)
    _worker_thread.start()
    logger.info("Email queue worker started.")


def stop_email_queue_worker():
    _stop_event.set()
    _work_event.set()
    global _worker_thread
    if _worker_thread is not None:
        _worker_thread.join(timeout=5)
        _worker_thread = None
    logger.info("Email queue worker stopped.")


def _run_queue_loop(app):
    while not _stop_event.is_set():
        try:
            processed = _process_next_queued_email(app)
            if processed:
                _stop_event.wait(timeout=1)
            else:
                _work_event.clear()
                _work_event.wait()
        except Exception:
            logger.exception("Email queue worker iteration failed")
            _work_event.clear()
            _work_event.wait(timeout=5)


def _process_next_queued_email(app):
    from app.models import EmailLog, EmailBulkCsvExecution, OpportunityHistory, db
    from app.services.email_service import EmailService

    with app.app_context():
        record = (
            EmailLog.query
            .filter_by(queue_status="queued")
            .order_by(EmailLog.created_at.asc())
            .first()
        )
        if record is None:
            return False

        record.queue_status = "processing"
        db.session.commit()

        try:
            email_service = EmailService(app)
            result = email_service.send_html_email(
                record.recipient_email,
                record.subject,
                record.body,
            )

            if result.success or result.status == "dev-mode":
                record.queue_status = "sent"
                record.status = result.status
            elif result.status == "unsubscribed":
                record.queue_status = "failed"
                record.status = "unsubscribed"
                record.error_message = result.error
            else:
                record.queue_status = "failed"
                record.status = "failed"
                record.error_message = result.error
        except Exception as exc:
            record.queue_status = "failed"
            record.status = "failed"
            record.error_message = str(exc)
            logger.exception("Email queue: exception sending to %s", record.recipient_email)

        if record.csv_execution_id:
            execution = EmailBulkCsvExecution.query.get(record.csv_execution_id)
            if execution:
                if record.queue_status == "sent":
                    execution.sent_rows = (execution.sent_rows or 0) + 1
                elif record.status == "unsubscribed":
                    execution.unsubscribed_rows = (execution.unsubscribed_rows or 0) + 1
                else:
                    execution.failed_rows = (execution.failed_rows or 0) + 1

        if record.customer_id:
            final_tag = "email"
            action = "email-sent" if record.queue_status == "sent" else "email-failed"
            summary = (
                f"Queued email processed to {record.recipient_email}. "
                f"Subject: {record.subject}. Status: {record.status}."
            )
            db.session.add(
                OpportunityHistory(
                    customer_id=record.customer_id,
                    changed_by="system",
                    action=action,
                    tag_name=final_tag,
                    changes_summary=summary,
                )
            )

        db.session.commit()
        return True
