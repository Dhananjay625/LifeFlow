from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed, HttpResponse
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from calendar import monthrange
import calendar as cal
from datetime import date, datetime, timedelta
import json
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from .forms import TaskForm
from .models import Bill, Document, sub, Task
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import secrets
from google.oauth2.credentials import Credentials as GoogleCreds

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
            return redirect('TaskManager')
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
        credentials.id_token, requests.Request(), settings.GOOGLE_CLIENT_ID
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

# main/views.py
from django.shortcuts import render
from types import SimpleNamespace
from datetime import datetime, timedelta

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
