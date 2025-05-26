from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from .models import Task
from .forms import TaskForm
from django.contrib.auth.decorators import login_required
from .models import Bill
from django.http import JsonResponse
from django.contrib.auth import authenticate, login

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)  # THIS sets the session!
            print(f"[DEBUG] Logged in user: {user.username}")
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('dashboard')
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
            return redirect('task_list')  
    else:
        form = TaskForm()
    return render(request, 'create_task.html', {'form': form})

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

@login_required
def add_item(request, item_type):
    # Your dynamic form logic here
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

def Subscription(request):
    return render(request, 'Subscription.html')

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

def DocumentStorage(request):
    return render(request, 'DocumentStorage.html')

def HealthManager(request):
    return render(request, 'HealthManager.html')

@login_required
def dashboard_view(request):
    print(f"[DEBUG] Current user at dashboard: {request.user}")
    return render(request, 'dashboard.html')

@login_required
def user_profile(request):
    return render(request, 'UserProfile.html', {
        'user': request.user
    })
