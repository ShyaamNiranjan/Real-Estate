// Prototype of the walkthrough worker: turns a phone video into stabilised WebP frame sets.
//
//   node scripts/process-walkthrough.mjs <video> <out-dir> --width 720 --frames 240
//
// Steps: quality check → stabilise (vidstab, 2 passes) → drop standing-still frames (mpdecimate)
// → sample evenly to the frame budget → WebP. Writes manifest.json with the frame set and report.
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const [input, outArg, ...rest] = process.argv.slice(2)
if (!input || !outArg) {
  console.error('usage: node scripts/process-walkthrough.mjs <video> <out-dir> [--width 720] [--frames 240] [--quality 82]')
  process.exit(1)
}
const flag = (name, fallback) => {
  const i = rest.indexOf(`--${name}`)
  return i >= 0 ? Number(rest[i + 1]) : fallback
}
const WIDTH = flag('width', 1280)
const FRAMES = flag('frames', 240)
const QUALITY = flag('quality', 82)

const src = resolve(input)
const out = resolve(outArg)
// vidstab's file arguments can't take Windows drive paths, so every pass runs inside a work dir.
const work = mkdtempSync(join(tmpdir(), 'ye-walk-'))

function run(cmd, args) {
  const r = spawnSync(cmd, args, { cwd: work, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.status !== 0) {
    console.error(r.stderr?.slice(-2000))
    throw new Error(`${cmd} failed`)
  }
  return r.stdout
}

function probe(file, entries) {
  const json = run('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', entries, '-of', 'json', file])
  return JSON.parse(json)
}

const t0 = Date.now()
const info = probe(src, 'stream=width,height,r_frame_rate,nb_read_frames:format=duration')
const stream = info.streams[0]
const [num, den] = stream.r_frame_rate.split('/').map(Number)
const fps = num / (den || 1)
const duration = Number(info.format.duration)
const sourceFrames = Number(stream.nb_read_frames)

// Pass 1: motion analysis (also the shake measurement) and average brightness.
run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-vf', 'vidstabdetect=shakiness=6:accuracy=15:fileformat=ascii:result=t.trf', '-f', 'null', '-'])
run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-vf', 'signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=y.txt', '-f', 'null', '-'])

function median(values) {
  const s = [...values].sort((a, b) => a - b)
  const mid = s.length >> 1
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/** Jitter: how far each frame's camera motion strays from its neighbours' average (px per frame). */
function measureShake() {
  const moves = []
  for (const line of readFileSync(join(work, 't.trf'), 'utf8').split('\n')) {
    if (!line.startsWith('Frame')) continue
    const fields = [...line.matchAll(/\(LM (-?\d+) (-?\d+)/g)]
    if (!fields.length) {
      moves.push([0, 0])
      continue
    }
    moves.push([median(fields.map((m) => Number(m[1]))), median(fields.map((m) => Number(m[2])))])
  }
  if (moves.length < 5) return 0
  let sum = 0
  for (let i = 2; i < moves.length - 2; i++) {
    const near = moves.slice(i - 2, i + 3)
    const ax = near.reduce((s, m) => s + m[0], 0) / near.length
    const ay = near.reduce((s, m) => s + m[1], 0) / near.length
    sum += Math.hypot(moves[i][0] - ax, moves[i][1] - ay)
  }
  return sum / (moves.length - 4)
}

const shake = measureShake()
const lumas = [...readFileSync(join(work, 'y.txt'), 'utf8').matchAll(/YAVG=([\d.]+)/g)].map((m) => Number(m[1]))
const brightness = lumas.reduce((s, v) => s + v, 0) / Math.max(1, lumas.length)

// Pass 2: stabilise, sharpen what the stabiliser's zoom softened, drop standing-still frames.
run('ffmpeg', [
  '-y', '-v', 'error', '-i', src,
  '-vf', 'vidstabtransform=input=t.trf:smoothing=24:zoom=4:optzoom=0:interpol=bicubic,unsharp=5:5:0.5:5:5:0,mpdecimate,setpts=N/FRAME_RATE/TB',
  '-an', '-c:v', 'libx264', '-crf', '12', '-preset', 'fast', 'stab.mp4',
])
const kept = Number(probe(join(work, 'stab.mp4'), 'stream=nb_read_frames').streams[0].nb_read_frames)
const target = Math.min(FRAMES, kept)

// Sample evenly down to the frame budget; never invent frames that weren't filmed.
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })
run('ffmpeg', [
  '-y', '-v', 'error', '-i', 'stab.mp4',
  '-vf', `fps=${target}/${(kept / fps).toFixed(4)},scale=${WIDTH}:-2:flags=lanczos`,
  '-frames:v', String(target),
  '-c:v', 'libwebp', '-quality', String(QUALITY), '-compression_level', '4',
  join(out, 'frame-%03d.webp'),
])

const files = readdirSync(out).filter((f) => f.endsWith('.webp'))
const first = probe(join(out, files[0]), 'stream=width,height').streams[0]
const bytes = files.reduce((s, f) => s + readFileSync(join(out, f)).length, 0)

const warnings = []
const shortSide = Math.min(stream.width, stream.height)
if (duration < 6) warnings.push('Video is shorter than 6 seconds; the walkthrough will feel abrupt.')
if (fps < 30) warnings.push(`Filmed at ${Math.round(fps)}fps; 60fps gives smoother motion.`)
if (shortSide < 1080) warnings.push(`Resolution is ${stream.width}×${stream.height}; film in 4K for sharp frames on large screens.`)
if (brightness < 60) warnings.push('Footage is dark; turn on the lights and film in daylight.')
if (shake > 1.5) warnings.push('Footage is shaky; use a gimbal or your phone\'s stabilised mode and walk slowly.')

const manifest = {
  pattern: 'frame-{###}.webp',
  frameCount: files.length,
  width: first.width,
  height: first.height,
  totalKB: Math.round(bytes / 1024),
  report: {
    source: { width: stream.width, height: stream.height, fps: Math.round(fps * 100) / 100, durationS: Math.round(duration * 10) / 10, frames: sourceFrames },
    stillFramesDropped: sourceFrames - kept,
    shakePxPerFrame: Math.round(shake * 100) / 100,
    brightness: Math.round(brightness),
    warnings,
    processedInS: Math.round((Date.now() - t0) / 100) / 10,
  },
}
writeFileSync(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2))
rmSync(work, { recursive: true, force: true })
console.log(JSON.stringify(manifest, null, 2))
