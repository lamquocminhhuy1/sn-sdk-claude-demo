from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from vault import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.project_list, name="project_list"),
    path("projects/new/", views.project_create, name="project_create"),
    path("p/<slug:slug>/", views.project_detail, name="project_detail"),
    path("p/<slug:slug>/edit/", views.project_edit, name="project_edit"),
    path("p/<slug:slug>/delete/", views.project_delete, name="project_delete"),
    path("p/<slug:slug>/deps/", views.project_dependencies, name="project_dependencies"),
    path("p/<slug:slug>/new/", views.item_create, name="item_create"),
    path("item/<uuid:uid>/", views.item_detail, name="item_detail"),
    path("item/<uuid:uid>/edit/", views.item_edit, name="item_edit"),
    path("item/<uuid:uid>/delete/", views.item_delete, name="item_delete"),
    path("item/<uuid:uid>/raw/", views.item_raw, name="item_raw"),
    path("media/<path:path>", views.serve_media, name="serve_media"),
]
