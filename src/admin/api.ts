import { BUCKETS, supabase } from '../lib/supabase'
import type { Database, EnquiryRow, EnquiryStatus, ListingMediaRow, ListingRow, PageSectionRow, SiteSettingsRow } from '../types/database'

type Tables = Database['public']['Tables']
export type ListingInsert = Tables['listings']['Insert']
export type ListingUpdate = Tables['listings']['Update']
export type MediaInsert = Tables['listing_media']['Insert']
export type MediaUpdate = Tables['listing_media']['Update']
export type SectionInsert = Tables['page_sections']['Insert']
export type SectionUpdate = Tables['page_sections']['Update']
export type SettingsUpdate = Tables['site_settings']['Update']

function unwrap<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(res.error.message)
  return res.data as T
}

// Listings -------------------------------------------------------------------

export async function listListings(): Promise<ListingRow[]> {
  return unwrap(
    await supabase.from('listings').select('*').order('sort_order', { ascending: true }).order('created_at', { ascending: false }),
  )
}

export async function getListing(id: string): Promise<ListingRow> {
  return unwrap(await supabase.from('listings').select('*').eq('id', id).single())
}

export async function createListing(input: ListingInsert): Promise<ListingRow> {
  return unwrap(await supabase.from('listings').insert(input).select('*').single())
}

export async function updateListing(id: string, patch: ListingUpdate): Promise<ListingRow> {
  return unwrap(await supabase.from('listings').update(patch).eq('id', id).select('*').single())
}

export async function deleteListing(id: string) {
  const media = await listMedia(id)
  await removeStorageObjects(media)
  unwrap(await supabase.from('listings').delete().eq('id', id))
}

export async function isSlugTaken(slug: string, exceptId?: string) {
  let q = supabase.from('listings').select('id').eq('slug', slug)
  if (exceptId) q = q.neq('id', exceptId)
  const rows = unwrap(await q)
  return rows.length > 0
}

// Media ----------------------------------------------------------------------

export async function listMedia(listingId: string): Promise<ListingMediaRow[]> {
  return unwrap(
    await supabase.from('listing_media').select('*').eq('listing_id', listingId).order('sort_order', { ascending: true }),
  )
}

export async function createMedia(input: MediaInsert): Promise<ListingMediaRow> {
  return unwrap(await supabase.from('listing_media').insert(input).select('*').single())
}

export async function updateMedia(id: string, patch: MediaUpdate): Promise<ListingMediaRow> {
  return unwrap(await supabase.from('listing_media').update(patch).eq('id', id).select('*').single())
}

export async function deleteMedia(media: ListingMediaRow) {
  await removeStorageObjects([media])
  unwrap(await supabase.from('listing_media').delete().eq('id', media.id))
}

export async function reorderRows(table: 'listing_media' | 'page_sections', ids: string[]) {
  await Promise.all(
    ids.map(async (id, index) => unwrap(await supabase.from(table).update({ sort_order: index }).eq('id', id))),
  )
}

/** Uploaded frame sequences store a folder prefix in storage_path; single files store the object path. */
async function removeStorageObjects(media: ListingMediaRow[]) {
  for (const m of media) {
    if (!m.storage_path) continue
    try {
      if (m.kind === 'frame_sequence') {
        const { data } = await supabase.storage.from(BUCKETS.frames).list(m.storage_path, { limit: 1000 })
        const paths = (data ?? []).map((f) => `${m.storage_path}/${f.name}`)
        if (paths.length) await supabase.storage.from(BUCKETS.frames).remove(paths)
      } else {
        const bucket = m.kind === 'video' ? BUCKETS.videos : BUCKETS.images
        await supabase.storage.from(bucket).remove([m.storage_path])
      }
    } catch (err) {
      console.warn('Storage cleanup failed', err)
    }
  }
}

// Uploads --------------------------------------------------------------------

const MAX_IMAGE_BYTES = 20 * 1024 * 1024

function extension(file: File) {
  const fromName = file.name.split('.').pop()?.toLowerCase()
  if (fromName && /^[a-z0-9]{2,5}$/.test(fromName)) return fromName
  return file.type.split('/')[1] ?? 'bin'
}

export async function uploadImage(file: File, folder: string): Promise<{ path: string; url: string }> {
  if (!file.type.startsWith('image/')) throw new Error(`${file.name} is not an image`)
  if (file.size > MAX_IMAGE_BYTES) throw new Error(`${file.name} is larger than 20 MB`)
  const path = `${folder}/${crypto.randomUUID()}.${extension(file)}`
  unwrap(
    await supabase.storage.from(BUCKETS.images).upload(path, file, {
      cacheControl: '31536000',
      contentType: file.type,
      upsert: false,
    }),
  )
  const { data } = supabase.storage.from(BUCKETS.images).getPublicUrl(path)
  return { path, url: data.publicUrl }
}

/**
 * Uploads an ordered set of frames as frame-001.jpg … into listing-frames/<listing>/<sequence>/.
 * Files are sorted by name, so exported sequences (e.g. from ffmpeg) keep their order.
 */
export async function uploadFrameSequence(
  listingId: string,
  files: File[],
  onProgress: (done: number, total: number) => void,
): Promise<{ prefix: string; baseUrl: string; count: number; pattern: string }> {
  const sorted = [...files]
    .filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  if (!sorted.length) throw new Error('Choose JPG, PNG or WebP frames')
  if (sorted.length > 999) throw new Error('A sequence can have at most 999 frames')

  const ext = extension(sorted[0]) === 'jpeg' ? 'jpg' : extension(sorted[0])
  const prefix = `${listingId}/${crypto.randomUUID()}`
  const pattern = `frame-{###}.${ext}`
  let done = 0
  let cursor = 0
  const worker = async () => {
    while (cursor < sorted.length) {
      const i = cursor++
      const name = `frame-${String(i + 1).padStart(3, '0')}.${ext}`
      unwrap(
        await supabase.storage.from(BUCKETS.frames).upload(`${prefix}/${name}`, sorted[i], {
          cacheControl: '31536000',
          contentType: sorted[i].type,
          upsert: true,
        }),
      )
      done += 1
      onProgress(done, sorted.length)
    }
  }
  await Promise.all(Array.from({ length: 5 }, worker))
  const { data } = supabase.storage.from(BUCKETS.frames).getPublicUrl(prefix)
  return { prefix, baseUrl: data.publicUrl, count: sorted.length, pattern }
}

// Sections -------------------------------------------------------------------

export async function listSections(listingId: string): Promise<PageSectionRow[]> {
  return unwrap(
    await supabase.from('page_sections').select('*').eq('listing_id', listingId).order('sort_order', { ascending: true }),
  )
}

export async function createSection(input: SectionInsert): Promise<PageSectionRow> {
  return unwrap(await supabase.from('page_sections').insert(input).select('*').single())
}

export async function updateSection(id: string, patch: SectionUpdate): Promise<PageSectionRow> {
  return unwrap(await supabase.from('page_sections').update(patch).eq('id', id).select('*').single())
}

export async function deleteSection(id: string) {
  unwrap(await supabase.from('page_sections').delete().eq('id', id))
}

// Enquiries ------------------------------------------------------------------

export type EnquiryWithListing = EnquiryRow & { listings: { title: string; slug: string } | null }

export async function listEnquiries(): Promise<EnquiryWithListing[]> {
  const res = await supabase
    .from('enquiries')
    .select('*, listings(title, slug)')
    .order('created_at', { ascending: false })
    .limit(500)
  return unwrap(res) as unknown as EnquiryWithListing[]
}

export async function setEnquiryStatus(id: string, status: EnquiryStatus) {
  unwrap(await supabase.from('enquiries').update({ status }).eq('id', id))
}

export async function countNewEnquiries(): Promise<number> {
  const { count, error } = await supabase.from('enquiries').select('id', { count: 'exact', head: true }).eq('status', 'new')
  if (error) throw new Error(error.message)
  return count ?? 0
}

// Settings -------------------------------------------------------------------

export async function getSettings(): Promise<SiteSettingsRow | null> {
  return unwrap(await supabase.from('site_settings').select('*').limit(1).maybeSingle())
}

export async function saveSettings(id: string | null, patch: SettingsUpdate): Promise<SiteSettingsRow> {
  if (id) return unwrap(await supabase.from('site_settings').update(patch).eq('id', id).select('*').single())
  return unwrap(await supabase.from('site_settings').insert(patch).select('*').single())
}
