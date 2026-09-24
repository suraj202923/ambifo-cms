import type {
  User,
  Customer,
  CustomerCreate,
  CustomerUpdate,
  CustomerStats,
  History,
  Lead,
  LeadCreate,
  LeadUpdate,
  LeadStats,
  DashboardData,
  Lookups,
  Financial,
  EmailTemplate,
  EmailLog,
  EmailLogStats,
  EmailSendPayload,
  EmailBulkPayload,
  EmailBulkResult,
  RenderedEmail,
  Sow,
  SowSectionIn,
  CustomerDocument,
  Diagram,
  DiagramGeneratePayload,
  DiagramSavePayload,
DiagramUpdatePayload,
  ImportResult,
  AiGeneratePayload,
  AiResult,
  AdminUserCreate,
  AdminUserUpdate,
  MeetingInvite,
  MeetingInviteCreate,
MeetingAvailability,
  MeetingAvailabilityCreate,
  AvailabilityFormSubmit,
  EmailSettings,
  EmailSettingsUpdate,
  ConfigLookup,
  SegmentConfig,
  TeamsConfig,
  StorageConfig,
  AppUrlConfig,
  AIConfig,
  MeetingAvailabilityConfig,
  DocusignConfig,
} from './types'
import { api, getToken } from './client'

export const authApi = {
  login: (username: string, password: string) =>
    api<{ access_token: string; token_type: string }>('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    }),
  me: () => api<User>('/api/auth/me'),
}

export const adminApi = {
  users: () => api<User[]>('/api/admin/users'),
  createUser: (payload: AdminUserCreate) =>
    api<User>('/api/admin/users', { method: 'POST', body: payload }),
  updateUser: (id: number, payload: AdminUserUpdate) =>
    api<User>(`/api/admin/users/${id}`, { method: 'PUT', body: payload }),
  deleteUser: (id: number) => api<void>(`/api/admin/users/${id}`, { method: 'DELETE' }),
  resetAllPasswords: (newPassword: string) =>
    api<{ updated: number; updated_at: string }>('/api/admin/users/reset-all-passwords', {
      method: 'POST',
      body: { new_password: newPassword },
    }),
}

export const customerApi = {
  list: (params?: Record<string, string | number | undefined>) => {
    const qs = params
      ? '?' + new URLSearchParams(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return api<Customer[]>(`/api/customers${qs}`)
  },
  get: (id: number) => api<Customer>(`/api/customers/${id}`),
  create: (payload: CustomerCreate) =>
    api<Customer>('/api/customers', { method: 'POST', body: payload }),
  update: (id: number, payload: CustomerUpdate) =>
    api<Customer>(`/api/customers/${id}`, { method: 'PUT', body: payload }),
  remove: (id: number) => api<void>(`/api/customers/${id}`, { method: 'DELETE' }),
  removeAll: () => api<{ deleted: number }>('/api/customers', { method: 'DELETE' }),
  history: (id: number) => api<History[]>(`/api/customers/${id}/history`),
  addHistory: (id: number, payload: { action: string; tag_name?: string | null; changes_summary: string; remark?: string | null }) =>
    api<History>(`/api/customers/${id}/history`, { method: 'POST', body: payload }),
financials: (id: number) => api<Financial>(`/api/customers/${id}/financials`),
  updateFinancials: (id: number, payload: Partial<Financial>) =>
    api<Financial>(`/api/customers/${id}/financials`, { method: 'PUT', body: payload }),
  bulkUpdate: (payload: { customer_ids?: number[]; filter_search?: string | null; filter_segment?: string | null; filter_deal_status?: string | null; deal_status?: string | null; segment?: string | null; assign_to_user_id?: number | null }) =>
    api<{ updated: number }>('/api/customers/bulk/update', { method: 'POST', body: payload }),
  stats: (search?: string) => {
    const qs = search && search.trim() ? `?search=${encodeURIComponent(search.trim())}` : ''
    return api<CustomerStats>(`/api/customers/stats${qs}`)
  },
  lookups: () => api<Lookups>('/api/lookups'),
}

export const leadApi = {
  list: (params?: Record<string, string | number | undefined>) => {
    const qs = params
      ? '?' + new URLSearchParams(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return api<Lead[]>(`/api/leads${qs}`)
  },
  create: (payload: LeadCreate) => api<Lead>('/api/leads', { method: 'POST', body: payload }),
  stats: (search?: string) => {
    const qs = search && search.trim() ? `?search=${encodeURIComponent(search.trim())}` : ''
    return api<LeadStats>(`/api/leads/stats${qs}`)
  },
  get: (id: number) => api<Lead>(`/api/leads/${id}`),
  update: (id: number, payload: LeadUpdate) =>
    api<Lead>(`/api/leads/${id}`, { method: 'PUT', body: payload }),
remove: (id: number) => api<void>(`/api/leads/${id}`, { method: 'DELETE' }),
  convert: (id: number) =>
    api<CustomerCreate>(`/api/leads/${id}/convert`, { method: 'POST', body: {} }),
}

export const dashboardApi = {
  get: () => api<DashboardData>('/api/dashboard'),
}

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export const emailApi = {
  templates: () => api<EmailTemplate[]>('/api/email/templates'),
  createTemplate: (payload: Partial<EmailTemplate>) =>
    api<EmailTemplate>('/api/email/templates', { method: 'POST', body: payload }),
  updateTemplate: (id: number, payload: Partial<EmailTemplate>) =>
    api<EmailTemplate>(`/api/email/templates/${id}`, { method: 'PUT', body: payload }),
  deleteTemplate: (id: number) => api<void>(`/api/email/templates/${id}`, { method: 'DELETE' }),
  removeAllTemplates: () => api<{ deleted: number }>('/api/email/templates', { method: 'DELETE' }),
  render: (payload: EmailSendPayload) =>
    api<RenderedEmail>('/api/email/render', { method: 'POST', body: payload }),
  send: (payload: EmailSendPayload) =>
    api<EmailLog>('/api/email/send', { method: 'POST', body: payload }),
  logs: (params?: { customerId?: number; status?: string; q?: string; page?: number; page_size?: number }) => {
    const query = new URLSearchParams()
    if (params?.customerId != null) query.set('customer_id', String(params.customerId))
    if (params?.status) query.set('status', params.status)
    if (params?.q) query.set('q', params.q)
    if (params?.page != null) query.set('page', String(params.page))
    if (params?.page_size != null) query.set('page_size', String(params.page_size))
    const qs = query.toString()
    return api<{ items: EmailLog[]; total: number; page: number; page_size: number }>(
      qs ? `/api/email/logs?${qs}` : '/api/email/logs'
    )
  },
  stats: () => api<EmailLogStats>('/api/email/stats'),
  retryLog: (logId: number) =>
    api<EmailLog>(`/api/email/logs/${logId}/retry`, { method: 'POST', body: {} }),
  resendLog: (logId: number) =>
    api<EmailLog>(`/api/email/logs/${logId}/resend`, { method: 'POST', body: {} }),
  bulk: (payload: EmailBulkPayload) =>
    api<EmailBulkResult>('/api/email/bulk', { method: 'POST', body: payload }),
  retryFailed: () =>
    api<EmailBulkResult>('/api/email/bulk/retry-failed', { method: 'POST', body: {} }),
  settings: () => api<EmailSettings>('/api/email/settings'),
  updateSettings: (payload: EmailSettingsUpdate) =>
    api<EmailSettings>('/api/email/settings', { method: 'PUT', body: payload }),
  testSmtp: (toEmail: string) =>
    api<{ ok: boolean; status: string; error: string | null }>('/api/email/settings/test', { method: 'POST', body: { to_email: toEmail } }),
  unsubscribed: () =>
    api<{ items: { id: number; email: string; source: string | null; unsubscribed_at: string }[]; total: number }>('/api/email/unsubscribed'),
  csvSample: (templateId: number) => {
    const token = getToken()
    return fetch(`${API_BASE}/api/email/templates/${templateId}/csv-sample`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(r => r.blob())
  },
  bulkCsv: async (file: File, templateId: number) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('template_id', String(templateId))
    const token = getToken()
    const resp = await fetch(`${API_BASE}/api/email/bulk/csv`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => null)
      throw new Error(typeof data?.detail === 'string' ? data.detail : `CSV upload failed (${resp.status})`)
    }
    return resp.json() as Promise<{ execution_id: number; total_rows: number; valid_rows: number; invalid_rows: number; queued: number; errors: string[] }>
  },
}

export const documentApi = {
  sowGenerate: (payload: { customer_id: number; sow_title?: string; company?: string | null; sections: SowSectionIn[] }) =>
    api<Sow>('/api/documents/sow/generate', { method: 'POST', body: payload }),
  sows: (customerId?: number) =>
    api<Sow[]>(customerId ? `/api/documents/sows?customer_id=${customerId}` : '/api/documents/sows'),
  getSow: (id: number) => api<Sow>(`/api/documents/sows/${id}`),
  deleteSow: (id: number) => api<void>(`/api/documents/sows/${id}`, { method: 'DELETE' }),
  downloadSow: async (id: number): Promise<Blob> => {
    const resp = await fetch(`${API_BASE}/api/documents/sows/${id}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`Download failed (${resp.status})`)
    return resp.blob()
  },
  sendSowEmail: (id: number, recipientEmail?: string) => {
    const qs = recipientEmail ? `?recipient_email=${encodeURIComponent(recipientEmail)}` : ''
    return api<Sow>(`/api/documents/sows/${id}/send${qs}`, { method: 'POST', body: {} })
  },
  list: (customerId?: number) =>
    api<CustomerDocument[]>(customerId ? `/api/documents?customer_id=${customerId}` : '/api/documents'),
upload: async (customerId: number, file: File, description?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    const qs = new URLSearchParams({ customer_id: String(customerId) })
    if (description) qs.set('description', description)
    const resp = await fetch(`${API_BASE}/api/documents?${qs}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => null)
      throw new Error(typeof data?.detail === 'string' ? data.detail : `Upload failed (${resp.status})`)
    }
    return resp.json() as Promise<CustomerDocument>
  },
  generateBom: async (customerId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const qs = new URLSearchParams({ customer_id: String(customerId) })
    const resp = await fetch(`${API_BASE}/api/documents/bom/generate?${qs}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => null)
      throw new Error(typeof data?.detail === 'string' ? data.detail : `BOM generation failed (${resp.status})`)
    }
    return resp.json() as Promise<CustomerDocument>
  },
  download: async (id: number): Promise<Blob> => {
    const resp = await fetch(`${API_BASE}/api/documents/${id}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`Download failed (${resp.status})`)
    return resp.blob()
  },
  remove: (id: number) => api<void>(`/api/documents/${id}`, { method: 'DELETE' }),
  awsImport: async (customerId: number, link: string) => {
    const qs = new URLSearchParams({ customer_id: String(customerId), aws_calculator_link: link })
    const token = getToken()
    const resp = await fetch(`${API_BASE}/api/documents/aws-import?${qs}`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => null)
      throw new Error(typeof data?.detail === 'string' ? data.detail : `AWS import failed (${resp.status})`)
    }
    return resp.json() as Promise<{ customer_id: number; aws_calculator_link: string | null; files_imported: string[]; bom_generated: boolean; bom_filename: string | null }>
  },
}

export const importApi = {
  excelCustomers: (url: string, updateExisting: boolean) =>
    api<ImportResult>('/api/import/excel-customers', {
      method: 'POST',
      body: { url, update_existing: updateExisting },
    }),
  excelFile: async (file: File, updateExisting: boolean) => {
    const fd = new FormData()
    fd.append('file', file)
    const token = getToken()
    const resp = await fetch(`${API_BASE}/api/import/customers/excel?update_existing=${updateExisting}`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => null)
      throw new Error(typeof data?.detail === 'string' ? data.detail : `Import failed (${resp.status})`)
    }
    return resp.json() as Promise<ImportResult>
  },
}

export const diagramApi = {
  generate: (payload: DiagramGeneratePayload) =>
    api<Diagram>('/api/diagrams/generate', { method: 'POST', body: payload }),
  save: (payload: DiagramSavePayload) =>
    api<Diagram>('/api/diagrams/save', { method: 'POST', body: payload }),
  update: (id: number, payload: DiagramUpdatePayload) =>
    api<Diagram>(`/api/diagrams/${id}`, { method: 'PUT', body: payload }),
  list: (customerId?: number) =>
    api<Diagram[]>(customerId ? `/api/diagrams?customer_id=${customerId}` : '/api/diagrams'),
  get: (id: number) => api<Diagram>(`/api/diagrams/${id}`),
  remove: (id: number) => api<void>(`/api/diagrams/${id}`, { method: 'DELETE' }),
}

export const aiApi = {
  generate: (payload: AiGeneratePayload) =>
    api<AiResult>('/api/ai/generate', { method: 'POST', body: payload }),
}

export const meetingApi = {
  invites: () => api<MeetingInvite[]>('/api/meetings/invites'),
  createInvite: (payload: MeetingInviteCreate) =>
    api<MeetingInvite>('/api/meetings/invites', { method: 'POST', body: payload }),
  getInvite: (id: number) => api<MeetingInvite>(`/api/meetings/invites/${id}`),
  deleteInvite: (id: number) => api<void>(`/api/meetings/invites/${id}`, { method: 'DELETE' }),
  availabilityList: () => api<MeetingAvailability[]>('/api/meetings/availability'),
  createAvailability: (payload: MeetingAvailabilityCreate) =>
    api<MeetingAvailability>('/api/meetings/availability', { method: 'POST', body: payload }),
  getAvailability: (id: number) => api<MeetingAvailability>(`/api/meetings/availability/${id}`),
}

export const publicMeetingApi = {
  getAvailability: (token: string) =>
    api<MeetingAvailability>(`/api/public/meetings/availability/${token}`),
  select: (token: string, option: 1 | 2 | 3) =>
    api<MeetingAvailability>(`/api/public/meetings/availability/${token}/select`, {
      method: 'POST',
      body: { option },
    }),
  form: (token: string, payload: AvailabilityFormSubmit) =>
    api<MeetingAvailability>(`/api/public/meetings/availability/${token}/form`, {
      method: 'POST',
      body: payload,
    }),
}

export const configApi = {
  // Lookup: deal statuses
  statuses: () => api<ConfigLookup[]>('/api/config/statuses'),
  createStatus: (payload: { name: string; color: string }) =>
    api<ConfigLookup>('/api/config/statuses', { method: 'POST', body: payload }),
  updateStatus: (id: number, payload: { name: string; color: string }) =>
    api<ConfigLookup>(`/api/config/statuses/${id}`, { method: 'PUT', body: payload }),
  deleteStatus: (id: number) => api<void>(`/api/config/statuses/${id}`, { method: 'DELETE' }),

  // Lookup: segments
  segments: () => api<SegmentConfig[]>('/api/config/segments'),
  createSegment: (payload: Partial<SegmentConfig>) => api<SegmentConfig>('/api/config/segments', { method: 'POST', body: payload }),
  updateSegment: (id: number, payload: Partial<SegmentConfig>) => api<SegmentConfig>(`/api/config/segments/${id}`, { method: 'PUT', body: payload }),
  deleteSegment: (id: number) => api<void>(`/api/config/segments/${id}`, { method: 'DELETE' }),

  // Lookup: cloud operators
  cloudOperators: () => api<ConfigLookup[]>('/api/config/cloud-operators'),
  createCloudOperator: (payload: { name: string }) => api<ConfigLookup>('/api/config/cloud-operators', { method: 'POST', body: payload }),
  updateCloudOperator: (id: number, payload: { name: string }) => api<ConfigLookup>(`/api/config/cloud-operators/${id}`, { method: 'PUT', body: payload }),
  deleteCloudOperator: (id: number) => api<void>(`/api/config/cloud-operators/${id}`, { method: 'DELETE' }),

  // Lookup: update tags
  updateTags: () => api<ConfigLookup[]>('/api/config/update-tags'),
  createUpdateTag: (payload: { name: string; color: string }) => api<ConfigLookup>('/api/config/update-tags', { method: 'POST', body: payload }),
  updateUpdateTag: (id: number, payload: { name: string; color: string }) => api<ConfigLookup>(`/api/config/update-tags/${id}`, { method: 'PUT', body: payload }),
  deleteUpdateTag: (id: number) => api<void>(`/api/config/update-tags/${id}`, { method: 'DELETE' }),

  // Teams
  teams: () => api<TeamsConfig>('/api/config/teams'),
  updateTeams: (payload: Partial<TeamsConfig>) => api<TeamsConfig>('/api/config/teams', { method: 'PUT', body: payload }),

  // Storage
  storage: () => api<StorageConfig>('/api/config/storage'),
  updateStorage: (payload: Partial<StorageConfig>) => api<StorageConfig>('/api/config/storage', { method: 'PUT', body: payload }),

  // Application URL
  appUrl: () => api<AppUrlConfig>('/api/config/app-url'),
  updateAppUrl: (payload: Partial<AppUrlConfig>) => api<AppUrlConfig>('/api/config/app-url', { method: 'PUT', body: payload }),

  // AI
  ai: () => api<AIConfig>('/api/config/ai'),
  updateAi: (payload: Partial<AIConfig> & { api_key?: string }) => api<AIConfig>('/api/config/ai', { method: 'PUT', body: payload }),

  // Meeting availability
  meetingAvailability: () => api<MeetingAvailabilityConfig>('/api/config/meeting-availability'),
  updateMeetingAvailability: (payload: Partial<MeetingAvailabilityConfig>) =>
    api<MeetingAvailabilityConfig>('/api/config/meeting-availability', { method: 'PUT', body: payload }),

  // DocuSign
  docusign: () => api<DocusignConfig>('/api/config/docusign'),
  updateDocusign: (payload: Partial<DocusignConfig> & { private_key?: string }) => api<DocusignConfig>('/api/config/docusign', { method: 'PUT', body: payload }),

  // Restart
  restart: () => api<{ status: string; started_at: string }>('/api/config/restart', { method: 'POST', body: {} }),
}
