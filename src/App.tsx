import { useEffect, useState } from 'react'
import { VideoScroll } from './components/VideoScroll'
import { MobileScroll } from './components/MobileScroll'
import { Site } from './components/Site'
import './App.css'

function useIsMobileScroll() {
  const [mobile, setMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(max-width: 900px) and (orientation: portrait)').matches
  })

  useEffect(() => {
    const sync = () => {
      const narrow = window.matchMedia('(max-width: 900px)').matches
      const tall = window.innerHeight >= window.innerWidth
      setMobile(narrow && tall)
    }
    sync()
    const mq = window.matchMedia('(max-width: 900px)')
    const mo = window.matchMedia('(orientation: portrait)')
    mq.addEventListener('change', sync)
    mo.addEventListener('change', sync)
    return () => {
      mq.removeEventListener('change', sync)
      mo.removeEventListener('change', sync)
    }
  }, [])

  return mobile
}

export default function App() {
  const mobile = useIsMobileScroll()

  return (
    <div className="app">
      {mobile ? <MobileScroll /> : <VideoScroll />}
      <Site />
    </div>
  )
}
