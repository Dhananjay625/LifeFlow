from django.shortcuts import render

def login(request):
    return render(request, 'index.html')

def calender(request):
    return render(request, 'calender.html')