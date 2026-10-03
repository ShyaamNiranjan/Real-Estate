import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate, Outlet, ScrollRestoration, useLocation, useParams } from 'react-router-dom'
import { useRealtor } from './lib/realtor'
import { ListingPage } from './public/ListingPage'
import { Marketplace } from './public/Marketplace'
import { NotFound } from './public/NotFound'
import { PropertiesPage } from './public/PropertiesPage'
import { Landing } from './ye/Landing'
import { Signup } from './ye/Signup'

const AdminApp = lazy(() => import('./admin/AdminApp'))

function Root() {
  return (
    <>
      <ScrollRestoration getKey={(location) => location.pathname} />
      <Outlet />
    </>
  )
}

/** One workspace exists in the prototype; any other realtor slug is a 404. */
function RealtorGate() {
  const { realtor } = useParams()
  const { slug, ready } = useRealtor()
  if (!ready) return <div className="page page--loading" aria-busy />
  if (realtor !== slug) return <NotFound title="No realtor lives at this address." body="Check the link, or start your own site on YE." href="/" cta="Go to YE" />
  return <Outlet />
}

function LegacyListing() {
  const { slug = '' } = useParams()
  const { listing, ready } = useRealtor()
  if (!ready) return <div className="page page--loading" aria-busy />
  return <Navigate to={listing(slug)} replace />
}

function LegacyStudio() {
  const { pathname } = useLocation()
  return <Navigate to={pathname.replace(/^\/admin/, '/studio')} replace />
}

export const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: '/', element: <Landing /> },
      { path: '/signup', element: <Signup /> },
      { path: '/listing/:slug', element: <LegacyListing /> },
      { path: '/admin/*', element: <LegacyStudio /> },
      {
        path: '/studio/*',
        element: (
          <Suspense fallback={<div className="admin-boot" aria-busy />}>
            <AdminApp />
          </Suspense>
        ),
      },
      {
        path: '/:realtor',
        element: <RealtorGate />,
        children: [
          { index: true, element: <Marketplace /> },
          { path: 'properties', element: <PropertiesPage /> },
          { path: ':slug', element: <ListingPage /> },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
])
