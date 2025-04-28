from django.shortcuts import render

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
