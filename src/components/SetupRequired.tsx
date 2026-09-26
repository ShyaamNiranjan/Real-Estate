export function SetupRequired() {
  return (
    <div className="page page--empty">
      <div className="empty">
        <p className="eyebrow">Configuration</p>
        <h1 className="empty__title">Connect a Supabase project to continue.</h1>
        <p className="empty__body">
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in your environment
          (see <code>.env.example</code>), then rebuild. The README covers self-hosting in full.
        </p>
      </div>
    </div>
  )
}
