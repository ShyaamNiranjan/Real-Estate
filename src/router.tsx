import { lazy, Suspense } from 'react'
import { createBrowserRouter, Outlet, ScrollRestoration } from 'react-router-dom'
import { ListingPage } from './public/ListingPage'
import { Marketplace } from './public/Marketplace'
import { NotFound } from './public/NotFound'

const AdminApp = lazy(() => import('./admin/AdminApp'))

function Root() {
  return (
    <>
      <ScrollRestoration getKey={(location) => location.pathname} />
      <Outlet />
    </>
  )
}

export const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: '/', element: <Marketplace /> },
      { path: '/listing/:slug', element: <ListingPage /> },
      {
        path: '/admin/*',
        element: (
          <Suspense fallback={<div className="admin-boot" aria-busy />}>
            <AdminApp />
          </Suspense>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
])
