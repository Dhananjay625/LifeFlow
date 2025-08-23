from datetime import date, datetime, timedelta
from calendar import monthrange
import calendar as cal
import json
import os
import secrets
from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    JsonResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponse,
)
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

User = get_user_model()


@login_required
def home(request):
    return render(request, 'appboard/home.html')

# Mining news function
def home(request):
    entries = []
    news_url = "https://www.mining.com"  # news site
    rss_url = "https://www.mining.com/feed/"  # news feed url

    try:
        response = requests.get(rss_url)
        root = ElementTree.fromstring(response.content)

        # Parse RSS feed items
        for item in root.findall('.//item')[:5]:  # Get first 5 items
            entry = {
                'title': item.find('title').text,
                'link': item.find('link').text,
                'description': item.find('description').text
            }
            entries.append(entry)

    except Exception as e:
        entries = []  # Handle error/empty state

    context = {
        'rss_feed': entries,
        'news_url': news_url
    }
    return render(request, 'appboard/home.html', context)

@csrf_exempt          # TODO: remove in production and send CSRF token from the page
@require_POST
def file_uploader(request):
    """
    Accepts a multipart/form-data upload from <form ... enctype="multipart/form-data">.
    Saves the file to MEDIA_ROOT/tmp and returns a JSON payload with a path you
    can pass to mapplotter.
    """
    f = (
        request.FILES.get("uploaded_file")
        or request.FILES.get("file")
        or request.FILES.get("datafile")
    )
    if not f:
        return HttpResponseBadRequest("No file uploaded")

    tmp_dir = os.path.join(settings.MEDIA_ROOT, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    filename = f"{uuid.uuid4()}_{f.name}"
    dest_path = os.path.join(tmp_dir, filename)
    with open(dest_path, "wb+") as dest:
        for chunk in f.chunks():
            dest.write(chunk)

    # relative path your frontend can use / pass to mapplotter
    rel_path = f"{settings.MEDIA_URL.lstrip('/')}" + f"tmp/{filename}"
    return JsonResponse(
        {
            "ok": True,
            "filename": f.name,
            "filepath": rel_path,   # e.g. "media/tmp/uuid_original.ext"
        }
    )


@csrf_exempt          # TODO: remove in production and send CSRF token from the page
@require_POST
def mapplotter(request):
    """
    Placeholder endpoint: expects JSON like {"filepath": "..."}.
    Returns it back so the template JS can proceed without errors.
    Replace with real logic later.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    return JsonResponse({"ok": True, "received": payload})