from datetime import date, datetime, timedelta
from calendar import monthrange
import calendar as cal
import json
import os
import secrets

# AI Integration
from openai import OpenAI
from openai import APIError, APIConnectionError, RateLimitError, AuthenticationError, OpenAIError
import logging

# django
from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
from types import SimpleNamespace
from urllib.parse import urlencode
from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    JsonResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponse,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from main import views_widgets
from django.utils.timezone import localtime

# google api
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials as GoogleCredentials
from google.auth.transport import requests as google_requests
from google.oauth2.credentials import Credentials
from google.auth.transport import requests as google_requests
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError

# local
from .forms import TaskForm
from .models import Bill, Document, Task
from .models import Family, FamilyMembership, FamilyInvite
from django.core.mail import EmailMultiAlternatives

# Health manager bits
from .models import HealthMetric, Reminder, UserHealthProfile
from .forms import HealthMetricForm, HealthProfileForm, ReminderForm
from django.views.decorators.csrf import csrf_exempt

# Support either Subscription or sub model names
try:
    from .models import Subscription as SubscriptionModel
except Exception:
    from .models import sub as SubscriptionModel

User = get_user_model()

try:
    from .models import Subscription
except Exception:
    from .models import sub
User = get_user_model()

from .models import HealthMetric, Reminder, UserHealthProfile
from .forms import HealthMetricForm, HealthProfileForm, ReminderForm

# Allow HTTP for local dev (never in prod)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

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
    ct = (contract_type or "").strip().lower()
    return "month" in ct

def _is_yearly(contract_type: str) -> bool:
    ct = (contract_type or "").strip().lower()
    return "year" in ct

def _monthly_rrule_for(dt: date):
    _, last_day = monthrange(dt.year, dt.month)
    if dt.day == last_day:
        return {"freq": "monthly", "dtstart": dt.isoformat(), "bymonthday": -1}
    return {"freq": "monthly", "dtstart": dt.isoformat(), "bymonthday": dt.day}

def _parse_iso_to_aware(s: str, expect_date_only=False):
    """
    Parse ISO8601 to an aware datetime in the current timezone.
    If expect_date_only=True and the string is YYYY-MM-DD, returns local midnight that day.
    """
    if not s:
        return None
    try:
        s_norm = s.replace("Z", "+00:00") if isinstance(s, str) else s
        dt = datetime.fromisoformat(s_norm)
    except Exception:
        if expect_date_only:
            try:
                d = datetime.strptime(s, "%Y-%m-%d")
                dt = d
            except Exception:
                raise ValueError(f"Invalid date: {s}")
        else:
            raise ValueError(f"Invalid datetime: {s}")
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

# Base Calendar scopes you already use

GCAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

# Unified session key + Fit scopes + identity scopes
GOOGLE_SESSION_KEY = "google_credentials"
GFIT_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.nutrition.read",
    "https://www.googleapis.com/auth/fitness.body.read",
]
GOOGLE_ID_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

def _sync_gcal_events_to_tasks(request, max_results=50, creds=None):
    """
    Pull upcoming Google events and upsert into Task table.
    If creds is provided, use it (fresh from callback). Otherwise rebuild from session.
    """
    if creds is None:
        creds_dict = request.session.get(GOOGLE_SESSION_KEY)
        if not creds_dict or not request.user.is_authenticated:
            return
        creds = GoogleCredentials.from_authorized_user_info(
            creds_dict, scopes=creds_dict.get("scopes")
        )
        creds = Credentials.from_authorized_user_info(creds_dict, scopes=creds_dict.get("scopes"))

    try:
        service = build("calendar", "v3", credentials=creds)
        resp = service.events().list(
            calendarId="primary",
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except RefreshError:
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

        if _model_has_field(Task, "external_id"):
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

# ---------- Unified Google creds helpers ----------

def _load_google_credentials(request):
    data = request.session.get(GOOGLE_SESSION_KEY)
    if not data:
        return None

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or [],
    )

    expiry_iso = data.get("expiry")
    if expiry_iso:
        try:
            exp = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
            creds.expiry = exp  # google-auth handles tz awareness internally
        except Exception:
            pass

    # Refresh silently if expired (and we have a refresh token)
    try:
        if creds and creds.refresh_token and (not creds.valid or creds.expired):
            creds.refresh(GoogleRequest())
            request.session[GOOGLE_SESSION_KEY] = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes) if getattr(creds, "scopes", None) else data.get("scopes", []),
                "expiry": creds.expiry.isoformat() if getattr(creds, "expiry", None) else None,
            }
            request.session.modified = True
    except Exception:
        return None

    return creds

def _has_required_scopes(creds, required_scopes: list[str]) -> bool:
    current = set((creds.scopes or [])) if creds else set()
    return set(required_scopes).issubset(current)

# ---------- auth (username/password) ----------
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next')
            # Old: return redirect(next_url or "TaskManager")
            return redirect(next_url or 'appboard:home')  # robust named redirect
    return render(request, 'index.html')
def register(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if User.objects.filter(username=username).exists():
            return render(request, "register.html", {"error": "Username already taken."})
        if User.objects.filter(email=email).exists():
            return render(request, "register.html", {"error": "Email already registered."})
        if password != confirm_password:
            return render(request, "register.html", {"error": "Passwords do not match."})

        User.objects.create_user(username=username, email=email, password=password)
        return redirect("login")

    return render(request, "register.html")

# ---------- tasks ----------
@login_required
def create_task(request):
    if request.method == "POST":
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = request.user
            task.save()
            return redirect("TaskManager")
    else:
        form = TaskForm()
    return render(request, "add_item.html", {"form": form, "item_type": "task"})

@login_required
def task_list(request):
    tasks = Task.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "task_list.html", {"tasks": tasks})

@login_required
def complete_task(request, task_id):
    task = Task.objects.get(id=task_id, user=request.user)
    task.status = "completed"
    task.save()
    return redirect("task_list")

@login_required
def archive_task(request, task_id):
    task = Task.objects.get(id=task_id, user=request.user)
    task.status = "archived"
    task.save()
    return redirect("task_list")

# ---------- calendar (page + JSON feed + mutations) ----------
@login_required
def calendar_view(request):
    today = date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    first_day = timezone.make_aware(datetime(year, month, 1))
    last_day = timezone.make_aware(datetime(year, month, monthrange(year, month)[1]))
    days = [first_day.date() + timedelta(days=i) for i in range((last_day - first_day).days + 1)]

    tasks = Task.objects.filter(user=request.user, due_date__range=(first_day, last_day))

    context = {
        "year": year,
        "month": month,
        "month_name": cal.month_name[month],
        "days": days,
        "tasks": tasks,
    }
    return render(request, "calendar.html", context)

@login_required
def calendar_events_create(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = json.loads(request.body or "{}")
        title = (payload.get("title") or "").strip()
        if not title:
            return HttpResponseBadRequest("Title required")
        start_str = payload.get("start")
        if not start_str:
            return HttpResponseBadRequest("start required")

        all_day = bool(payload.get("allDay", False))
        due_dt = _parse_iso_to_aware(start_str, expect_date_only=all_day)

        task = Task.objects.create(
            user=request.user, title=title, due_date=due_dt, status="pending"
        )

        CalendarEvent.objects.create(
            user=request.user,
            title=title,
            start=due_dt,
            all_day=all_day,
            type="task"
        )

        return JsonResponse({"id": f"task-{task.id}"}, status=201)
    except Exception as e:
        return HttpResponseBadRequest(str(e))

    # --- Optional dummy fallback events (if no tasks exist) ---
    if not events:
        now = datetime.now()
        events = [
            {
                "id": "dummy-1",
                "title": "🩺 Doctor's Appointment",
                "start": (now + timedelta(days=1)).isoformat(),
                "allDay": True,
                "extendedProps": {"type": "dummy", "status": "scheduled"},
            },
            {
                "id": "dummy-2",
                "title": "📦 Subscription Renewal",
                "start": (now + timedelta(days=3)).isoformat(),
                "allDay": True,
                "extendedProps": {"type": "dummy", "status": "renew"},
            },
        ]

    return JsonResponse({"events": events})
    # Bills
    bills_qs = Bill.objects.filter(status="active")
    if _model_has_field(Bill, "user"):
        bills_qs = bills_qs.filter(user=request.user)
    bills_qs = bills_qs.exclude(renewal_date__isnull=True).values("id", "name", "renewal_date", "cost", "contract_type")

    for b in bills_qs:
        rd = _to_date(b["renewal_date"])
        if not rd:
            continue
        title = f"{b['name']} bill (${b['cost']})"
        if _is_monthly(b.get("contract_type")):
            events.append({
                "id": f"bill-{b['id']}",
                "title": title,
                "allDay": True,
                "duration": "P1D",
                "extendedProps": {"type": "bill"},
                "rrule": _monthly_rrule_for(rd),
            })
        elif _is_yearly(b.get("contract_type")):
            events.append({
                "id": f"bill-{b['id']}",
                "title": title,
                "allDay": True,
                "duration": "P1D",
                "extendedProps": {"type": "bill"},
                "rrule": {"freq": "yearly", "dtstart": rd.isoformat()},
            })
        else:
            events.append({
                "id": f"bill-{b['id']}",
                "title": title,
                "start": rd.isoformat(),
                "allDay": True,
                "extendedProps": {"type": "bill"},
            })

    # Subscriptions
    subs_qs = SubscriptionModel.objects.filter(status="active")
    if _model_has_field(SubscriptionModel, "user"):
        subs_qs = subs_qs.filter(user=request.user)
    subs_qs = subs_qs.exclude(renewal_date__isnull=True).values("id", "name", "renewal_date", "cost", "contract_type")

    for s in subs_qs:
        rd = _to_date(s["renewal_date"])
        if not rd:
            continue
        title = f"{s['name']} subscription (${s['cost']})"
        if _is_monthly(s.get("contract_type")):
            events.append({
                "id": f"sub-{s['id']}",
                "title": title,
                "allDay": True,
                "duration": "P1D",
                "extendedProps": {"type": "subscription"},
                "rrule": _monthly_rrule_for(rd),
            })
        elif _is_yearly(s.get("contract_type")):
            events.append({
                "id": f"sub-{s['id']}",
                "title": title,
                "allDay": True,
                "duration": "P1D",
                "extendedProps": {"type": "subscription"},
                "rrule": {"freq": "yearly", "dtstart": rd.isoformat()},
            })
        else:
            events.append({
                "id": f"sub-{s['id']}",
                "title": title,
                "start": rd.isoformat(),
                "allDay": True,
                "extendedProps": {"type": "subscription"},
            })

    # Google Calendar (live) if connected
    creds_dict = request.session.get(GOOGLE_SESSION_KEY)
    if creds_dict:
        try:
            gcreds = Credentials.from_authorized_user_info(
                creds_dict, scopes=creds_dict.get("scopes")
            )
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
                    "id": f"gcal-{ev.get('id')}",
                    "title": ev.get("summary") or "(No title)",
                    "start": start_iso,
                    "end": end_iso,
                    "allDay": all_day,
                    "extendedProps": {"type": "gcal", "htmlLink": ev.get("htmlLink")},
                })
        except Exception:
            pass

    # Health reminders
    if request.user.is_authenticated:
        for r in Reminder.objects.filter(user=request.user):
            events.append({
                "id": f"reminder-{r.id}",
                "title": r.text,
                "start": r.date.isoformat(),
                "allDay": True,
                "extendedProps": {"type": "reminder"},
            })

    return JsonResponse(events, safe=False)

@login_required
def calendar_events_create(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = json.loads(request.body or "{}")
        title = (payload.get("title") or "").strip()
        if not title:
            return HttpResponseBadRequest("Title required")
        start_str = payload.get("start")
        if not start_str:
            return HttpResponseBadRequest("start required")

        all_day = bool(payload.get("allDay", False))
        due_dt = _parse_iso_to_aware(start_str, expect_date_only=all_day)

        task = Task.objects.create(
            user=request.user, title=title, due_date=due_dt, status="pending"
        )
        return JsonResponse({"id": f"task-{task.id}"}, status=201)
    except Exception as e:
        return HttpResponseBadRequest(str(e))

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
            all_day = bool(payload.get("allDay", True))
            task.due_date = _parse_iso_to_aware(start_str, expect_date_only=all_day)

        task.save()
        return JsonResponse({"ok": True, "id": full_id})

    # ---- Subscription ----
    if full_id.startswith("sub-"):
        sub_id = full_id.split("sub-")[-1]
        if _model_has_field(SubscriptionModel, "user"):
            s = get_object_or_404(SubscriptionModel, id=sub_id, user=request.user)
        else:
            s = get_object_or_404(SubscriptionModel, id=sub_id)

        if isinstance(title, str) and title.strip():
            s.name = title.strip()

        if start_str:
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
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])
    try:
        payload = json.loads(request.body or "{}")
        full_id = payload.get("id") or ""
        if not full_id.startswith("task-"):
            return HttpResponseBadRequest("Only tasks can be deleted from the calendar")
        task_id = full_id.split("task-")[-1]
        task = get_object_or_404(Task, id=task_id, user=request.user)
        task.delete()
        return JsonResponse({"ok": True})
    except Exception as e:
        return HttpResponseBadRequest(str(e))

# ---------- other views ----------
@login_required
def add_item(request, item_type):
    if request.method == "POST":
        if item_type == "bill":
            create_kwargs = dict(
                name=request.POST.get("name"),
                cost=request.POST.get("cost"),
                renewal_date=request.POST.get("renewal_date") or None,
                contract_type=request.POST.get("contract_type") or "NA",
                status="active",
            )
            if _model_has_field(Bill, "user"):
                create_kwargs["user"] = request.user
            Bill.objects.create(**create_kwargs)
            return redirect("BillManager")

        elif item_type == "document":
            doc_name = request.POST.get("doc_name")
            uploaded_file = request.FILES.get("upload")
            if uploaded_file:
                Document.objects.create(user=request.user, doc_name=doc_name, file=uploaded_file)
            return redirect("DocumentStorage")

        elif item_type == "subscription":
            create_kwargs = dict(
                name=request.POST.get("name"),
                cost=request.POST.get("cost"),
                renewal_date=request.POST.get("renewal_date") or None,
                contract_type=request.POST.get("contract_type") or "NA",
                status="active",
            )
            if _model_has_field(SubscriptionModel, "user"):
                create_kwargs["user"] = request.user
            SubscriptionModel.objects.create(**create_kwargs)
            return redirect("Subscription")

    return render(request, "add_item.html", {"item_type": item_type})

@login_required
def SubscriptionTracker(request):
    subs_qs = SubscriptionModel.objects.all()
    if _model_has_field(SubscriptionModel, "user"):
        subs_qs = subs_qs.filter(user=request.user)
    total_cost = sum(s.cost for s in subs_qs)
    subs_with_colors = [{"obj": s, "hue": (i + 1) * 60} for i, s in enumerate(subs_qs)]
    return render(request, "Subscription.html", {"subs": subs_with_colors, "total_cost": total_cost})

def TaskManager(request):
    return render(request, "TaskManager.html")

def BillManager(request):
    bills_qs = Bill.objects.all()
    if _model_has_field(Bill, "user"):
        bills_qs = bills_qs.filter(user=request.user)
    total_cost = sum(b.cost for b in bills_qs)
    bills_with_colors = [{"obj": b, "hue": (i + 1) * 60} for i, b in enumerate(bills_qs)]
    return render(request, "BillManager.html", {"bills": bills_with_colors, "total_cost": total_cost})

def LandingPage(request):
    return render(request, "LandingPage.html")

@login_required
def DocumentStorage(request):
    if not request.session.get("document_verified"):
        return redirect("confirm_password")
    documents = Document.objects.filter(user=request.user)
    return render(request, "DocumentStorage.html", {"documents": documents})

@login_required
def delete_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id, user=request.user)
    document.delete()
    return redirect("DocumentStorage")

@login_required
def dashboard(request):
    return render(request, "dashboard.html")

@login_required
def user_profile(request):
    return render(request, "UserProfile.html", {"user": request.user})

@login_required
def confirm_password(request):
    if request.method == "POST":
        password = request.POST.get("password")
        user = authenticate(username=request.user.username, password=password)
        if user is not None:
            request.session["document_verified"] = True
            return redirect("DocumentStorage")
        return render(request, "confirm_password.html", {"error": "Incorrect password."})
    return render(request, "confirm_password.html")

def delete_bill(request, bill_id):
    if request.method == "POST":
        if _model_has_field(Bill, "user"):
            bill = get_object_or_404(Bill, id=bill_id, user=request.user)
        else:
            bill = get_object_or_404(Bill, id=bill_id)
        bill.delete()
    return redirect("BillManager")

@login_required
def delete_sub(request, sub_id):
    if _model_has_field(SubscriptionModel, "user"):
        subscription = get_object_or_404(SubscriptionModel, id=sub_id, user=request.user)
    else:
        subscription = get_object_or_404(SubscriptionModel, id=sub_id)
    subscription.delete()
    return redirect("Subscription")

# ---------- Health Manager (metrics, reminders, Google Fit) ----------
def _rule_based_advice(age, bmi):
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

def google_fit_login(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, "credentials.json"),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.nutrition.read",
            "https://www.googleapis.com/auth/fitness.body.read",
        ],
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    request.session["flow"] = flow.authorization_url
    return redirect(auth_url)

def oauth2callback(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, "credentials.json"),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.nutrition.read",
            "https://www.googleapis.com/auth/fitness.body.read",
        ],
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    credentials = flow.credentials
    # Store as dict for easy restore
    request.session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }
    return redirect("HealthManager")

@login_required
def health_manager(request):
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
                return JsonResponse({"ok": False, "error": "Invalid metric type"}, status=200)

            defaults = {}
            try:
                if metric_type == 'water_intake':
                    defaults['water_intake'] = float(value)
                elif metric_type == 'steps':
                    defaults['steps'] = int(value)
                else:
                    defaults['calories'] = int(value)
            except (TypeError, ValueError):
                return JsonResponse({"ok": False, "error": "Invalid value"}, status=200)

            existing = HealthMetric.objects.filter(user=request.user, date=today).first()
            if existing:
                defaults.setdefault('water_intake', existing.water_intake or 0)
                defaults.setdefault('steps', existing.steps or 0)
                defaults.setdefault('calories', existing.calories or 0)

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

    # Google Fit integration (optional best-effort)
    google_fit_data = {"steps": None, "calories": None, "water_intake": None}
    creds_data = request.session.get("credentials")
    try:
        if creds_data:
            # creds_data may be a dict (our oauth2callback) or a JSON string (older code)
            if isinstance(creds_data, str):
                creds_data = json.loads(creds_data)
            creds = GoogleCredentials.from_authorized_user_info(creds_data, scopes=creds_data.get("scopes"))
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
    except Exception:
        # Swallow fit errors silently (keeps page working even if Fit fails)
        pass

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
    q = request.GET.get('q', '').strip()
    if not q:
        return redirect('HealthManager')
    from urllib.parse import urlencode
    query = f"site:healthdirect.gov.au OR site:who.int OR site:cdc.gov {q}"
    params = urlencode({'q': query})
    return redirect(f"https://www.google.com/search?{params}")

def google_fit_auth(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, "credentials.json"),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.nutrition.read",
            "https://www.googleapis.com/auth/fitness.body.read",
        ],
        redirect_uri="http://localhost:8000/google-fit-callback/"
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    request.session["oauth_state"] = state
    return redirect(auth_url)

@login_required
def google_fit_connect(request):
    flow = Flow.from_client_config(
        _google_flow_config(settings.GOOGLE_FIT_REDIRECT_URI),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.body.read",
            "https://www.googleapis.com/auth/fitness.nutrition.read",
        ],
    )
    flow.redirect_uri = settings.GOOGLE_FIT_REDIRECT_URI

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    request.session["fit_oauth_state"] = state

    return redirect(authorization_url)

@login_required
def google_fit_callback(request):
    expected_state = request.session.get("fit_oauth_state")
    returned_state = request.GET.get("state")

    if not expected_state or expected_state != returned_state:
        request.session.pop("fit_oauth_state", None)
        return redirect("google_fit_connect")

    flow = Flow.from_client_config(
        _google_flow_config(settings.GOOGLE_FIT_REDIRECT_URI),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.body.read",
            "https://www.googleapis.com/auth/fitness.nutrition.read",
        ],
        state=expected_state,
    )
    flow.redirect_uri = settings.GOOGLE_FIT_REDIRECT_URI

    flow.fetch_token(authorization_response=request.build_absolute_uri())
    credentials = flow.credentials

    request.session["google_fit_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }

    return redirect("HealthManager")

@login_required
def edit_reminder(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)
    if request.method == 'POST':
        form = ReminderForm(request.POST, instance=reminder)
        if form.is_valid():
            form.save()
            return redirect('HealthManager')
    else:
        form = ReminderForm(instance=reminder)
    return render(request, "edit_reminder.html", {"form": form})

@login_required
def delete_reminder(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)
    reminder.delete()
    return redirect('HealthManager')

# ---------- Google OAuth (single flow) ----------
def google_connect(request):
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    requested_scopes = request.GET.getlist("scope")
    if not requested_scopes:
        requested_scopes = GOOGLE_ID_SCOPES + GCAL_SCOPES  

    request.session["google_requested_scopes"] = requested_scopes

    flow = Flow.from_client_config(
        _google_flow_config(redirect_uri),
        scopes=requested_scopes,
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
    expected_state = request.session.get("oauth_state")
    returned_state = request.GET.get("state")
    if not expected_state or expected_state != returned_state:
        request.session.pop("oauth_state", None)
        return redirect("google_connect")

    redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Reuse EXACT scopes we initiated with; default to base if missing
    requested_scopes = request.session.pop(
        "google_requested_scopes", GOOGLE_ID_SCOPES + GCAL_SCOPES
    )

    # Important: build Flow without fixing scopes here to avoid
    # oauthlib raising "Scope has changed" if Google returns a different format/order
    flow = Flow.from_client_config(
        _google_flow_config(redirect_uri),
        scopes=None,                 # <-- tolerate returned scope
        state=expected_state,
    )
    flow.redirect_uri = redirect_uri

    flow.fetch_token(
        authorization_response=request.build_absolute_uri(),
        state=expected_state,
    )
    credentials = flow.credentials

    # Identify user via ID token
    idinfo = id_token.verify_oauth2_token(
        credentials.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
    )
    email = idinfo.get("email")
    first = idinfo.get("given_name") or ""
    last = idinfo.get("family_name") or ""

    user, created = User.objects.get_or_create(username=email, defaults={"email": email})
    if created or not user.first_name or not user.last_name or not user.email:
        user.first_name = user.first_name or first
        user.last_name  = user.last_name  or last
        user.email      = user.email      or email
        user.save()

    login(request, user)
    request.session.pop("oauth_state", None)

    # Store creds (record the scopes that were actually granted)
    request.session["google_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes) if getattr(credentials, "scopes", None) else requested_scopes,
        "expiry": credentials.expiry.isoformat() if getattr(credentials, "expiry", None) else None,
    }
    request.session.modified = True

    try:
        _sync_gcal_events_to_tasks(request, creds=credentials)
    except Exception:
        pass

    return redirect("user_profile")

# ---------- Family ----------
@login_required
def family_page(request):
    """
    Render the Family page with real data. If the user owns a family, use that;
    otherwise, use the first family they are a member of.
    """
    family = (
        Family.objects.filter(owner=request.user).first()
        or Family.objects.filter(memberships__user=request.user).first()
    )
    owner = family.owner if family else request.user
    is_owner = bool(family and family.owner_id == request.user.id)

    members = []
    invites = []
    tasks = []
    if family:
        members = family.memberships.select_related("user").order_by("joined_at")
        invites = FamilyInvite.objects.filter(family=family, accepted_at__isnull=True)
        # Recent family tasks
        if _model_has_field(Task, "family"):
            tasks = (
                Task.objects.filter(family=family)
                .select_related('assigned_to')
                .order_by('-created_at')[:10]
            )

    return render(request, "FamilyManager.html", {
        "family": family,
        "owner": owner,
        "members": members,
        "invites": invites,
        "tasks": tasks,
        "families": [family] if family else [],
        "has_family": bool(family),
        "is_owner": is_owner,
    })

@login_required
def FamilyManager(request):
    # Wrapper used by menu route
    return family_page(request)

@login_required
@require_POST
def family_create(request):
    if FamilyMembership.objects.filter(user=request.user).exists():
        messages.info(request, "You already belong to a family.")
        return redirect("FamilyManager")

    name = (request.POST.get("name") or "").strip() or f"{request.user.username}'s Family"
    fam = Family.objects.create(name=name, owner=request.user)
    FamilyMembership.objects.create(user=request.user, family=fam, role="owner")
    messages.success(request, f"Family created: {fam.name}")
    return redirect("FamilyManager")

@login_required
@require_POST
def family_leave(request):
    fam_id = (request.POST.get("family_id") or "").strip()
    if not fam_id:
        messages.error(request, "Missing family id.")
        return redirect("FamilyManager")

    membership = (
        FamilyMembership.objects
        .filter(family_id=fam_id, user=request.user)
        .select_related("family")
        .first()
    )
    if not membership:
        messages.error(request, "You're not a member of that family.")
        return redirect("FamilyManager")

    if membership.family.owner_id == request.user.id or (membership.role or "").lower() == "owner":
        messages.error(request, "Owners can’t leave their own family. Transfer ownership or delete the family.")
        return redirect("FamilyManager")

    membership.delete()
    messages.success(request, "You’ve left the family.")
    return redirect("FamilyManager")

@login_required
@require_POST
def family_delete(request):
    fam_id = (request.POST.get("family_id") or "").strip()
    if not fam_id:
        messages.error(request, "Couldn't find which family to delete.")
        return redirect("FamilyManager")

    family = Family.objects.filter(id=fam_id).first()
    if not family:
        messages.error(request, "That family no longer exists.")
        return redirect("FamilyManager")

    if family.owner_id != request.user.id:
        messages.error(request, "Only the family owner can delete the family.")
        return redirect("FamilyManager")

    FamilyInvite.objects.filter(family=family).delete()
    FamilyMembership.objects.filter(family=family).delete()
    family.delete()
    messages.success(request, "Family deleted.")
    return redirect("FamilyManager")

@login_required
def family_invite_create(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    family = (
        Family.objects.filter(owner=request.user).first()
        or Family.objects.filter(memberships__user=request.user).first()
    )
    if not family:
        messages.error(request, "Create or join a family first.")
        return redirect("FamilyManager")

    if family.owner_id != request.user.id:
        messages.error(request, "Only the family owner can send invites.")
        return redirect("FamilyManager")

    email = (request.POST.get("email") or "").strip().lower()
    role = (request.POST.get("role") or "member").strip().lower()
    if not email:
        return HttpResponseBadRequest("Email required")

    FamilyMembership.objects.get_or_create(
        user=request.user, family=family, defaults={"role": "owner"}
    )

    invite = FamilyInvite.objects.create(
        family=family,
        inviter=request.user,
        email=email,
        role=role,
    )

    join_url = request.build_absolute_uri(reverse("family_join", args=[invite.code]))

    subject = f"You're invited to join {family.name} on LifeFlow"
    text = (
        f"{request.user.username} invited you to join {family.name} on LifeFlow.\n\n"
        f"Join here: {join_url}\n\n"
        f"Link expires on {invite.expires_at.strftime('%Y-%m-%d %H:%M')}."
    )
    html = f"""
        <p><strong>{request.user.username}</strong> invited you to join
        <strong>{family.name}</strong> on LifeFlow.</p>
        <p><a href="{join_url}">Join Family</a></p>
        <p style="color:#666;font-size:12px;">Link expires on {invite.expires_at.strftime('%Y-%m-%d %H:%M')}.</p>
        <p style="color:#999;font-size:12px;">If you didn't expect this, ignore this email.</p>
    """

    msg = EmailMultiAlternatives(subject, text, to=[email])
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)

    messages.success(request, "Invite sent.")
    return redirect("FamilyManager")

@login_required
def family_join(request, code: str):
    invite = (
        FamilyInvite.objects
        .filter(code=code, accepted_at__isnull=True)
        .select_related("family")
        .first()
    )
    if not invite:
        messages.error(request, "That invite is invalid or already used.")
        return redirect("FamilyManager")

    membership, created = FamilyMembership.objects.get_or_create(
        family=invite.family,
        user=request.user,
        defaults={"role": invite.role},
    )
    if not created and invite.role and membership.role != invite.role:
        membership.role = invite.role
        membership.save(update_fields=["role"])

    invite.accepted_by = request.user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_by", "accepted_at"])

    messages.success(request, f"You’ve joined {invite.family.name}.")
    return redirect("FamilyManager")

@login_required
@require_http_methods(["POST"])
def family_join_code(request):
    code = (request.POST.get("invite_code") or "").strip()
    if not code:
        messages.error(request, "Please paste a valid invite code.")
        return redirect("FamilyManager")
    return family_join(request, code)

# ---------- NEW: assign a task to a family member ----------
@login_required
@require_POST
def family_task_assign(request):
    """
    JSON body: { member_id: <FamilyMembership.id>, title: str, due_date?: ISO or YYYY-MM-DD }
    Creates a Task linked to the family and assigned to that member.
    """
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return HttpResponseBadRequest("Invalid JSON")

    member_id = str(payload.get("member_id") or "").strip()
    title = (payload.get("title") or "").strip()
    due = (payload.get("due_date") or "").strip()

    if not member_id or not title:
        return HttpResponseBadRequest("member_id and title are required.")

    membership = (
        FamilyMembership.objects
        .select_related("family", "user")
        .filter(id=member_id)
        .first()
    )
    if not membership:
        return HttpResponseBadRequest("Member not found.")

    # Caller must be in the same family (or the owner)
    fam = membership.family
    same_family = FamilyMembership.objects.filter(family=fam, user=request.user).exists() or fam.owner_id == request.user.id
    if not same_family:
        return HttpResponseBadRequest("Not allowed.")

    due_dt = None
    if due:
        try:
            expect_date_only = len(due) == 10  # 'YYYY-MM-DD'
            due_dt = _parse_iso_to_aware(due, expect_date_only=expect_date_only)
        except Exception:
            return HttpResponseBadRequest("Invalid due date.")

    # Create the task (requires Task to have assigned_to and family FKs)
    task_kwargs = dict(
        user=request.user,
        title=title,
        due_date=due_dt,
        status="pending",
    )
    if _model_has_field(Task, "priority"):
        task_kwargs["priority"] = "medium"
    if _model_has_field(Task, "assigned_to"):
        task_kwargs["assigned_to"] = membership.user
    if _model_has_field(Task, "family"):
        task_kwargs["family"] = fam

    task = Task.objects.create(**task_kwargs)

    return JsonResponse({
        "id": task.id,
        "title": task.title,
        "assigned_to": getattr(task.assigned_to, "username", "") if _model_has_field(Task, "assigned_to") else "",
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "due_date_html": (
            f"<span class=\"date\"> • Due: {timezone.localtime(task.due_date).strftime('%b %e, %I:%M %p')}</span>"
            if task.due_date else ""
        ),
        "priority_html": (
            f"<span class=\"date\"> • {task.get_priority_display()}</span>"
            if _model_has_field(Task, "priority") else ""
        ),
    }, status=201)
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

# -------- AI Helpers -----------

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

# ---------- Health Manager (uses unified Google creds with incremental consent) ----------

@login_required
def health_manager(request):
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
                data['steps'] = data.get('steps') or 0
                data['calories'] = data.get('calories') or 0
                data['water_intake'] = data.get('water_intake') or 0
                HealthMetric.objects.update_or_create(
                    user=request.user, date=today, defaults=data
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

    # BMI/advice
    bmi = profile.bmi()
    bmi_cat = profile.bmi_category()
    advice = _rule_based_advice(profile.age, bmi)

    # ---- Google Fit integration via unified creds ----
    google_fit_data = {"steps": None, "calories": None, "water_intake": None}
    required_scopes = GFIT_SCOPES + GOOGLE_ID_SCOPES
    creds = _load_google_credentials(request)

    if not creds or not _has_required_scopes(creds, required_scopes):
        # ask ONLY for missing scopes (incremental consent)
        scope_params = "&".join(f"scope={s}" for s in required_scopes)
        return redirect(f"/google/connect/?{scope_params}")

    # Build Fitness service and aggregate last 24h
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
            "endTimeMillis": int(end_time.timestamp() * 1000),
        }
    ).execute()

    for bucket in results.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                dtype = point.get("dataTypeName")
                for value in point.get("value", []):
                    if dtype == "com.google.step_count.delta":
                        google_fit_data["steps"] = (google_fit_data["steps"] or 0) + value.get("intVal", 0)
                    elif dtype == "com.google.calories.expended":
                        google_fit_data["calories"] = (google_fit_data["calories"] or 0) + value.get("fpVal", 0.0)
                    elif dtype == "com.google.hydration":
                        google_fit_data["water_intake"] = (google_fit_data["water_intake"] or 0) + value.get("fpVal", 0.0)

    # Save to DB (merge with today_metrics)
    today_metrics = HealthMetric.objects.filter(user=request.user, date=today).first()
    if any(v is not None for v in google_fit_data.values()):
        if today_metrics:
            today_metrics.steps = google_fit_data["steps"] if google_fit_data["steps"] is not None else today_metrics.steps
            today_metrics.calories = google_fit_data["calories"] if google_fit_data["calories"] is not None else today_metrics.calories
            today_metrics.water_intake = google_fit_data["water_intake"] if google_fit_data["water_intake"] is not None else today_metrics.water_intake
            today_metrics.save()
        else:
            HealthMetric.objects.create(
                user=request.user,
                date=today,
                steps=google_fit_data["steps"] or 0,
                calories=google_fit_data["calories"] or 0.0,
                water_intake=google_fit_data["water_intake"] or 0.0,
            )

    context = {
        "profile_form": profile_form,
        "metric_form": metric_form,
        "reminder_form": reminder_form,
        "metrics": HealthMetric.objects.filter(user=request.user, date=today).first(),
        "reminders": reminders,
        "bmi": bmi,
        "bmi_cat": bmi_cat,
        "advice": advice,
        "google_fit_data": google_fit_data,
    }
    return render(request, "HealthManager.html", context)

# ---------- Health search ----------

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

@csrf_exempt
@login_required
def upload_health_data(request):
    """Demo: Inject mock health data for Health Connect / HealthKit."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
        metrics = data.get("metrics", [])
        today = timezone.now().date()

        # Get or create today's record
        today_metric, _ = HealthMetric.objects.get_or_create(
            user=request.user,
            date=today,
            defaults={"steps": 0, "calories": 0, "water_intake": 0},
        )

        for m in metrics:
            mtype = m.get("type")
            value = m.get("value")
            if mtype == "steps":
                today_metric.steps = (today_metric.steps or 0) + int(value)
            elif mtype == "calories":
                today_metric.calories = (today_metric.calories or 0) + int(value)
            elif mtype == "water_intake":
                today_metric.water_intake = (today_metric.water_intake or 0) + float(value)

        today_metric.save()

        return JsonResponse({
            "status": "ok",
            "date": str(today),
            "steps": today_metric.steps,
            "calories": today_metric.calories,
            "water_intake": today_metric.water_intake,
        })
    except Exception as e:
        return HttpResponseBadRequest(str(e))
@login_required
def ingest_health_data(request):
    """
    Placeholder view for ingesting Health Connect / HealthKit data.
    Later you’ll connect APIs here.
    """
    return JsonResponse({"status": "success", "message": "Health data ingestion not yet implemented"})

# AI Integration in Health Manager Page 
_openai_api_key = getattr(settings, "OPENAI_API_KEY", None)
if not _openai_api_key:
    logging.warning("OPENAI_API_KEY not set in settings. OpenAI calls will fail until configured.")
client = OpenAI(api_key=_openai_api_key) if _openai_api_key else None

@login_required
@require_POST
def ai_query(request):
    """Receive AJAX prompt, call OpenAI, and return assistant reply as JSON."""
    try:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)

        prompt = payload.get("prompt", "").strip()
        if not prompt:
            return JsonResponse({"ok": False, "error": "Empty prompt"}, status=400)

        # Build messaging
        system_msg = (
            "You are a concise, helpful health assistant. Provide general advice and "
            "explain calculations where relevant. Always include a brief medical disclaimer."
        )

        profile, _ = UserHealthProfile.objects.get_or_create(user=request.user)
        bmi = profile.bmi() or None
        user_context = f"User: age={profile.age}, height_cm={profile.height_cm}, weight_kg={profile.weight_kg}, bmi={bmi}"

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "system", "content": f"Context: {user_context}"},
            {"role": "user", "content": prompt},
        ]

        # Use a cost-conscious model and token limit for dev
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",   # cheaper for testing; switch to gpt-4* when billing is configured
            messages=messages,
            max_tokens=400,          # reduce tokens to lower cost
            temperature=0.7,
        )

        assistant_text = ""
        if getattr(resp, "choices", None) and len(resp.choices) > 0:
            assistant_text = resp.choices[0].message.content.strip()

        return JsonResponse({"ok": True, "reply": assistant_text})

    except RateLimitError:
        logging.exception("OpenAI rate limit / quota exceeded")
        return JsonResponse({
            "ok": False,
            "error": "OpenAI quota exceeded or rate-limited. Check your billing/usage on the OpenAI dashboard."
        }, status=429)

    except AuthenticationError:
        logging.exception("OpenAI authentication failed (bad API key)")
        return JsonResponse({
            "ok": False,
            "error": "OpenAI authentication failed. Ensure OPENAI_API_KEY is set correctly on the server."
        }, status=401)

    except APIError:
        logging.exception("OpenAI API error")
        return JsonResponse({"ok": False, "error": "OpenAI API error. Try again later."}, status=502)

    except OpenAIError:
        logging.exception("OpenAI generic error")
        return JsonResponse({"ok": False, "error": "OpenAI error occurred."}, status=500)

    except Exception:
        logging.exception("AI query failed (unexpected)")
        return JsonResponse({"ok": False, "error": "Internal server error (see server logs)."}, status=500)