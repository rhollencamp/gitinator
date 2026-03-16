"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path

from gitinator import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),
    path(
        "repos/<str:group_name>/<str:repo_name>/info/refs",
        views.info_refs,
        name="info_refs",
    ),
    path(
        "repos/<str:group_name>/<str:repo_name>/git-upload-pack",
        views.upload_pack,
        name="upload_pack",
    ),
    path(
        "repos/<str:group_name>/<str:repo_name>/git-receive-pack",
        views.receive_pack,
        name="receive_pack",
    ),
    path(
        "repos/<str:group_name>/<str:repo_name>/browse/",
        views.browse,
        name="browse",
    ),
    path(
        "repos/<str:group_name>/<str:repo_name>/browse/<path:path>",
        views.browse,
        name="browse_path",
    ),
]
