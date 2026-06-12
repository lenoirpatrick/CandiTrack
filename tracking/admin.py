from django.contrib import admin

from .models import (
    CV,
    ApiToken,
    Candidature,
    Contact,
    Interview,
    JobSite,
    Reminder,
    StatusHistory,
)


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0


class ReminderInline(admin.TabularInline):
    model = Reminder
    extra = 0


class InterviewInline(admin.TabularInline):
    model = Interview
    extra = 0


@admin.register(JobSite)
class JobSiteAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "username", "is_builtin")
    list_filter = ("is_builtin",)
    search_fields = ("name", "url", "username")


@admin.register(Candidature)
class CandidatureAdmin(admin.ModelAdmin):
    list_display = ("entreprise", "poste", "source", "statut", "date_envoi")
    list_filter = ("statut", "source", "site")
    search_fields = ("entreprise", "poste", "notes")
    date_hierarchy = "date_envoi"
    inlines = [StatusHistoryInline, ReminderInline, InterviewInline]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("nom", "entreprise", "email")
    search_fields = ("nom", "entreprise", "email")


@admin.register(CV)
class CVAdmin(admin.ModelAdmin):
    list_display = ("label", "file", "uploaded_at")


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("label", "token", "created_at")
    readonly_fields = ("created_at",)


admin.site.register(StatusHistory)
admin.site.register(Reminder)
admin.site.register(Interview)
