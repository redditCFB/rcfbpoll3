from django.contrib import admin
from django.utils import timezone

from .models import (
    User, UserRole, UserSecondaryAffiliation, ProvisionalUserApplication, Team, Poll, Ballot, ResultSet
)


class RoleInline(admin.TabularInline):
    model = UserRole


class SecondaryAffiliationInline(admin.TabularInline):
    model = UserSecondaryAffiliation


class UserAdmin(admin.ModelAdmin):
    inlines = [RoleInline, SecondaryAffiliationInline]
    list_display = ('username', 'primary_affiliation', 'is_voter', 'is_provisional_voter')
    search_fields = ['username']


admin.site.register(User, UserAdmin)


@admin.action(description='Accept selected applications')
def accept_applications(modeladmin, request, queryset):
    queryset.update(status=ProvisionalUserApplication.Status.ACCEPTED)
    for application in queryset:
        role = UserRole(
            user=application.user,
            role=UserRole.Role.PROVISIONAL,
            start_date=timezone.now()
        )
        role.save()


@admin.action(description='Reject selected applications')
def reject_applications(modeladmin, request, queryset):
    queryset.update(status=ProvisionalUserApplication.Status.REJECTED)


class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_page', 'submission_date', 'status')
    list_filter = ['status']
    actions = ['accept_applications', 'reject_applications']
    ordering = ['-submission_date']


admin.site.register(ProvisionalUserApplication, ApplicationAdmin)
admin.site.register(Team)
admin.site.register(Poll)
admin.site.register(Ballot)
admin.site.register(ResultSet)
