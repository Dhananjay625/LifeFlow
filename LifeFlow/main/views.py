from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User

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


def calender(request):
    return render(request, 'calender.html')

def Subscription(request):
    return render(request, 'Subscription.html')

def TaskManager(request):
    return render(request, 'TaskManager.html')

def BillManager(request):
    return render(request, 'BillManager.html')

def LandingPage(request):
    return render(request, 'LandingPage.html')

def DocumentStorage(request):
    return render(request, 'DocumentStorage.html')
