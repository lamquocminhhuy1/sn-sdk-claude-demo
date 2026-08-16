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
    path("", views.item_list, name="item_list"),
    path("new/", views.item_create, name="item_create"),
    path("item/<int:pk>/", views.item_detail, name="item_detail"),
    path("item/<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("item/<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("item/<int:pk>/raw/", views.item_raw, name="item_raw"),
    path("media/<path:path>", views.serve_media, name="serve_media"),
]
