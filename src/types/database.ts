export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[]

export type ListingStatus = 'draft' | 'preview' | 'published'
export type ExperienceType = 'immersive' | 'photo'
export type MediaKind = 'cover' | 'gallery' | 'video' | 'frame_sequence'
export type MediaAspect = 'landscape' | 'portrait' | 'square'
export type SectionPreset = 'hero' | 'tiles' | 'text' | 'gallery' | 'specs' | 'cta' | 'custom'
export type SectionLayout = 'default' | 'tiles' | 'split' | 'full'
export type EnquiryStatus = 'new' | 'read' | 'closed'
export type ProfileRole = 'admin' | 'member'

type Table<Row, Required extends keyof Row = never> = {
  Row: Row
  Insert: Partial<Row> & Pick<Row, Required>
  Update: Partial<Row>
  Relationships: []
}

export type ProfileRow = {
  id: string
  email: string | null
  full_name: string | null
  role: ProfileRole
  created_at: string
  updated_at: string
}

export type SiteSettingsRow = {
  id: string
  brand_name: string
  tagline: string | null
  logo_url: string | null
  primary_color: string
  accent_color: string
  background_color: string
  contact_email: string | null
  contact_phone: string | null
  socials: Json
  hero_headline: string | null
  hero_body: string | null
  hero_image_url: string | null
  hero_cta_label: string | null
  footer_note: string | null
  updated_at: string
}

export type ListingRow = {
  id: string
  slug: string
  title: string
  subtitle: string | null
  summary: string | null
  status: ListingStatus
  experience_type: ExperienceType
  experience: Json
  cover_image_url: string | null
  price_label: string | null
  location: string | null
  bedrooms: number | null
  bathrooms: number | null
  area_sqft: number | null
  sort_order: number
  published_at: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type ListingMediaRow = {
  id: string
  listing_id: string
  kind: MediaKind
  storage_path: string | null
  public_url: string | null
  label: string | null
  aspect: MediaAspect | null
  frame_count: number | null
  frame_pattern: string | null
  sort_order: number
  metadata: Json
  created_at: string
}

export type PageSectionRow = {
  id: string
  listing_id: string
  preset: SectionPreset
  title: string | null
  body: string | null
  layout: SectionLayout
  style: Json
  content: Json
  sort_order: number
  is_visible: boolean
  created_at: string
  updated_at: string
}

export type EnquiryRow = {
  id: string
  listing_id: string | null
  name: string
  email: string
  phone: string | null
  message: string | null
  status: EnquiryStatus
  created_at: string
}

export type Database = {
  public: {
    Tables: {
      profiles: Table<ProfileRow, 'id'>
      site_settings: Table<SiteSettingsRow>
      listings: Table<ListingRow, 'slug' | 'title'>
      listing_media: Table<ListingMediaRow, 'listing_id' | 'kind'>
      page_sections: Table<PageSectionRow, 'listing_id' | 'preset'>
      enquiries: Table<EnquiryRow, 'name' | 'email'>
    }
    Views: { [_ in never]: never }
    Functions: {
      is_admin: { Args: Record<string, never>; Returns: boolean }
    }
    Enums: { [_ in never]: never }
    CompositeTypes: { [_ in never]: never }
  }
}
