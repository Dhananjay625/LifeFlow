from django.shortcuts import render

def login(request):
    return render(request, 'index.html')

def calender(request):
    return render(request, 'calender.html')

def Subscription(request):
    return render(request, 'Subscription.html')

def TaskManager(request):
    return render(request, 'TaskManager.html')