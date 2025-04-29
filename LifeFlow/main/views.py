from django.shortcuts import render
from django.contrib.auth.decorators import login_required

def login(request):
    return render(request, 'index.html')

def calender(request):
    return render(request, 'calender.html')

def Subscription(request):
    return render(request, 'Subscription.html')

def TaskManager(request):
    return render(request, 'TaskManager.html')

def BillManager(request):
    return render(request, 'BillManager.html')

def register(request):
    return render(request, 'register.html')

def LandingPage(request):
    return render(request, 'LandingPage.html')

def DocumentStorage(request):
    return render(request, 'DocumentStorage.html')

@login_required
def dashboard(request):
    return render(request, 'dashboard.html')
