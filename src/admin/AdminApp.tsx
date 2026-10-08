import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { AdminLayout } from './AdminLayout'
import { AnalyticsPage } from './AnalyticsPage'
import { Dashboard } from './Dashboard'
import { Enquiries } from './Enquiries'
import { HomePage } from './HomePage'
import { ListingEditor } from './ListingEditor'
import { Login } from './Login'
import { NewListing } from './NewListing'
import { Overview } from './Overview'
import { PaidOnly, PlanPage } from './PlanPage'
import { Settings } from './Settings'
import { TeamPage } from './TeamPage'
import { Spinner, ToastProvider } from './ui'
import './admin.css'

function RequireAdmin({ children }: { children: ReactNode }) {
  const { session, isAdmin, loading, signOut, profile } = useAuth()
  const location = useLocation()

  if (loading)
    return (
      <div className="a-boot">
        <Spinner />
      </div>
    )
  if (!session) return <Navigate to="/studio/login" replace state={{ from: location.pathname }} />
  if (!isAdmin)
    return (
      <div className="a-auth">
        <div className="a-auth__panel">
          <p className="a-auth__brand">Access restricted</p>
          <h1 className="a-auth__title">This account has no workspace.</h1>
          <p className="a-auth__body">
            Signed in as {profile?.email ?? session.user.email}. Ask the workspace owner to invite you.
          </p>
          <button type="button" className="a-btn a-btn--primary" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </div>
    )
  return <>{children}</>
}

export default function AdminApp() {
  return (
    <ToastProvider>
      <div className="admin">
        <Routes>
          <Route path="login" element={<Login />} />
          <Route
            element={
              <RequireAdmin>
                <AdminLayout />
              </RequireAdmin>
            }
          >
            <Route index element={<Overview />} />
            <Route path="listings" element={<Dashboard />} />
            <Route path="listings/new" element={<NewListing />} />
            <Route path="listings/:id" element={<ListingEditor />} />
            <Route path="listings/:id/:tab" element={<ListingEditor />} />
            <Route
              path="home"
              element={
                <PaidOnly feature="Website" body="Choose your sections, order them and write your own words. Unlocks when you subscribe.">
                  <HomePage />
                </PaidOnly>
              }
            />
            <Route path="enquiries" element={<Enquiries />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route
              path="settings"
              element={
                <PaidOnly feature="Brand & contact" body="Your name, logo, colours, licence and contact details. Unlocks when you subscribe.">
                  <Settings />
                </PaidOnly>
              }
            />
            <Route path="team" element={<TeamPage />} />
            <Route path="plan" element={<PlanPage />} />
            <Route path="*" element={<Navigate to="/studio" replace />} />
          </Route>
        </Routes>
      </div>
    </ToastProvider>
  )
}
