from django.contrib import admin

from .models import ApiToken, Dependency, Item, Project


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("owner", "key", "created_at", "last_used_at")
    readonly_fields = ("key", "created_at", "last_used_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "scope_type", "scope_name", "owner", "created_at")
    list_filter = ("scope_type",)
    search_fields = ("name", "description", "scope_name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "kind", "script_type", "identifier", "owner", "created_at")
    list_filter = ("kind", "script_type", "project", "owner")
    search_fields = ("title", "identifier", "note", "content")
    date_hierarchy = "created_at"


@admin.register(Dependency)
class DependencyAdmin(admin.ModelAdmin):
    list_display = ("from_item", "to_item", "detected_at")
