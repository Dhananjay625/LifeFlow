This app can connect to Google for OAuth login and Calendar import.

## Enable APIs
- Google Calendar API (for event sync)

## Create OAuth credentials
- Go to Google *Cloud Console → APIs & Services → Credentials*
- Configure *OAuth consent screen* (External is fine for dev)
- *Create Credentials → OAuth client ID → Web application*
- Authorized redirect URIs:
    - Dev: `http://localhost:8000/google/oauth2/callback/`
    - Prod: `https://<your-domain>/google/oauth2/callback/`
- Copy Client ID and Client Secret into `.env`

## Scopes
Typical scopes used:
- *openid email profile (for login)*
- `https://www.googleapis.com/auth/calendar.readonly` (for calendar import)
