# README.md
A Django web app to manage Tasks, Subscriptions, Bills and a unified Calendar. Optional Google OAuth enables Google Calendar sync.

### Features
- Tasks: create, list, complete, archive; priorities & due dates
- Subscriptions: track renewal dates, names
- Bills: track renewal dates, names
- Calendar: month/day view; drag/resize/edit items
- Google OAuth (optional): connect your Google account; import upcoming events into Tasks
- Documents: upload & delete user documents


### Project Structure

LifeFlow/
│
├── LifeFlow/                 
│
├── main/                     
│   ├── static/
│   ├── templates/
│   └── kanban/
│   │   └── projects/
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   └── apps.py
│
├── kanban/                   
├── appboard/                
├── media/                   
├── .env.example             
├── requirements.txt
└── manage.py


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

```

### Quickstart (Windows PowerShell)
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

# AI Query Setup Guide

- Creating OpenAI API Key 

1. Visit the Official OpenAI website:
    https://platform.openai.com/account/api-keys

2. Log in (or sign up)

3. Click "Create new secret key".

4. Copy the generated key - it will look like this: 
    sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

- Set API Key in the Terminal 
Open your terminal in the project directory and run the following command line:
    export OPENAI_API_KEY="Your_key_here"
replace "Your_key_here" with the actual created API key. 

- Run the Project
Once you have set the API key simply run the app.
python manage.py runserver

### Troubleshooting
To check if your API key is loaded correctly 
- Open Django shell, run:
    python3 manage.py shell
- Then inside, enter the following:
    from django.conf import settings
    print(settings.OPENAI_API_KEY)

If it prints None, the environment variable isn't set correctly.
If it prints something like 'sk.xxxxx', your key, then Django can read it fine. 
 
 
## Health Data Integration 
### Overview
This project enhances the Health Manager page by integrating the Health Kit (iOS) and Health Connect (Android) APIs, which allow for real-time synchronisation of user's health data. 

Initially, the Google Fit API was integrated in the project to collect user data. However, since Google Fit will be deprecated in 2026, the integration strategy has been revised to ensure cross-platform compatibility. 

## Integration Options (Health Kit and Health Connect)
### Option 1: Native Integration (Manually)
Implement these on-device APIs directly in native mobile applications. 

- **iOS (Swift)**
    - Use Apple Health Kit to fetch and write health-related metries.
    - Requires user authorisation via 'HKHealthStore'.
    - Data is stored securely on the device and can be selectively shared with the backend. 

- **Android (Kotlin)**
    - Use Health Connect to access fitness data.
    - Offers granular permission management for user privacy.
    - Requires creating a Health Connect client and requesting read/write permissions. 

**Pros**
- Offers direct and secure access to user data 
- No dependency on 3rd party services.
- Better control over permissions and data flow.
- Free of cost. 

**Cons**
- Requires maintaining separate codebase for iOS and Android.
- Increases development complexity. 

### Option 2: 3rd-Party API Aggregator
Integrate through a 3rd-party health data aggregation service that bridges btoh APIs Health Kit and Health Connect. 
API Aggregators options:
- Terra
- Human API
- Validic
- Fitbit Web API 

**Pros**
- Simplifies integration with a single unified API.
- Supports multiple platforms and data types.
- Reduces native development effort.

**Cons**
- Adds a dependency on an external service.
- Potential costs or rate limits. Each of the API aggregators requires cost for implementation vary costs. 


### Tech Stack
- **Backend:** Django, Python3 
- **Frontend:** HTML5, Bootstrap, JavaScript
- **Database:** SQLite, PostgreSQL 
- **APIs:** Google Calendar API, OpenAI API