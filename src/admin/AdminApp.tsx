import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { AdminLayout } from './AdminLayout'
import { Dashboard } from './Dashboard'
import { Enquiries } from './Enquiries'
import { ListingEditor } from './ListingEditor'
import { Login } from './Login'
import { NewListing } from './NewListing'
import { Settings } from './Settings'
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
  if (!session) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
  if (!isAdmin)
    return (
      <div className="a-auth">
        <div className="a-auth__panel">
          <p className="a-auth__brand">Access restricted</p>
          <h1 className="a-auth__title">This account is not an administrator.</h1>
          <p className="a-auth__body">
            Signed in as {profile?.email ?? session.user.email}. Ask the owner to grant the admin role in Supabase.
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
            <Route index element={<Dashboard />} />
            <Route path="listings/new" element={<NewListing />} />
            <Route path="listings/:id" element={<ListingEditor />} />
            <Route path="listings/:id/:tab" element={<ListingEditor />} />
            <Route path="enquiries" element={<Enquiries />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/admin" replace />} />
          </Route>
        </Routes>
      </div>
    </ToastProvider>
  )
}
