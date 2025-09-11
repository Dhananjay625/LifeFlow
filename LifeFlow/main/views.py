# stdlib
from datetime import date, datetime, timedelta
from calendar import monthrange
import calendar as cal
import json
import os
import secrets
from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    JsonResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponse,
)
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.conf import settings

# google api
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials 
from google.auth.transport import requests as google_requests  
from .forms import TaskForm
from .models import Bill, Document, Task
try:
    from .models import Subscription  
except Exception:
    from .models import sub
User = get_user_model()
from types import SimpleNamespace
from datetime import datetime, timedelta
from .models import HealthMetric, Reminder, UserHealthProfile
from .forms import HealthMetricForm, HealthProfileForm, ReminderForm



# Allow HTTP for local dev (never in prod)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# ---------- helpers ----------

def _model_has_field(model, field_name: str) -> bool:
    return any(f.name == field_name for f in model._meta.get_fields())

def _to_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    return d

def _is_monthly(contract_type: str) -> bool:
    ct = (contract_type or '').strip().lower()
    return 'month' in ct

def _is_yearly(contract_type: str) -> bool:
    ct = (contract_type or '').strip().lower()
    return 'year' in ct

def _monthly_rrule_for(dt: date):
    _, last_day = monthrange(dt.year, dt.month)
    if dt.day == last_day:
        return {'freq': 'monthly', 'dtstart': dt.isoformat(), 'bymonthday': -1}
    return {'freq': 'monthly', 'dtstart': dt.isoformat(), 'bymonthday': dt.day}

def _parse_iso_to_aware(s: str, expect_date_only=False):
    """
    Parse ISO8601 to an aware datetime in the current timezone.
    If expect_date_only=True and the string is YYYY-MM-DD, returns local midnight that day.
    """
    if not s:
        return None
    try:
        s_norm = s.replace('Z', '+00:00') if isinstance(s, str) else s
        dt = datetime.fromisoformat(s_norm)
    except Exception:
        if expect_date_only:
            try:
                d = datetime.strptime(s, '%Y-%m-%d')
                dt = d
            except Exception:
                raise ValueError(f'Invalid date: {s}')
        else:
            raise ValueError(f'Invalid datetime: {s}')
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.get_current_timezone())

def _google_flow_config(redirect_uri: str):
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "project_id": "lifeflow-469400",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uris": [redirect_uri],
        }
    }

# Request everything we need in one flow (prevents double sign-in)
GCAL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar",
]

from google.auth.exceptions import RefreshError

def _sync_gcal_events_to_tasks(request, max_results=50, creds=None):
    """
    Pull upcoming Google events and upsert into Task table.
    If creds is provided, use it (fresh from callback). Otherwise rebuild from session.
    """
    if creds is None:
        creds_dict = request.session.get("google_credentials")
        if not creds_dict or not request.user.is_authenticated:
            return
        creds = GoogleCreds.from_authorized_user_info(creds_dict, scopes=creds_dict.get("scopes"))

    try:
        service = build("calendar", "v3", credentials=creds)
        resp = service.events().list(
            calendarId="primary",
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except RefreshError:
        # No refresh_token or invalid creds — skip silently
        return

    items = resp.get("items", [])
    for ev in items:
        summary = ev.get("summary") or "(No title)"
        start = ev.get("start", {})
        start_iso = start.get("dateTime") or start.get("date")
        if not start_iso:
            continue
        all_day = "date" in start
        due_dt = _parse_iso_to_aware(start_iso, expect_date_only=all_day)

        if _model_has_field(Task, 'external_id'):
            obj, _ = Task.objects.get_or_create(
                user=request.user,
                external_id=ev.get("id"),
                defaults={"title": summary, "due_date": due_dt, "status": "pending"},
            )
            changed = False
            if obj.title != summary:
                obj.title = summary; changed = True
            if obj.due_date != due_dt:
                obj.due_date = due_dt; changed = True
            if changed:
                obj.save()
        else:
            if not Task.objects.filter(user=request.user, title=summary, due_date=due_dt).exists():
                Task.objects.create(user=request.user, title=summary, due_date=due_dt, status="pending")


# ---------- auth (username/password) ----------

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next')
            return redirect(next_url or 'TaskManager')
        return render(request, 'index.html', {'error': 'Invalid username or password.'})
    return render(request, 'index.html')

def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if User.objects.filter(username=username).exists():
            return render(request, 'register.html', {'error': 'Username already taken.'})
        if User.objects.filter(email=email).exists():
            return render(request, 'register.html', {'error': 'Email already registered.'})
        if password != confirm_password:
            return render(request, 'register.html', {'error': 'Passwords do not match.'})

        User.objects.create_user(username=username, email=email, password=password)
        return redirect('login')

    return render(request, 'register.html')

# ---------- tasks ----------

@login_required
def create_task(request):
    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = request.user
            task.save()
            return redirect('dashboard-v2')
    else:
        form = TaskForm()
    return render(request, 'add_item.html', {'form': form, 'item_type': 'task'})

@login_required
def task_list(request):
    tasks = Task.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'task_list.html', {'tasks': tasks})

@login_required
def complete_task(request, task_id):
    task = Task.objects.get(id=task_id, user=request.user)
    task.status = 'completed'
    task.save()
    return redirect('task_list')

@login_required
def archive_task(request, task_id):
    task = Task.objects.get(id=task_id, user=request.user)
    task.status = 'archived'
    task.save()
    return redirect('task_list')

# ---------- calendar ----------

@login_required
def calendar_view(request):
    today = date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    first_day = timezone.make_aware(datetime(year, month, 1))
    last_day = timezone.make_aware(datetime(year, month, monthrange(year, month)[1]))
    days = [first_day.date() + timedelta(days=i) for i in range((last_day - first_day).days + 1)]

    tasks = Task.objects.filter(user=request.user, due_date__range=(first_day, last_day))

    context = {
        'year': year,
        'month': month,
        'month_name': cal.month_name[month],
        'days': days,
        'tasks': tasks,
    }
    return render(request, 'calendar.html', context)

@login_required
def calendar_events(request):
    events = []

    # Tasks (one-off)
    for t in Task.objects.filter(user=request.user).exclude(due_date__isnull=True).values(
        'id', 'title', 'due_date', 'status', 'priority'
    ):
        events.append({
            'id': f"task-{t['id']}",
            'title': t['title'],
            'start': t['due_date'].isoformat() if isinstance(t['due_date'], datetime) else t['due_date'],
            'allDay': True,
            'extendedProps': {'type': 'task', 'status': t['status'], 'priority': t['priority']},
        })

    # Bills
    bills_qs = Bill.objects.filter(status='active')
    if _model_has_field(Bill, 'user'):
        bills_qs = bills_qs.filter(user=request.user)
    bills_qs = bills_qs.exclude(renewal_date__isnull=True).values('id', 'name', 'renewal_date', 'cost', 'contract_type')

    for b in bills_qs:
        rd = _to_date(b['renewal_date'])
        if not rd:
            continue
        title = f"{b['name']} bill (${b['cost']})"
        if _is_monthly(b.get('contract_type')):
            events.append({
                'id': f"bill-{b['id']}",
                'title': title,
                'allDay': True,
                'duration': 'P1D',
                'extendedProps': {'type': 'bill'},
                'rrule': _monthly_rrule_for(rd),
            })
        elif _is_yearly(b.get('contract_type')):
            events.append({
                'id': f"bill-{b['id']}",
                'title': title,
                'allDay': True,
                'duration': 'P1D',
                'extendedProps': {'type': 'bill'},
                'rrule': {'freq': 'yearly', 'dtstart': rd.isoformat()},
            })
        else:
            events.append({
                'id': f"bill-{b['id']}",
                'title': title,
                'start': rd.isoformat(),
                'allDay': True,
                'extendedProps': {'type': 'bill'},
            })

    # Subscriptions
    subs_qs = sub.objects.filter(status='active')
    if _model_has_field(sub, 'user'):
        subs_qs = subs_qs.filter(user=request.user)
    subs_qs = subs_qs.exclude(renewal_date__isnull=True).values('id', 'name', 'renewal_date', 'cost', 'contract_type')

    for s in subs_qs:
        rd = _to_date(s['renewal_date'])
        if not rd:
            continue
        title = f"{s['name']} subscription (${s['cost']})"
        if _is_monthly(s.get('contract_type')):
            events.append({
                'id': f"sub-{s['id']}",
                'title': title,
                'allDay': True,
                'duration': 'P1D',
                'extendedProps': {'type': 'subscription'},
                'rrule': _monthly_rrule_for(rd),
            })
        elif _is_yearly(s.get('contract_type')):
            events.append({
                'id': f"sub-{s['id']}",
                'title': title,
                'allDay': True,
                'duration': 'P1D',
                'extendedProps': {'type': 'subscription'},
                'rrule': {'freq': 'yearly', 'dtstart': rd.isoformat()},
            })
        else:
            events.append({
                'id': f"sub-{s['id']}",
                'title': title,
                'start': rd.isoformat(),
                'allDay': True,
                'extendedProps': {'type': 'subscription'},
            })

    # Append Google Calendar events (live) if connected
    creds_dict = request.session.get("google_credentials")
    if creds_dict:
        try:
            gcreds = GoogleCreds.from_authorized_user_info(creds_dict, scopes=creds_dict.get("scopes"))
            service = build("calendar", "v3", credentials=gcreds)
            gitems = service.events().list(
                calendarId="primary", maxResults=50, singleEvents=True, orderBy="startTime"
            ).execute().get("items", [])

            for ev in gitems:
                start = ev.get("start", {})
                end = ev.get("end", {})
                start_iso = start.get("dateTime") or start.get("date")
                end_iso = end.get("dateTime") or end.get("date")
                if not start_iso:
                    continue
                all_day = "date" in start
                events.append({
                    'id': f"gcal-{ev.get('id')}",
                    'title': ev.get('summary') or '(No title)',
                    'start': start_iso,
                    'end': end_iso,
                    'allDay': all_day,
                    'extendedProps': {'type': 'gcal', 'htmlLink': ev.get('htmlLink')},
                })
        except Exception:
            # token errors etc — ignore gracefully
            pass

    return JsonResponse(events, safe=False)

@login_required
def calendar_events_create(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    try:
        payload = json.loads(request.body or '{}')
        title = (payload.get('title') or '').strip()
        if not title:
            return HttpResponseBadRequest('Title required')
        start_str = payload.get('start')
        if not start_str:
            return HttpResponseBadRequest('start required')

        all_day = bool(payload.get('allDay', False))
        due_dt = _parse_iso_to_aware(start_str, expect_date_only=all_day)

        task = Task.objects.create(
            user=request.user,
            title=title,
            due_date=due_dt,
            status='pending',
        )
        return JsonResponse({'id': f'task-{task.id}'}, status=201)
    except Exception as e:
        return HttpResponseBadRequest(str(e))

# ---------- Google OAuth (single flow) ----------

def google_connect(request):
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    flow = Flow.from_client_config(
        _google_flow_config(redirect_uri),
        scopes=GCAL_SCOPES,
        state=state,
    )
    flow.redirect_uri = redirect_uri

    have_refresh = bool(request.session.get("google_credentials", {}).get("refresh_token"))
    auth_kwargs = dict(
        access_type="offline",
        include_granted_scopes="true",  
        state=state,
    )
    if not have_refresh:
        auth_kwargs["prompt"] = "consent"

    auth_url, _ = flow.authorization_url(**auth_kwargs)
    return redirect(auth_url)



def google_callback(request):
    """
    Callback: verify state, fetch tokens, log in Django user, store creds, sync events, go to profile.
    Also fills first/last name when available.
    """
    expected_state = request.session.get("oauth_state")
    returned_state = request.GET.get("state")
    if not expected_state or expected_state != returned_state:
        request.session.pop("oauth_state", None)
        return redirect("google_connect")

    redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow = Flow.from_client_config(
        _google_flow_config(redirect_uri),
        scopes=GCAL_SCOPES,
        state=expected_state,
    )
    flow.redirect_uri = redirect_uri

    flow.fetch_token(
        authorization_response=request.build_absolute_uri(),
        state=expected_state,
    )
    credentials = flow.credentials  # fresh access token (likely not expired yet)

    # Identify user via Google ID token
    idinfo = id_token.verify_oauth2_token(
        credentials.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
    )
    email = idinfo.get("email")

    # Prefer split name fields; fall back gracefully
    first = idinfo.get("given_name")
    last = idinfo.get("family_name")
    if not first and not last:
        full = (idinfo.get("name") or "").strip()
        if full:
            parts = full.split()
            first = parts[0]
            last = " ".join(parts[1:]) if len(parts) > 1 else ""
        else:
            local = (email or "").split("@")[0]
            first = local or ""
            last = ""

    user, created = User.objects.get_or_create(username=email, defaults={"email": email})

    changed = False
    if created:
        if first: user.first_name = first; changed = True
        if last:  user.last_name = last;  changed = True
    else:
        if first and not user.first_name: user.first_name = first; changed = True
        if last and not user.last_name:   user.last_name = last;   changed = True
        if not user.email and email:      user.email = email;      changed = True
    if changed:
        user.save()

    login(request, user)
    request.session.pop("oauth_state", None)

    # Save Google creds (include expiry!)
    request.session["google_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
        "expiry": credentials.expiry.isoformat() if getattr(credentials, "expiry", None) else None,
    }

    # Sync immediately using the fresh creds (no refresh needed)
    _sync_gcal_events_to_tasks(request, creds=credentials)

    return redirect("user_profile")


# ---------- calendar event mutations ----------

def calendar_events_update(request):
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except ValueError:
        return HttpResponseBadRequest("Invalid JSON")

    full_id = str(payload.get("id") or "").strip()
    if not full_id:
        return HttpResponseBadRequest("Missing id")

    title = payload.get("title")
    start_str = payload.get("start")

    # ---- Task ----
    if full_id.startswith("task-"):
        task_id = full_id.split("task-")[-1]
        task = get_object_or_404(Task, id=task_id, user=request.user)

        if isinstance(title, str) and title.strip():
            task.title = title.strip()

        if start_str:
            # If allDay is not provided, default to True for tasks (same as your code)
            all_day = bool(payload.get("allDay", True))
            # Your helper decides whether to parse as date-only or datetime
            task.due_date = _parse_iso_to_aware(start_str, expect_date_only=all_day)

        task.save()
        return JsonResponse({"ok": True, "id": full_id})

    # ---- Subscription ----
    if full_id.startswith("sub-"):
        sub_id = full_id.split("sub-")[-1]
        if _model_has_field(Subscription, "user"):
            s = get_object_or_404(Subscription, id=sub_id, user=request.user)
        else:
            s = get_object_or_404(Subscription, id=sub_id)

        if isinstance(title, str) and title.strip():
            s.name = title.strip()

        if start_str:
            # Calendar drag for subs is date-based
            s.renewal_date = _parse_iso_to_aware(start_str, expect_date_only=True).date()

        s.save()
        return JsonResponse({"ok": True, "id": full_id})

    # ---- Bill ----
    if full_id.startswith("bill-"):
        bill_id = full_id.split("bill-")[-1]
        if _model_has_field(Bill, "user"):
            b = get_object_or_404(Bill, id=bill_id, user=request.user)
        else:
            b = get_object_or_404(Bill, id=bill_id)

        if isinstance(title, str) and title.strip():
            b.name = title.strip()

        if start_str:
            b.renewal_date = _parse_iso_to_aware(start_str, expect_date_only=True).date()

        b.save()
        return JsonResponse({"ok": True, "id": full_id})

    # Unknown prefix
    return HttpResponseBadRequest("Unknown id prefix")

@login_required
def calendar_events_delete(request):
    """
    Delete a Task from the calendar.
    Body: { id }
    Only supports ids that start with 'task-'.
    """
    if request.method != 'DELETE':
        return HttpResponseNotAllowed(['DELETE'])
    try:
        payload = json.loads(request.body or '{}')
        full_id = payload.get('id') or ''
        if not full_id.startswith('task-'):
            return HttpResponseBadRequest('Only tasks can be deleted from the calendar')
        task_id = full_id.split('task-')[-1]
        task = get_object_or_404(Task, id=task_id, user=request.user)
        task.delete()
        return JsonResponse({'ok': True})
    except Exception as e:
        return HttpResponseBadRequest(str(e))

# ---------- other views ----------

@login_required
def add_item(request, item_type):
    if request.method == 'POST':
        if item_type == 'bill':
            create_kwargs = dict(
                name=request.POST.get('name'),
                cost=request.POST.get('cost'),
                renewal_date=request.POST.get('renewal_date') or None,
                contract_type=request.POST.get('contract_type') or 'NA',
                status='active',
            )
            if _model_has_field(Bill, 'user'):
                create_kwargs['user'] = request.user
            Bill.objects.create(**create_kwargs)
            return redirect('BillManager')

        elif item_type == 'document':
            doc_name = request.POST.get('doc_name')
            uploaded_file = request.FILES.get('upload')
            if uploaded_file:
                Document.objects.create(user=request.user, doc_name=doc_name, file=uploaded_file)
            return redirect('DocumentStorage')

        elif item_type == 'subscription':
            create_kwargs = dict(
                name=request.POST.get('name'),
                cost=request.POST.get('cost'),
                renewal_date=request.POST.get('renewal_date') or None,
                contract_type=request.POST.get('contract_type') or 'NA',
                status='active',
            )
            if _model_has_field(sub, 'user'):
                create_kwargs['user'] = request.user
            sub.objects.create(**create_kwargs)
            return redirect('Subscription')

    return render(request, 'add_item.html', {'item_type': item_type})

@login_required
def SubscriptionTracker(request):
    subs_qs = sub.objects.all()
    if _model_has_field(sub, 'user'):
        subs_qs = subs_qs.filter(user=request.user)
    total_cost = sum(b.cost for b in subs_qs)
    subs_with_colors = [{"obj": s, "hue": (i + 1) * 60} for i, s in enumerate(subs_qs)]
    return render(request, 'Subscription.html', {'subs': subs_with_colors, 'total_cost': total_cost})

def TaskManager(request):
    return render(request, 'TaskManager.html')

def BillManager(request):
    bills_qs = Bill.objects.all()
    if _model_has_field(Bill, 'user'):
        bills_qs = bills_qs.filter(user=request.user)
    total_cost = sum(b.cost for b in bills_qs)
    bills_with_colors = [{"obj": b, "hue": (i + 1) * 60} for i, b in enumerate(bills_qs)]
    return render(request, 'BillManager.html', {'bills': bills_with_colors, 'total_cost': total_cost})

def LandingPage(request):
    return render(request, 'LandingPage.html')

@login_required
def DocumentStorage(request):
    if not request.session.get('document_verified'):
        return redirect('confirm_password')
    documents = Document.objects.filter(user=request.user)
    return render(request, 'DocumentStorage.html', {'documents': documents})

@login_required
def delete_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id, user=request.user)
    document.delete()
    return redirect('DocumentStorage')

def HealthManager(request):
    return render(request, 'HealthManager.html')

@login_required
def dashboard(request):
    return render(request, 'dashboard.html')

@login_required
def user_profile(request):
    return render(request, 'UserProfile.html', {'user': request.user})

@login_required
def confirm_password(request):
    if request.method == 'POST':
        password = request.POST.get('password')
        user = authenticate(username=request.user.username, password=password)
        if user is not None:
            request.session['document_verified'] = True
            return redirect('DocumentStorage')
        return render(request, 'confirm_password.html', {'error': 'Incorrect password.'})
    return render(request, 'confirm_password.html')

def delete_bill(request, bill_id):
    if request.method == 'POST':
        if _model_has_field(Bill, 'user'):
            bill = get_object_or_404(Bill, id=bill_id, user=request.user)
        else:
            bill = get_object_or_404(Bill, id=bill_id)
        bill.delete()
    return redirect('BillManager')

@login_required
def delete_sub(request, sub_id):
    if _model_has_field(sub, 'user'):
        subscription = get_object_or_404(sub, id=sub_id, user=request.user)
    else:
        subscription = get_object_or_404(sub, id=sub_id)
    subscription.delete()
    return redirect('Subscription')

# Convenience aliases
calendar = calendar_view
calender_view = calendar_view

def FamilyManager(request):
    family = SimpleNamespace(id=1, name="The Rai Family", created_at=datetime.now())
    owner = SimpleNamespace(username=getattr(request.user, "username", "owner"))
    members = [
        SimpleNamespace(user=SimpleNamespace(username="yash"), role="owner"),
        SimpleNamespace(user=SimpleNamespace(username="Vaidehi"), role="parent"),
        SimpleNamespace(user=SimpleNamespace(username="aarav"), role="child"),
    ]
    invites = []
    tasks = [
        SimpleNamespace(title="Grocery run", due_date=datetime.now()+timedelta(hours=6),
                        assigned_to=SimpleNamespace(username="yash"), priority="high", completed=False),
        SimpleNamespace(title="Pay electricity bill", due_date=datetime.now()+timedelta(days=1),
                        assigned_to=SimpleNamespace(username="jiya"), priority="medium", completed=False),
    ]
    return render(request, "FamilyManager.html", {
        "family": family, "owner": owner, "members": members,
        "invites": invites, "tasks": tasks, "families": [family],
    })

#-------- AI Helpers -----------
# Uses the official OpenAI Python SDK v1.x 
def _rule_based_advice(age, bmi):
    """
    Simple built-in AI advice (works without external APIs).
    """
    tips = []
    if bmi is None:
        return ["Enter your height and weight to get BMI-based advice."]
    if bmi < 18.5:
        tips.append("Your BMI suggests you're underweight. Consider nutrient-dense meals and speak to a GP or dietitian.")
    elif bmi < 25:
        tips.append("Great—your BMI is in the healthy range. Keep up regular activity and balanced meals.")
    elif bmi < 30:
        tips.append("Your BMI suggests you're overweight. Aim for consistent activity (e.g., brisk walking 30 mins/day) and watch portion sizes.")
    else:
        tips.append("Your BMI suggests obesity. Consider a structured plan with a healthcare professional.")

    if age and age >= 45:
        tips.append("For 45+, include strength training 2–3×/week to preserve muscle and bone health.")
    tips.append("Hydration: ~2–2.5L/day (adjust for activity and climate).")
    tips.append("Aim for 7–9 hours of sleep and regular checkups.")
    return tips

# Path to your Google OAuth client credentials
GOOGLE_CLIENT_SECRETS_FILE = os.path.join(settings.BASE_DIR, "credentials.json")
SCOPES = ["https://www.googleapis.com/auth/fitness.activity.read"]

# Save credentials in session or DB in real app
SCOPES = ["https://www.googleapis.com/auth/fitness.activity.read",
          "https://www.googleapis.com/auth/fitness.nutrition.read",
          "https://www.googleapis.com/auth/fitness.body.read"]

def google_fit_login(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, "credentials.json"),
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    request.session["flow"] = flow.authorization_url
    return redirect(auth_url)

def oauth2callback(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, "credentials.json"),
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    flow.fetch_token(authorization_response=request.build_absolute_uri())

    credentials = flow.credentials
    request.session["credentials"] = credentials.to_json()
    return redirect("HealthManager")

@login_required
def health_manager(request):
    creds_data = request.session.get("credentials")

    if not creds_data:
        return redirect("google_fit_auth")  # Or show an error

    creds = Credentials(**creds_data)
    profile, _ = UserHealthProfile.objects.get_or_create(user=request.user)
    today = timezone.now().date()
    today_metrics = HealthMetric.objects.filter(user=request.user, date=today).first()
    reminders = Reminder.objects.filter(user=request.user).order_by('-date')[:7]

    metric_form = HealthMetricForm(initial={
        'water_intake': getattr(today_metrics, 'water_intake', ''),
        'steps': getattr(today_metrics, 'steps', ''),
        'calories': getattr(today_metrics, 'calories', ''),
    })
    profile_form = HealthProfileForm(instance=profile)
    reminder_form = ReminderForm()

    if request.method == 'POST':
        if 'save_profile' in request.POST:
            profile_form = HealthProfileForm(request.POST, instance=profile)
            if profile_form.is_valid():
                profile_form.save()
                return redirect('HealthManager')

        elif 'save_metrics' in request.POST:
            form = HealthMetricForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data

                # Ensure no NULLs for required fields
                data['steps'] = data.get('steps') or 0
                data['calories'] = data.get('calories') or 0
                data['water_intake'] = data.get('water_intake') or 0

                HealthMetric.objects.update_or_create(
                    user=request.user,
                    date=today,
                    defaults=data
                )
                return redirect('HealthManager')

        elif 'quick_metric' in request.POST:
            metric_type = request.POST.get('metric_type')
            value = request.POST.get('metric_value')

            if metric_type not in ['water_intake', 'steps', 'calories']:
                return HttpResponseBadRequest("Invalid metric type")

            defaults = {}
            try:
                if metric_type == 'water_intake':
                    defaults['water_intake'] = float(value)
                elif metric_type == 'steps':
                    defaults['steps'] = int(value)
                else:
                    defaults['calories'] = int(value)
            except (TypeError, ValueError):
                return HttpResponseBadRequest("Invalid value")

            existing = HealthMetric.objects.filter(user=request.user, date=today).first()
            if existing:
                defaults.setdefault('water_intake', existing.water_intake or 0)
                defaults.setdefault('steps', existing.steps or 0)
                defaults.setdefault('calories', existing.calories or 0)

            # Make sure all fields are present
            defaults['water_intake'] = defaults.get('water_intake', 0)
            defaults['steps'] = defaults.get('steps', 0)
            defaults['calories'] = defaults.get('calories', 0)

            HealthMetric.objects.update_or_create(
                user=request.user, date=today, defaults=defaults
            )
            return redirect('HealthManager')

        elif 'save_reminder' in request.POST:
            reminder_form = ReminderForm(request.POST)
            if reminder_form.is_valid():
                rem = reminder_form.save(commit=False)
                rem.user = request.user
                rem.save()
                return redirect('HealthManager')

    # BMI logic
    bmi = profile.bmi()
    bmi_cat = profile.bmi_category()
    advice = _rule_based_advice(profile.age, bmi)

    # Google Fit integration
    google_fit_data = {"steps": None, "calories": None, "water_intake": None}
    creds_data = request.session.get("credentials")
    if creds_data:
        creds = Credentials(**creds_data)
        service = build("fitness", "v1", credentials=creds)

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=1)

        results = service.users().dataset().aggregate(
            userId="me",
            body={
                "aggregateBy": [
                    {"dataTypeName": "com.google.step_count.delta"},
                    {"dataTypeName": "com.google.calories.expended"},
                    {"dataTypeName": "com.google.hydration"},
                ],
                "bucketByTime": {"durationMillis": 86400000},
                "startTimeMillis": int(start_time.timestamp() * 1000),
                "endTimeMillis": int(end_time.timestamp() * 1000)
            }
        ).execute()

        for bucket in results.get("bucket", []):
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    dtype = point["dataTypeName"]
                    for value in point["value"]:
                        if dtype == "com.google.step_count.delta":
                            google_fit_data["steps"] = (google_fit_data["steps"] or 0) + value.get("intVal", 0)
                        elif dtype == "com.google.calories.expended":
                            google_fit_data["calories"] = (google_fit_data["calories"] or 0) + value.get("fpVal", 0)
                        elif dtype == "com.google.hydration":
                            google_fit_data["water_intake"] = (google_fit_data["water_intake"] or 0) + value.get("fpVal", 0)

        # Save to DB
        if any(v is not None for v in google_fit_data.values()):
            if today_metrics:
                today_metrics.steps = google_fit_data["steps"] or today_metrics.steps
                today_metrics.calories = google_fit_data["calories"] or today_metrics.calories
                today_metrics.water_intake = google_fit_data["water_intake"] or today_metrics.water_intake
                today_metrics.save()
            else:
                HealthMetric.objects.create(
                    user=request.user,
                    date=today,
                    steps=google_fit_data["steps"] or 0,
                    calories=google_fit_data["calories"] or 0,
                    water_intake=google_fit_data["water_intake"] or 0,
                )

    context = {
        "profile_form": profile_form,
        "metric_form": metric_form,
        "reminder_form": reminder_form,
        "metrics": today_metrics,
        "reminders": reminders,
        "bmi": bmi,
        "bmi_cat": bmi_cat,
        "advice": advice,
        "google_fit_data": google_fit_data,
    }
    return render(request, "HealthManager.html", context)

@login_required
def health_search(request):
    """
    Redirects to a trusted health site search in a new tab based on query.
    You can change domains below to your preference.
    """
    q = request.GET.get('q', '').strip()
    if not q:
        return redirect('HealthManager')
    
    query = f"site:healthdirect.gov.au OR site:who.int OR site:cdc.gov {q}"
    params = urlencode({'q': query})
    return redirect(f"https://www.google.com/search?{params}")

def google_fit_auth(request):
    # return HttpResponse("Google Fit authentication will go here.")
    flow = Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/google-fit-callback/"
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    request.session["state"] = state
    return redirect(auth_url)

@login_required
def google_fit_callback(request):
    """
    Step 2: Handle Google's OAuth 2.0 redirect back
    """
    state = request.session.get("state")

    flow = Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri="http://localhost:8000/google-fit-callback/"
    )

    flow.fetch_token(authorization_response=request.build_absolute_uri())
    creds = flow.credentials

    # Save credentials in session (or DB if you prefer)
    request.session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    }

    return redirect("https://www.google.com/fit/")