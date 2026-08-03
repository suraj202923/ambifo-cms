from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    account_name = db.Column(db.String(255), nullable=True)
    customer_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    alternate_emails = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    cloud = db.Column(db.String(80), nullable=True)
    main_page_address = db.Column(db.String(255), nullable=True)
    billing = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    aws_id = db.Column(db.String(120), nullable=True)
    opportunity_id = db.Column(db.String(120), nullable=True)
    segment = db.Column(db.String(80), nullable=True)
    deal_status = db.Column(db.String(80), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    next_action_planned = db.Column(db.Text, nullable=True)
    assign_to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    assigned_to = db.relationship("User", foreign_keys=[assign_to_user_id])


class OpportunityHistory(db.Model):
    __tablename__ = "opportunity_histories"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    changed_by = db.Column(db.String(80), nullable=True)
    action = db.Column(db.String(40), nullable=False)
    tag_name = db.Column(db.String(40), nullable=True, index=True)
    changes_summary = db.Column(db.Text, nullable=False)
    remark = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="history_entries")


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    subject_template = db.Column(db.String(255), nullable=False)
    body_template = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class EmailLog(db.Model):
    __tablename__ = "email_logs"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"), nullable=True)
    recipient_email = db.Column(db.String(255), nullable=True)   # stored for all sends
    email_type = db.Column(db.String(40), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(40), nullable=False)
    queue_status = db.Column(db.String(20), nullable=False, default="immediate")
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    csv_execution_id = db.Column(db.Integer, db.ForeignKey("email_bulk_csv_executions.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="email_logs")
    template = db.relationship("EmailTemplate", backref="email_logs")
    csv_execution = db.relationship("EmailBulkCsvExecution", backref="email_logs")


class EmailUnsubscribe(db.Model):
    __tablename__ = "email_unsubscribes"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    source = db.Column(db.String(80), nullable=True)
    unsubscribed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class EmailBulkCsvExecution(db.Model):
    __tablename__ = "email_bulk_csv_executions"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"), nullable=True)
    uploaded_filename = db.Column(db.String(255), nullable=False)
    bad_log_filename = db.Column(db.String(500), nullable=False)
    success_log_filename = db.Column(db.String(500), nullable=False)
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    unsubscribed_rows = db.Column(db.Integer, nullable=False, default=0)
    invalid_rows = db.Column(db.Integer, nullable=False, default=0)
    sent_rows = db.Column(db.Integer, nullable=False, default=0)
    failed_rows = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    template = db.relationship("EmailTemplate", backref="csv_bulk_executions")


class PartnerReferenceContact(db.Model):
    __tablename__ = "partner_reference_contacts"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True, index=True)
    partner_name = db.Column(db.String(120), nullable=False)
    contact_name = db.Column(db.String(160), nullable=False)
    designation = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="partner_reference_contacts")


class PartnerReferenceActivity(db.Model):
    __tablename__ = "partner_reference_activities"

    id = db.Column(db.Integer, primary_key=True)
    reference_contact_id = db.Column(db.Integer, db.ForeignKey("partner_reference_contacts.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    activity_type = db.Column(db.String(40), nullable=False, default="note")
    activity_date = db.Column(db.DateTime, nullable=True)
    summary = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    next_action = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    reference_contact = db.relationship("PartnerReferenceContact", backref="activities")
    customer = db.relationship("Customer", backref="partner_reference_activities")


class PartnerReferenceOpportunity(db.Model):
    __tablename__ = "partner_reference_opportunities"

    id = db.Column(db.Integer, primary_key=True)
    reference_contact_id = db.Column(db.Integer, db.ForeignKey("partner_reference_contacts.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("reference_contact_id", "customer_id", name="uq_ref_contact_customer"),
    )

    reference_contact = db.relationship("PartnerReferenceContact", backref="opportunity_links")
    customer = db.relationship("Customer", backref="reference_links")


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    lead_name = db.Column(db.String(160), nullable=True)
    email = db.Column(db.String(255), nullable=True, unique=True, index=True)
    phone = db.Column(db.String(100), nullable=True)
    company = db.Column(db.String(160), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    source = db.Column(db.String(120), nullable=True)
    tags = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    raw_payload = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    lead_status = db.Column(db.String(40), nullable=False, default="new")
    last_emailed_at = db.Column(db.DateTime, nullable=True)
    last_email_status = db.Column(db.String(40), nullable=True)
    converted_at = db.Column(db.DateTime, nullable=True)
    converted_customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    converted_customer = db.relationship("Customer", foreign_keys=[converted_customer_id])


class GatheringRequest(db.Model):
    __tablename__ = "gathering_requests"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    note = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    access_key_hash = db.Column(db.String(255), nullable=True)
    access_key_hint = db.Column(db.String(8), nullable=True)
    access_verified_at = db.Column(db.DateTime, nullable=True)
    sheet_file_name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="sent")
    company_website = db.Column(db.String(255), nullable=True)
    current_tools = db.Column(db.Text, nullable=True)
    pain_points = db.Column(db.Text, nullable=True)
    submitted_sheet_path = db.Column(db.String(500), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    locked_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="gathering_requests")


class CustomerDocument(db.Model):
    __tablename__ = "customer_documents"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(500), nullable=True)
    file_path = db.Column(db.String(500), nullable=True)
    blob_url = db.Column(db.String(1000), nullable=True)
    storage_backend = db.Column(db.String(20), nullable=False, default="local")
    file_size_bytes = db.Column(db.Integer, nullable=True)
    mime_type = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    docusign_envelope_id = db.Column(db.String(100), nullable=True, index=True)
    docusign_status = db.Column(db.String(40), nullable=True)
    docusign_sent_at = db.Column(db.DateTime, nullable=True)
    docusign_completed_at = db.Column(db.DateTime, nullable=True)
    docusign_signer_email = db.Column(db.String(255), nullable=True)
    docusign_signer_name = db.Column(db.String(255), nullable=True)
    signed_pdf_path = db.Column(db.String(500), nullable=True)
    uploaded_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="documents")


class CustomerDiagram(db.Model):
    __tablename__ = "customer_diagrams"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    diagram_name = db.Column(db.String(160), nullable=False)
    macro_key = db.Column(db.String(80), nullable=False)
    diagram_content = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="diagrams")


class GatheringServerDetail(db.Model):
    __tablename__ = "gathering_server_details"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    gathering_request_id = db.Column(db.Integer, db.ForeignKey("gathering_requests.id"), nullable=True, index=True)
    server_name = db.Column(db.String(255), nullable=False)
    cpu_cores = db.Column(db.Integer, nullable=True)
    memory_mb = db.Column(db.Integer, nullable=True)
    provisioned_storage_gb = db.Column(db.Float, nullable=True)
    operating_system = db.Column(db.String(255), nullable=True)
    is_virtual = db.Column(db.Boolean, nullable=True)
    hypervisor_name = db.Column(db.String(255), nullable=True)
    cpu_string = db.Column(db.String(255), nullable=True)
    environment = db.Column(db.String(80), nullable=True)
    sql_edition = db.Column(db.String(255), nullable=True)
    application = db.Column(db.String(255), nullable=True)
    cpu_utilization_peak = db.Column(db.Float, nullable=True)
    memory_utilization_peak = db.Column(db.Float, nullable=True)
    time_in_use = db.Column(db.Float, nullable=True)
    annual_cost_usd = db.Column(db.Float, nullable=True)
    storage_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="gathering_server_details")
    gathering_request = db.relationship("GatheringRequest", backref="server_details")


class GatheringFileNasDetail(db.Model):
    __tablename__ = "gathering_file_nas_details"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    gathering_request_id = db.Column(db.Integer, db.ForeignKey("gathering_requests.id"), nullable=True, index=True)
    file_server_share_name = db.Column(db.String(255), nullable=False)
    total_used_capacity_gb = db.Column(db.Float, nullable=True)
    access_protocol = db.Column(db.String(80), nullable=True)
    total_provisioned_capacity_gb = db.Column(db.Float, nullable=True)
    storage_efficiency_ratio = db.Column(db.Float, nullable=True)
    peak_iops = db.Column(db.Float, nullable=True)
    peak_throughput_mbps = db.Column(db.Float, nullable=True)
    average_iops = db.Column(db.Float, nullable=True)
    average_throughput_mbps = db.Column(db.Float, nullable=True)
    storage_pool_name = db.Column(db.String(255), nullable=True)
    array_name = db.Column(db.String(255), nullable=True)
    array_vendor = db.Column(db.String(255), nullable=True)
    average_latency_ms = db.Column(db.Float, nullable=True)
    application = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="gathering_file_nas_details")
    gathering_request = db.relationship("GatheringRequest", backref="file_nas_details")


class GatheringBlockStorageDetail(db.Model):
    __tablename__ = "gathering_block_storage_details"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    gathering_request_id = db.Column(db.Integer, db.ForeignKey("gathering_requests.id"), nullable=True, index=True)
    volume_name = db.Column(db.String(255), nullable=False)
    total_used_capacity_gb = db.Column(db.Float, nullable=True)
    total_provisioned_capacity_gb = db.Column(db.Float, nullable=True)
    peak_iops = db.Column(db.Float, nullable=True)
    peak_throughput_mbps = db.Column(db.Float, nullable=True)
    average_iops = db.Column(db.Float, nullable=True)
    average_throughput_mbps = db.Column(db.Float, nullable=True)
    array_name = db.Column(db.String(255), nullable=True)
    average_latency_ms = db.Column(db.Float, nullable=True)
    application = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="gathering_block_storage_details")
    gathering_request = db.relationship("GatheringRequest", backref="block_storage_details")


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    setting_value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @classmethod
    def get_value(cls, key, default=None):
        setting = cls.query.filter_by(setting_key=key).first()
        return setting.setting_value if setting else default

    @classmethod
    def set_value(cls, key, value):
        setting = cls.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = value
        else:
            setting = cls(setting_key=key, setting_value=value)
            db.session.add(setting)


class OpportunityStatus(db.Model):
    __tablename__ = "opportunity_statuses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    color = db.Column(db.String(20), nullable=False, default="#8a8f98")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class OpportunitySegment(db.Model):
    __tablename__ = "opportunity_segments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    credit_percentage = db.Column(db.Float, nullable=True)
    credit_on_arr = db.Column(db.Boolean, nullable=False, default=False)
    credit_percentage_customer = db.Column(db.Float, nullable=True)
    credit_percentage_ambifo = db.Column(db.Float, nullable=True)
    credit_basis_mrr = db.Column(db.Boolean, nullable=False, default=True)
    credit_basis_arr = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class OpportunityFinancial(db.Model):
    __tablename__ = "opportunity_financials"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, unique=True, index=True)

    expected_mrr = db.Column(db.Float, nullable=True)
    expected_arr = db.Column(db.Float, nullable=True)
    expected_credit_customer = db.Column(db.Float, nullable=True)
    expected_credit_ambifo = db.Column(db.Float, nullable=True)

    actual_mrr = db.Column(db.Float, nullable=True)
    actual_arr = db.Column(db.Float, nullable=True)
    actual_credit_customer = db.Column(db.Float, nullable=True)
    actual_credit_ambifo = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref=db.backref("financial_profile", uselist=False))


class OpportunityCloudOperator(db.Model):
    __tablename__ = "opportunity_cloud_operators"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class OpportunityUpdateTag(db.Model):
    __tablename__ = "opportunity_update_tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, unique=True, index=True)
    color = db.Column(db.String(20), nullable=False, default="#6b7280")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MeetingInvite(db.Model):
    __tablename__ = "meeting_invites"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    recipient_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    meeting_link = db.Column(db.Text, nullable=False)
    agenda = db.Column(db.Text, nullable=True)
    required_data = db.Column(db.Text, nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True, index=True)
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="meeting_invites")


class CustomerSOW(db.Model):
    __tablename__ = "customer_sows"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    sow_title = db.Column(db.String(255), nullable=True)
    version = db.Column(db.String(20), nullable=False, default="1.0")
    master_template_id = db.Column(db.Integer, nullable=True, index=True)
    selected_diagram_ids = db.Column(db.Text, nullable=True)
    sow_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    content_html = db.Column(db.Text, nullable=True)
    docusign_envelope_id = db.Column(db.String(100), nullable=True, index=True)
    docusign_status = db.Column(db.String(40), nullable=True)
    docusign_sent_at = db.Column(db.DateTime, nullable=True)
    docusign_completed_at = db.Column(db.DateTime, nullable=True)
    docusign_signer_email = db.Column(db.String(255), nullable=True)
    docusign_signer_name = db.Column(db.String(255), nullable=True)
    signed_pdf_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.String(80), nullable=True)

    customer = db.relationship("Customer", backref="sows")


class SOWMasterTemplate(db.Model):
    __tablename__ = "sow_master_templates"

    id = db.Column(db.Integer, primary_key=True)
    template_key = db.Column(db.String(40), nullable=False, unique=True, index=True, default="default")
    template_name = db.Column(db.String(120), nullable=False, default="Default Template")
    section_about = db.Column(db.Text, nullable=True)
    section_offerings = db.Column(db.Text, nullable=True)
    section_business_background = db.Column(db.Text, nullable=True)
    section_project_overview = db.Column(db.Text, nullable=True)
    section_problem_statement = db.Column(db.Text, nullable=True)
    section_document_objective = db.Column(db.Text, nullable=True)
    section_success_criteria = db.Column(db.Text, nullable=True)
    section_proposed_solution = db.Column(db.Text, nullable=True)
    section_scope_schedule = db.Column(db.Text, nullable=True)
    section_project_governance = db.Column(db.Text, nullable=True)
    section_commercials_signoff = db.Column(db.Text, nullable=True)
    content_html = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = db.Column(db.String(80), nullable=True)


class SOWMasterTemplateSection(db.Model):
    __tablename__ = "sow_master_template_sections"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("sow_master_templates.id"), nullable=False, index=True)
    section_name = db.Column(db.String(160), nullable=False)
    sequence_no = db.Column(db.Integer, nullable=False, default=1)
    content_html = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    template = db.relationship("SOWMasterTemplate", backref="sections")


class MeetingAvailabilityRequest(db.Model):
    __tablename__ = "meeting_availability_requests"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    recipient_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    option_1_at = db.Column(db.DateTime, nullable=False)
    option_2_at = db.Column(db.DateTime, nullable=False)
    option_3_at = db.Column(db.DateTime, nullable=False)
    customer_option_1_at = db.Column(db.DateTime, nullable=True)
    customer_option_2_at = db.Column(db.DateTime, nullable=True)
    customer_option_3_at = db.Column(db.DateTime, nullable=True)
    extra_recipients = db.Column(db.Text, nullable=True)
    customer_note = db.Column(db.Text, nullable=True)
    customer_submitted_at = db.Column(db.DateTime, nullable=True)
    selected_option = db.Column(db.Integer, nullable=True)
    selected_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(40), nullable=False, default="sent")
    created_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", backref="meeting_availability_requests")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(255), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, plain_password):
        self.password_hash = generate_password_hash(plain_password)

    def check_password(self, plain_password):
        return check_password_hash(self.password_hash, plain_password)

    @property
    def is_active(self):
        return self.is_active_user
