export interface User {
  id: number
  username: string
  email: string
  full_name: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string
}

export interface AdminUserCreate {
  username: string
  email: string
  password: string
  full_name?: string | null
  is_admin?: boolean
}

export interface AdminUserUpdate {
  email?: string | null
  full_name?: string | null
  is_active?: boolean
  is_admin?: boolean
  new_password?: string | null
}

export interface Customer {
  id: number
  account_name: string | null
  customer_name: string
  designation: string | null
  email: string
  alternate_emails: string | null
  phone: string | null
  cloud: string | null
  main_page_address: string | null
  billing: string | null
  city: string | null
  aws_id: string | null
  aws_calculator_link: string | null
  opportunity_id: string | null
  segment: string | null
  deal_status: string | null
comment: string | null
  next_action_planned: string | null
  assign_to_user_id: number | null
  created_at: string
  updated_at: string
}

export type CustomerCreate = Omit<
  Customer,
  'id' | 'created_at' | 'updated_at'
>

export type CustomerUpdate = Partial<CustomerCreate>

export interface CustomerStats {
  total: number
  open: number
  won: number
  lost: number
  segments: number
  clouds: number
}

export interface History {
  id: number
  customer_id: number
  changed_by: string | null
  action: string
  tag_name: string | null
  changes_summary: string
  remark: string | null
  created_at: string
}

export interface Financial {
  id: number
  customer_id: number
  expected_mrr: number | null
  expected_arr: number | null
  expected_credit_customer: number | null
  expected_credit_ambifo: number | null
  actual_mrr: number | null
  actual_arr: number | null
  actual_credit_customer: number | null
  actual_credit_ambifo: number | null
  credits_requested: number | null
  credits_gets: number | null
  phases_to_distribute: number | null
}

export interface Lead {
  id: number
  lead_name: string | null
  email: string | null
  phone: string | null
  company: string | null
  city: string | null
  source: string | null
  tags: string | null
  notes: string | null
  is_active: boolean
  lead_status: string
  last_emailed_at: string | null
  last_email_status: string | null
converted_at: string | null
  converted_customer_id: number | null
  created_at: string
  updated_at: string
}

export type LeadCreate = Pick<
  Lead,
  'lead_name' | 'email' | 'phone' | 'company' | 'city' | 'source' | 'tags' | 'notes'
> & { lead_status?: string }

export type LeadUpdate = Partial<LeadCreate> & { is_active?: boolean }

export interface LeadStats {
  total: number
  new: number
  contacted: number
  qualified: number
  converted: number
  lost: number
}

export interface DashboardData {
  kpis: {
    total_customers: number
    total_leads: number
    open_opportunities: number
    total_mrr: number
    total_arr: number
    customers_added_30d: number
  }
  by_status: { name: string; color: string; count: number }[]
  by_segment: { name: string; count: number }[]
  by_assignee: { name: string; count: number }[]
  recent_history: {
    id: number
    customer_id: number
    changed_by: string | null
    action: string
    tag_name: string | null
    changes_summary: string
    created_at: string | null
  }[]
  opportunities_by_month: { month: string; count: number }[]
}

export interface Lookups {
  statuses: { id: number; name: string; color: string }[]
  segments: { id: number; name: string }[]
  cloud_operators: { id: number; name: string }[]
  update_tags: { id: number; name: string; color: string }[]
  users: { id: number; username: string }[]
}

// ------------------------------------------------------------------ Email
export interface EmailTemplate {
  id: number
  name: string
  subject_template: string
  body_template: string
  is_active: boolean
  is_system?: boolean
  created_at: string
}

export interface EmailLog {
  id: number
  customer_id: number | null
  template_id: number | null
  recipient_email: string | null
  email_type: string
  subject: string
  body: string
  status: string
  queue_status: string
  error_message: string | null
  retry_count: number
  created_at: string
}

export interface EmailLogStats {
  total: number
  sent: number
  dev_mode: number
  failed: number
  queued: number
  processing: number
}

export interface EmailSendPayload {
  email_type?: string
  recipient_email: string
  template_id?: number | null
  subject?: string | null
  body?: string | null
  context?: Record<string, string>
  customer_id?: number | null
  cc_emails?: string[] | null
}

export type BulkEmailMode =
  | 'all_customers'
  | 'all_leads'
  | 'customers_by_status'
  | 'customers_by_segment'
  | 'select_customers'
  | 'manual_emails'

export interface EmailBulkPayload {
  email_type?: string
  template_id?: number | null
  subject?: string | null
  body?: string | null
  mode: BulkEmailMode
  filter_value?: string | null
  customer_ids?: number[]
  manual_emails?: string[]
  context?: Record<string, string>
}

export interface EmailBulkResult {
  mode: string
  attempted: number
  queued: number
  failed: number
  errors: string[]
}

export interface RenderedEmail {
  subject: string
  body: string
}

export interface EmailSettings {
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_use_tls: boolean
  smtp_mail_from: string
  smtp_password_set: boolean
  app_base_url: string
}

export type EmailSettingsUpdate = Partial<{
  smtp_host: string | null
  smtp_port: number
  smtp_username: string | null
  smtp_password: string | null
  smtp_use_tls: boolean
  smtp_mail_from: string | null
  app_base_url: string | null
}>

// ------------------------------------------------------------------ Documents / SOW
export interface SowSectionIn {
  title: string
  body: string
}

export interface Sow {
  id: number
  customer_id: number
  sow_title: string | null
  version: string
  status: string
  content_html: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface CustomerDocument {
  id: number
  customer_id: number
  original_filename: string
  storage_backend: string
  blob_url: string | null
  file_size_bytes: number | null
  mime_type: string | null
  description: string | null
  uploaded_by: string | null
  created_at: string
}

// ------------------------------------------------------------------ Diagrams
export interface Diagram {
  id: number
  customer_id: number
  diagram_name: string
  macro_key: string
  diagram_content: string
  aws_calculator_link: string | null
  is_active: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface DiagramGeneratePayload {
  customer_id: number
  diagram_name: string
  macro_key?: string
  title?: string | null
  entities?: string[]
  ai_generated?: string | null
  aws_calculator_link?: string | null
}

export interface DiagramSavePayload {
  customer_id: number
  diagram_name: string
  macro_key?: string
  diagram_content: string
  aws_calculator_link?: string | null
}

export interface DiagramUpdatePayload {
  diagram_name?: string
  diagram_content?: string
  aws_calculator_link?: string | null
  is_active?: boolean
}

// ------------------------------------------------------------------ Import
export interface ImportResult {
  entity: string
  created: number
  created_ids: number[]
  skipped: number
  updated: number
  errors: string[]
}

// ------------------------------------------------------------------ AI
export interface AiGeneratePayload {
  provider: 'openai' | 'gemini'
  prompt: string
  api_key: string
  model?: string
  max_tokens?: number
}

export interface AiResult {
  content: string
}

// ------------------------------------------------------------------ Meetings
export interface MeetingInvite {
  id: number
  customer_id: number
  customer_name: string | null
  recipient_email: string
  subject: string
  meeting_link: string
  agenda: string | null
  required_data: string | null
  scheduled_at: string | null
  created_by: string | null
  created_at: string
}

export interface MeetingInviteCreate {
  customer_id: number
  recipient_email?: string | null
  subject?: string | null
  meeting_link: string
  agenda?: string | null
  required_data?: string | null
  scheduled_at?: string | null
}

export interface MeetingAvailability {
  id: number
  token: string
  customer_id: number
  customer_name: string | null
  recipient_email: string
  subject: string
  option_1_at: string
  option_2_at: string
  option_3_at: string
  customer_option_1_at: string | null
  customer_option_2_at: string | null
  customer_option_3_at: string | null
  extra_recipients: string | null
  customer_note: string | null
  customer_submitted_at: string | null
  selected_option: number | null
  selected_at: string | null
  expires_at: string | null
  status: string
  created_by: string | null
  created_at: string
}

export interface MeetingAvailabilityCreate {
  customer_id: number
  recipient_email?: string | null
  subject?: string | null
  option_1_at: string
  option_2_at: string
  option_3_at: string
  expires_days?: number
}

export interface AvailabilityFormSubmit {
  option_1_at: string
  option_2_at: string
  option_3_at: string
extra_recipients?: string | null
  customer_note?: string | null
}

// ------------------------------------------------------------------ Configuration
export interface ConfigLookup {
  id: number
  name: string
  color?: string
  is_active?: boolean
}

export interface SegmentConfig extends ConfigLookup {
  credit_percentage: number | null
  credit_on_arr: boolean
  credit_percentage_customer: number | null
  credit_percentage_ambifo: number | null
  credit_basis_mrr: boolean
  credit_basis_arr: boolean
}

export interface TeamsConfig { webhook_url: string; enabled: boolean }
export interface StorageConfig { backend: string; docs_dir: string; max_upload_mb: number; onedrive_folder_link: string }
export interface AppUrlConfig { base_url: string }
export interface AIConfig { provider: string; model: string; api_key_set: boolean; max_tokens: number }
export interface MeetingAvailabilityConfig { default_duration_min: number; default_expiry_days: number }
export interface DocusignConfig {
  integration_key: string
  account_id: string
  base_url: string
  private_key_set: boolean
  enabled: boolean
}
