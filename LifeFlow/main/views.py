# stdlib
from datetime import date, datetime, timedelta
from calendar import monthrange
import calendar as cal
import json
import os
import secrets

# django
from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
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

# google api
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials as GoogleCredentials
from google.auth.transport import requests as google_requests
from google.auth.exceptions import RefreshError

# local
from .forms import TaskForm
from .models import Bill, Document, Task
from .models import Family, FamilyMembership, FamilyInvite
from django.core.mail import EmailMultiAlternatives

# Health manager bits
from .models import HealthMetric, Reminder, UserHealthProfile
from .forms import HealthMetricForm, HealthProfileForm, ReminderForm

# Support either Subscription or sub model names
try:
    from .models import Subscription as SubscriptionModel
except Exception:
    from .models import sub as SubscriptionModel

User = get_user_model()

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

GCAL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar",
]

def _sync_gcal_events_to_tasks(request, max_results=50, creds=None):
    """
    Pull upcoming Google events and upsert into Task table.
    If creds is provided, use it (fresh from callback). Otherwise rebuild from session.
    """
    if creds is None:
        creds_dict = request.session.get("google_credentials")
        if not creds_dict or not request.user.is_authenticated:
            return
        creds = GoogleCredentials.from_authorized_user_info(
            creds_dict, scopes=creds_dict.get("scopes")
        )
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
def calendar_events(request):
    events = []

    # Tasks (one-off)
    for t in Task.objects.filter(user=request.user).exclude(due_date__isnull=True).values(
        "id", "title", "due_date", "status", "priority"
    ):
        events.append({
            "id": f"task-{t['id']}",
            "title": t["title"],
            "start": t["due_date"].isoformat() if isinstance(t["due_date"], datetime) else t["due_date"],
            "allDay": True,
            "extendedProps": {"type": "task", "status": t["status"], "priority": t["priority"]},
        })

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
    creds_dict = request.session.get("google_credentials")
    if creds_dict:
        try:
            gcreds = GoogleCredentials.from_authorized_user_info(
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
            # token errors etc — ignore gracefully
            pass

    # Health reminders on the calendar (optional)
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
