from django.contrib import admin
from django.utils import timezone

from .models import (
    User, UserRole, UserSecondaryAffiliation, ProvisionalUserApplication, Team, Poll, Ballot, BallotEntry, ResultSet,
    Result, AboutPage
)


class RoleInline(admin.TabularInline):
    model = UserRole
    extra = 0


class SecondaryAffiliationInline(admin.TabularInline):
    model = UserSecondaryAffiliation
    extra = 0


class UserAdmin(admin.ModelAdmin):
    inlines = [RoleInline, SecondaryAffiliationInline]
    readonly_fields = ('is_voter', 'is_provisional_voter')
    list_display = ('username', 'primary_affiliation', 'is_voter', 'is_provisional_voter')
    search_fields = ['username']


admin.site.register(User, UserAdmin)


@admin.action(description='Accept selected applications')
def accept_applications(model_admin, request, queryset):
    queryset.update(status=ProvisionalUserApplication.Status.ACCEPTED)
    for application in queryset:
        role = UserRole(
            user=application.user,
            role=UserRole.Role.PROVISIONAL,
            start_date=timezone.now()
        )
        role.save()


@admin.action(description='Reject selected applications')
def reject_applications(model_admin, request, queryset):
    queryset.update(status=ProvisionalUserApplication.Status.REJECTED)


class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_page', 'submission_date', 'status')
    list_filter = ['status']
    actions = ['accept_applications', 'reject_applications']
    ordering = ['-submission_date']


admin.site.register(ProvisionalUserApplication, ApplicationAdmin)


class TeamAdmin(admin.ModelAdmin):
    list_display = ('handle', 'name', 'conference', 'division', 'use_for_ballot', 'short_name')
    search_fields = ['handle', 'name', 'conference', 'division', 'short_name']


admin.site.register(Team, TeamAdmin)


class ResultSetInline(admin.TabularInline):
    model = ResultSet
    show_change_link = True
    extra = 0


class BallotInLine(admin.TabularInline):
    model = Ballot
    show_change_link = True
    readonly_fields = ('is_submitted',)
    fields = ('user', 'poll_type', 'is_submitted')
    extra = 0


class PollAdmin(admin.ModelAdmin):
    inlines = [ResultSetInline, BallotInLine]
    list_display = ('year', 'week', 'open_date', 'publish_date', 'last_week')
    ordering = ['publish_date']


admin.site.register(Poll, PollAdmin)


class BallotEntryInline(admin.TabularInline):
    model = BallotEntry
    extra = 0


class BallotAdmin(admin.ModelAdmin):
    inlines = [BallotEntryInline]
    readonly_fields = ('is_submitted',)
    list_display = ('poll', 'user', 'poll_type', 'is_submitted')
    search_fields = ['poll', 'user']
    ordering = ['-poll', 'user']


admin.site.register(Ballot, BallotAdmin)


class ResultInLine(admin.TabularInline):
    model = Result
    extra = 0


class ResultSetAdmin(admin.ModelAdmin):
    inlines = [ResultInLine]
    list_display = (
        'poll', 'time_calculated', 'human', 'computer', 'hybrid', 'main', 'provisional',
        'before_ap', 'after_ap'
    )


admin.site.register(ResultSet, ResultSetAdmin)
admin.site.register(AboutPage)
