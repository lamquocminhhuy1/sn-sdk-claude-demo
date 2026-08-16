from django.contrib import admin

from .models import Dependency, Item, Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "created_at")
    search_fields = ("name", "description")
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
