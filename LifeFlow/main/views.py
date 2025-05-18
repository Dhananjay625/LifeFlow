<<<<<<< HEAD
from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from .models import Task
from .forms import TaskForm
from django.contrib.auth.decorators import login_required
from .models import Bill


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        try:
            user = User.objects.get(username=username)
            print("User found:", user.username)
            print("Entered:", password)
            print("In DB:", user.password)
            print("Match:", check_password(password, user.password))

            if check_password(password, user.password):
                return redirect('calender')
            else:
                return render(request, 'index.html', {'error': 'Invalid username or password.'})
        except User.DoesNotExist:
            return render(request, 'index.html', {'error': 'Invalid username or password.'})
=======
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
>>>>>>> dashboard

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

<<<<<<< HEAD
def HealthManager(request):
    return render(request, 'HealthManager.html')
=======
@login_required
def dashboard(request):
    return render(request, 'dashboard.html')
>>>>>>> dashboard
