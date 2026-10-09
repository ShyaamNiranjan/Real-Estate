# API contract — frontend guide

`openapi.json` here is generated from the backend (`python -m app.openapi_export`) and a test fails if it drifts. Generate the typed client from it; never hand-write request or response types.

## Calling the API
- **Same origin.** Next.js proxies `/api/*` to FastAPI (rewrite in `next.config`), so the browser only ever talks to `scrollwalk.com`. Use `fetch('/api/v1/...', { credentials: 'include' })`. Locally FastAPI runs on `:8000`, Next.js on `:3000`.
- **JSON only.** Send `Content-Type: application/json`.
- **CSRF.** Every `POST`/`PUT`/`PATCH`/`DELETE` made while signed in must send header `X-CSRF-Token`. Read it from the `__Host-sw_csrf` cookie, or from `csrf_token` in `GET /auth/me`. Missing or wrong: `403 csrf_failed`.
- **Never** read, store or forward the session cookie (`__Host-sw_session` is HttpOnly anyway). No tokens in localStorage or sessionStorage.
- **Errors** always look like `{ "error": { "code": "...", "message": "...", "fields": { "password": "..." } } }`. Show `message` to the user; branch on `code`; `fields` only on `422 validation_error`.
- **Rate limits** answer `429 rate_limited`; show the message, don't retry automatically.

## Sign-in flows (docs/SCOPE.md 8.1)

| Screen | Call | Result |
|---|---|---|
| Sign up | `POST /auth/signup {email, password, display_name, accept_terms: true}` | Always `202` (even if the email exists: never tell the user). Go to the code screen. |
| Code screen | `POST /auth/verify {email, code}` | `200 Me` + cookies: signed in. `400 invalid_code` otherwise. |
| Resend (enable after 30 s) | `POST /auth/resend {email, purpose: "verify" \| "reset"}` | Always `202`. |
| Sign in | `POST /auth/login {email, password}` | `200 Me`; `401 invalid_credentials`; `403 email_not_verified` (a code was sent: go to the code screen). |
| Forgot password | `POST /auth/password/forgot {email}` | Always `202`. Go to the reset screen. |
| Reset | `POST /auth/password/reset {email, code, password}` | `200 Me`, signed in; all other devices signed out. |
| Google | Full-page navigation to `GET /api/v1/auth/google/start` | Returns to `/studio` signed in, or to `/login?error=google_failed \| google_cancelled \| google_unavailable`. |
| App load | `GET /auth/me` | `200 Me` or `401 not_signed_in`. |
| Sign out / everywhere | `POST /auth/logout`, `POST /auth/logout-all` | `204`. |
| Change email | `POST /auth/email/change {new_email, password}` then `POST /auth/email/confirm {code}` | `202`, then `200 Me`. `409 email_taken`. |

Code inputs: 6 digits, `inputmode="numeric"`, `autocomplete="one-time-code"`, with "Wrong email? Change it".
Passwords: 8–128 characters.
