from django.contrib import admin

from .models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "language", "owner", "created_at")
    list_filter = ("kind", "language", "owner")
    search_fields = ("title", "note", "content")
    date_hierarchy = "created_at"
