from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from .models import Task
from .forms import TaskForm
from django.contrib.auth.decorators import login_required
from .models import Bill
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from django.contrib.auth import authenticate
from django.shortcuts import redirect, get_object_or_404
from .models import Bill
from .models import Document
from django.shortcuts import get_object_or_404, redirect
from .models import sub
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from .models import HealthMetric, Reminder, UserHealthProfile
from .forms import HealthMetricForm, HealthProfileForm, ReminderForm
from django.utils import timezone
from urllib.parse import urlencode


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)  # THIS sets the session!
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('calender')
        else:
            return render(request, 'index.html', {'error': 'Invalid username or password.'})

    return render(request, 'index.html')

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


        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        print("sa", password)

        return redirect('login')

    return render(request, 'register.html')

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
    
    return render(request, 'add_item.html', {
        'form': form,
        'item_type': 'task'  
    })


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


def calender(request):
    return render(request, 'calender.html')

from .models import Bill, Document
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Bill, Document, sub

@login_required
def add_item(request, item_type):
    if request.method == 'POST':
        if item_type == 'bill':
            name = request.POST.get('name')
            cost = request.POST.get('cost')
            renewal_date = request.POST.get('renewal_date') or None
            contract_type = request.POST.get('contract_type') or 'NA'
            add_to_calendar = request.POST.get('add_to_calendar')

            status = 'active'

            Bill.objects.create(
                name=name,
                cost=cost,
                renewal_date=renewal_date,
                contract_type=contract_type,
                status=status
            )
            return redirect('BillManager')

        elif item_type == 'document':
            doc_name = request.POST.get('doc_name')
            uploaded_file = request.FILES.get('upload')

            if uploaded_file:
                Document.objects.create(
                    user=request.user,
                    doc_name=doc_name,
                    file=uploaded_file
                )
            return redirect('DocumentStorage')

        elif item_type == 'subscription':  # ✅ make sure the URL matches this
            name = request.POST.get('name')
            cost = request.POST.get('cost')
            renewal_date = request.POST.get('renewal_date') or None
            contract_type = request.POST.get('contract_type') or 'NA'
            add_to_calendar = request.POST.get('add_to_calendar')

            status = 'active'

            sub.objects.create(
                name=name,
                cost=cost,
                renewal_date=renewal_date,
                contract_type=contract_type,
                status=status
            )
            return redirect('Subscription')  # ✅ redirect to the correct tracker

    return render(request, 'add_item.html', {'item_type': item_type})



@login_required
def calendar_events(request):
    tasks = Task.objects.filter(user=request.user).values(
        'title', 'due_date', 'status', 'priority'
    )
    bills = Bill.objects.filter(status='active').values(
        'name', 'renewal_date', 'cost'
    )

    events = []
    for task in tasks:
        events.append({
            'title': task['title'],
            'start': task['due_date'],
            'type': 'task',
            'status': task['status'],
            'priority': task['priority'],
        })

    for bill in bills:
        events.append({
            'title': f"{bill['name']} Renewal (${bill['cost']})",
            'start': bill['renewal_date'],
            'type': 'subscription',
        })

    return JsonResponse(events, safe=False)

@login_required
def SubscriptionTracker(request):
    subs = sub.objects.all()
    total_cost = sum(b.cost for b in subs)
    
    # Annotate bills with a "hue" field for coloring
    subs_with_colors = [
        {
            "obj": sub,
            "hue": (index + 1) * 60
        }
        for index, sub in enumerate(subs)
    ]
    
    return render(request, 'Subscription.html', {
        'subs': subs_with_colors,
        'total_cost': total_cost
    })

def TaskManager(request):
    return render(request, 'TaskManager.html')

def BillManager(request):
    bills = Bill.objects.all()
    total_cost = sum(b.cost for b in bills)
    
    # Annotate bills with a "hue" field for coloring
    bills_with_colors = [
        {
            "obj": bill,
            "hue": (index + 1) * 60
        }
        for index, bill in enumerate(bills)
    ]
    
    return render(request, 'BillManager.html', {
        'bills': bills_with_colors,
        'total_cost': total_cost
    })

def LandingPage(request):
    return render(request, 'LandingPage.html')


@login_required
def DocumentStorage(request):
    if not request.session.get('document_verified'):
        return redirect('confirm_password')
    
    documents = Document.objects.all()
    return render(request, 'DocumentStorage.html', {'documents': documents})


@login_required
def delete_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)
    document.delete()
    return redirect('DocumentStorage')

def HealthManager(request):
    return render(request, 'HealthManager.html')
@login_required
def dashboard(request):
    return render(request, 'dashboard.html')

@login_required
def user_profile(request):
    return render(request, 'UserProfile.html', {
        'user': request.user
    })

@login_required
def confirm_password(request):
    if request.method == 'POST':
        password = request.POST.get('password')
        user = authenticate(username=request.user.username, password=password)
        if user is not None:
            request.session['document_verified'] = True
            return redirect('DocumentStorage')
        else:
            return render(request, 'confirm_password.html', {'error': 'Incorrect password.'})
    return render(request, 'confirm_password.html')


def delete_bill(request, bill_id):
    if request.method == 'POST':
        bill = get_object_or_404(Bill, id=bill_id)
        bill.delete()
    return redirect('BillManager')

from django.shortcuts import get_object_or_404

@login_required
def delete_sub(request, sub_id):
    subscription = get_object_or_404(sub, id=sub_id)
    subscription.delete()
    return redirect('Subscription')

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

@login_required
def health_manager(request):
    # Ensure profile exists
    profile, _ = UserHealthProfile.objects.get_or_create(user=request.user)

    # Latest metrics for quick display
    today = timezone.now().date()
    today_metrics = HealthMetric.objects.filter(user=request.user, date=today).first()
    reminders = Reminder.objects.filter(user=request.user).order_by('-date')[:7]

    # Forms
    metric_form = HealthMetricForm(initial={
        'water_intake': getattr(today_metrics, 'water_intake', ''),
        'steps': getattr(today_metrics, 'steps', ''),
        'calories': getattr(today_metrics, 'calories', ''),
    })
    profile_form = HealthProfileForm(instance=profile)
    reminder_form = ReminderForm()

    # POST handlers
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
                HealthMetric.objects.update_or_create(
                    user=request.user,
                    date=today,
                    defaults=data
                )
                return redirect('HealthManager')

        elif 'quick_metric' in request.POST:
            # Quick add individual metric from chips
            metric_type = request.POST.get('metric_type')  # 'water_intake' | 'steps' | 'calories'
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

            # Keep any existing values
            existing = HealthMetric.objects.filter(user=request.user, date=today).first()
            if existing:
                defaults.setdefault('water_intake', existing.water_intake)
                defaults.setdefault('steps', existing.steps)
                defaults.setdefault('calories', existing.calories)

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

    bmi = profile.bmi()
    bmi_cat = profile.bmi_category()
    advice = _rule_based_advice(profile.age, bmi)

    context = {
        'profile_form': profile_form,
        'metric_form': metric_form,
        'reminder_form': reminder_form,
        'metrics': today_metrics,
        'reminders': reminders,
        'bmi': bmi,
        'bmi_cat': bmi_cat,
        'advice': advice,
    }
    return render(request, 'HealthManager.html', context)

@login_required
def health_search(request):
    """
    Redirects to a trusted health site search in a new tab based on query.
    You can change domains below to your preference.
    """
    q = request.GET.get('q', '').strip()
    if not q:
        return redirect('HealthManager')
    # Example: search across reputable sources
    # Using Google with site filters for consumer-friendly info
    query = f"site:healthdirect.gov.au OR site:who.int OR site:cdc.gov {q}"
    params = urlencode({'q': query})
    return redirect(f"https://www.google.com/search?{params}")