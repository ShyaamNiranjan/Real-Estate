import type { NextConfig } from 'next'

/** Where FastAPI listens. Not a secret: the browser never sees it, it only talks to `/api` on this origin. */
const API_ORIGIN = process.env.API_ORIGIN ?? 'http://localhost:8000'

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The repo root has its own lockfile (the Vite prototype); this app is self-contained.
  turbopack: { root: __dirname },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_ORIGIN}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
