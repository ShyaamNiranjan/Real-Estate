# Scrollwalk web (Next.js)

The Scrollwalk frontend: marketing landing and waitlist, sign-in screens, and the Studio. All data comes from the FastAPI backend in `../backend` through `/api`, which `next.config.ts` rewrites to `API_ORIGIN` (default `http://localhost:8000`).

```powershell
npm install
npm run dev          # http://localhost:3000 (the backend allows writes from this origin only)
npm run build        # production build
npm run typecheck    # route types + tsc
npm run lint
npm run api:generate # regenerate lib/api/schema.d.ts from ../docs/api/openapi.json
npm run api:check    # fail if the generated client is out of date
```

- `lib/api/client.ts`: typed `openapi-fetch` client; adds `X-CSRF-Token` to every write.
- `lib/api/errors.ts`: `ApiError` from `{ error: { code, message, fields } }`, and `unwrap()`.
- `lib/api/waitlist.ts`: `POST /api/v1/waitlist` for the landing and `/waitlist` forms.
- `lib/session.tsx`: `GET /auth/me` on load, sign-in and sign-out state.
