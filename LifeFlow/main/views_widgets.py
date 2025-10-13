from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from .models import Task, Bill, sub, Document, CalendarEvent, HealthMetric, FamilyMembership, Family
from datetime import datetime



@login_required
def kanban_summary(request):
    qs = Task.objects.filter(user=request.user)
    counts = qs.values('status').annotate(total=Count('id'))
    summary = {item['status']: item['total'] for item in counts}
    return JsonResponse({'summary': summary})

@login_required
def calendar_events(request):
    events = []
    tasks_qs = Task.objects.filter(user=request.user).exclude(due_date__isnull=True)

    for t in tasks_qs:
        due_date = t.due_date
        if isinstance(due_date, datetime):
            due_date = localtime(due_date).isoformat()
        else:
            due_date = str(due_date)

        events.append({
            "id": f"task-{t.id}",
            "title": t.title,
            "start": due_date,
            "allDay": True,
            "extendedProps": {
                "type": "task",
                "status": t.status,
                "priority": getattr(t, "priority", ""),
            },
        })


    print("Current User:", user)
    print("Family IDs:", list(family_user_ids))
    print("All Events:", list(CalendarEvent.objects.all().values()))
    print("Future Events for this user/family:", list(events.values()))    
    print("Returning Events:", event_list)
    return JsonResponse(event_data, safe=False)

@login_required
def bills_summary(request):
    upcoming = Bill.objects.filter(status='active').order_by('renewal_date')[:3]
    data = [{"name": b.name, "cost": str(b.cost), "renewal": b.renewal_date.strftime("%Y-%m-%d") if b.renewal_date else None} for b in upcoming]
    return JsonResponse({"bills": data})


@login_required
def subscriptions_summary(request):
    subscriptions = sub.objects.filter(status='active').order_by('renewal_date')[:5]

    data = {
        "subscriptions": [
            {
                "name": s.name,
                "cost": str(s.cost),
                "renewal": s.renewal_date.strftime("%Y-%m-%d") if s.renewal_date else None,
                "contract_type": s.contract_type,
                "status": s.status,
            }
            for s in subscriptions
        ]
    }

    return JsonResponse(data)

@login_required
def dashboard_summary(request):
    data = {
        "summary": {
            "kanban": 5,
            "calendar_events": 3,
            "bills_due": 2,
            "documents": 4,
        }
    }
    return JsonResponse(data)

@login_required
def documents_summary(request):
    data = {
        "documents": [
            {"name": "contract.pdf", "uploaded": "2025-09-15"},
            {"name": "notes.docx", "uploaded": "2025-09-20"},
        ]
    }

@login_required
def health_summary(request):
    latest = HealthMetric.objects.filter(user=request.user).order_by('-date').first()
    if not latest:
        return JsonResponse({"metrics": None})
    data = {
        "date": latest.date.strftime("%Y-%m-%d"),
        "water": latest.water_intake,
        "steps": latest.steps,
        "calories": latest.calories,
    }
    return JsonResponse({"metrics": data})

@login_required
def family_summary(request):
    memberships = FamilyMembership.objects.filter(user=request.user)
    families = [{"name": m.family.name, "role": m.role} for m in memberships]
    return JsonResponse({"families": families})

@login_required
def calendar_events(request):
    events = []

    for t in Task.objects.filter(user=request.user).exclude(due_date__isnull=True).values(
        "id", "title", "due_date", "status", "priority"
    ):
        events.append({
            "id": f"task-{t['id']}",
            "title": t["title"],
            "start": t["due_date"].isoformat() if isinstance(t["due_date"], datetime) else t["due_date"],
            "allDay": True,
            "extendedProps": {
                "type": "task",
                "status": t["status"],
                "priority": t["priority"]
            },
        })

    return JsonResponse(events, safe=False)