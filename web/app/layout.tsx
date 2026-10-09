import type { Metadata, Viewport } from 'next'
import { Cormorant_Garamond, JetBrains_Mono, Manrope } from 'next/font/google'
import { SessionProvider } from '@/lib/session'
import './globals.css'
import '@/styles/ye.css'
import '@/styles/auth.css'

const body = Manrope({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-body-face',
  display: 'swap',
})

const display = Cormorant_Garamond({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  style: ['normal', 'italic'],
  variable: '--font-display-face',
  display: 'swap',
})

const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono-face',
  display: 'swap',
})

export const metadata: Metadata = {
  title: {
    default: 'Scrollwalk · Homes you can walk through',
    template: '%s · Scrollwalk',
  },
  description:
    'Scrollwalk turns a phone video into a scroll-controlled walkthrough on your own premium website. Homes you can walk through. Just scroll.',
  applicationName: 'Scrollwalk',
}

export const viewport: Viewport = {
  themeColor: '#0a0b0b',
  viewportFit: 'cover',
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable} ${mono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  )
}
