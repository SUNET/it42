from django.contrib import admin

from .models import OutboxEvent, ProcessedEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "exchange", "occurred_at", "published_at", "attempts")
    list_filter = ("type", "exchange")
    readonly_fields = [f.name for f in OutboxEvent._meta.fields]


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "type", "queue", "processed_at")
    list_filter = ("type", "queue")
    readonly_fields = ("event_id", "type", "queue", "processed_at")
