import type { MediaAspect } from '../types/database'

export const VIDEO_PRESETS: Record<MediaAspect, { frames: number; width: number; quality: number }> = {
  landscape: { frames: 240, width: 1920, quality: 0.82 },
  portrait: { frames: 120, width: 900, quality: 0.8 },
  square: { frames: 180, width: 1280, quality: 0.82 },
}

function once(el: HTMLVideoElement, event: string) {
  return new Promise<void>((resolve, reject) => {
    const ok = () => {
      cleanup()
      resolve()
    }
    const fail = () => {
      cleanup()
      reject(new Error('This video could not be decoded by the browser. Try an H.264 MP4.'))
    }
    const cleanup = () => {
      el.removeEventListener(event, ok)
      el.removeEventListener('error', fail)
    }
    el.addEventListener(event, ok, { once: true })
    el.addEventListener('error', fail, { once: true })
  })
}

async function seek(video: HTMLVideoElement, time: number) {
  const done = once(video, 'seeked')
  video.currentTime = time
  await done
}

/** Some encoders write no duration into the header; seeking far past the end makes the browser compute it. */
async function resolveDuration(video: HTMLVideoElement) {
  if (Number.isFinite(video.duration) && video.duration > 0) return video.duration
  await seek(video, 1e7)
  const d = video.duration
  await seek(video, 0)
  if (!Number.isFinite(d) || d <= 0) throw new Error('Could not read the video length')
  return d
}

export type VideoInfo = { width: number; height: number; duration: number; aspect: MediaAspect }

export async function probeVideo(file: File): Promise<VideoInfo> {
  const url = URL.createObjectURL(file)
  const video = document.createElement('video')
  video.muted = true
  video.playsInline = true
  video.preload = 'auto'
  try {
    const ready = once(video, 'loadedmetadata')
    video.src = url
    await ready
    const duration = await resolveDuration(video)
    const { videoWidth: width, videoHeight: height } = video
    const ratio = width / height
    const aspect: MediaAspect = ratio > 1.1 ? 'landscape' : ratio < 0.9 ? 'portrait' : 'square'
    return { width, height, duration, aspect }
  } finally {
    video.removeAttribute('src')
    video.load()
    URL.revokeObjectURL(url)
  }
}

/**
 * Samples `count` evenly spaced frames from a local video file and returns them as JPG files
 * named frame-001.jpg… ready for uploadFrameSequence.
 */
export async function extractFrames(
  file: File,
  opts: { count: number; maxWidth: number; quality: number },
  onProgress: (done: number, total: number) => void,
  signal?: AbortSignal,
): Promise<File[]> {
  const url = URL.createObjectURL(file)
  const video = document.createElement('video')
  video.muted = true
  video.playsInline = true
  video.preload = 'auto'
  try {
    const ready = once(video, 'loadeddata')
    video.src = url
    await ready
    const duration = await resolveDuration(video)

    const scale = Math.min(1, opts.maxWidth / video.videoWidth)
    const width = Math.round(video.videoWidth * scale)
    const height = Math.round(video.videoHeight * scale)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas is not available in this browser')

    const count = Math.max(2, opts.count)
    const step = duration / count
    const frames: File[] = []
    for (let i = 0; i < count; i++) {
      if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
      await seek(video, Math.min(duration - 0.001, step * (i + 0.5)))
      ctx.drawImage(video, 0, 0, width, height)
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', opts.quality))
      if (!blob) throw new Error('Could not encode a frame')
      frames.push(new File([blob], `frame-${String(i + 1).padStart(3, '0')}.jpg`, { type: 'image/jpeg' }))
      onProgress(i + 1, count)
    }
    return frames
  } finally {
    video.removeAttribute('src')
    video.load()
    URL.revokeObjectURL(url)
  }
}
