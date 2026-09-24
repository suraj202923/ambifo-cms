import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { AuthProvider, useAuth } from './auth'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import LeadsPage from './pages/LeadsPage'
import EmailPage from './pages/EmailPage'
import DocumentsPage from './pages/DocumentsPage'
import DiagramsPage from './pages/DiagramsPage'
import AiPage from './pages/AiPage'
import AdminPage from './pages/AdminPage'
import MeetingsPage from './pages/MeetingsPage'
import ConfigurationPage from './pages/ConfigurationPage'
import PublicMeetingPage from './pages/PublicMeetingPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1 } },
})

function Protected() {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-brand-teal/20 border-t-brand-teal" />
          <span className="font-display text-sm font-semibold text-slate-500">Loading</span>
        </div>
      </div>
    )
  if (!user) return <Navigate to="/login" replace />
  return <Layout />
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (!user?.is_admin) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<Protected />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/customers" element={<CustomersPage />} />
              <Route path="/customers/:id" element={<CustomerDetailPage />} />
              <Route path="/leads" element={<LeadsPage />} />
              <Route path="/email" element={<EmailPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/diagrams" element={<DiagramsPage />} />
              <Route path="/ai" element={<AiPage />} />
              <Route path="/meetings" element={<MeetingsPage />} />
              <Route path="/configuration" element={<AdminOnly><ConfigurationPage /></AdminOnly>} />
              <Route path="/admin" element={<AdminOnly><AdminPage /></AdminOnly>} />
            </Route>
            <Route path="/public/meetings/:token" element={<PublicMeetingPage />} />
            <Route path="/public/meetings/:token/:action" element={<PublicMeetingPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}