import { useEffect } from 'react'
import Lenis from 'lenis'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { VideoScroll } from './components/VideoScroll'
import { Site } from './components/Site'
import './App.css'

gsap.registerPlugin(ScrollTrigger)

export default function App() {
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.35,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -11 * t)),
      smoothWheel: true,
      syncTouch: false,
      wheelMultiplier: 0.55,
      touchMultiplier: 0.85,
      lerp: 0.075,
    })

    lenis.on('scroll', ScrollTrigger.update)

    const ticker = (time: number) => {
      lenis.raf(time * 1000)
    }
    gsap.ticker.add(ticker)
    gsap.ticker.lagSmoothing(0)

    return () => {
      gsap.ticker.remove(ticker)
      lenis.destroy()
    }
  }, [])

  return (
    <div className="app">
      <VideoScroll />
      <Site />
    </div>
  )
}
