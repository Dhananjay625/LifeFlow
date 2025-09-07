# README.md
A Django web app to manage Tasks, Subscriptions, Bills and a unified Calendar. Optional Google OAuth enables Google Calendar sync.

### Features
- Tasks: create, list, complete, archive; priorities & due dates
- Subscriptions: track renewal dates, names
- Bills: track renewal dates, names
- Calendar: month/day view; drag/resize/edit items
- Google OAuth (optional): connect your Google account; import upcoming events into Tasks
- Documents: upload & delete user documents

### Quickstart (macOS/Linux)
```
# 1) Clone & enter
git clone <REPO_URL>
cd LifeFlow

# 2) Python venv
python3 -m venv .venv && source .venv/bin/activate

# 3) Install 
pip install -r requirements.txt 

# 4) DB setup
python3 manage.py migrate

# 5) Run
python3 manage.py runserver `

### Quickstart (Windows PowerShell)

```
```
# 1) Clone & enter
git clone <REPO_URL>
cd LifeFlow

# 2) Python venv
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) Install 
pip install -r requirements.txt

# 4) DB setup
python3 manage.py migrate

# 5) Run
python3 manage.py runserver
```

# Local login vs Google login

- Local dev works without Google keys. Use the Django superuser you created.
- To enable Google login/calendar in dev, fill `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and ensure `GOOGLE_REDIRECT_URI=http://localhost:8000/google/oauth2/callback/.`

# Troubleshooting
- *SECRET_KEY* must not be empty: add `DJANGO_SECRET_KEY` to `.env` (any random string for dev), or keep DJANGO_DEBUG=1 locally.
- *CSRF verification failed (non-localhost):* set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for your domain.
- *Google redirect_uri_mismatch:* the redirect URI in Google Console must exactly match `GOOGLE_REDIRECT_URI`.
- GH013 push blocked (secrets detected): see `SECURITY.md` → Rotate & purge history.
