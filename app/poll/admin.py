from django.contrib import admin
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from .notifications import send_provisional_application_decision_message
from .reddit_admin import RedditAccountAdmin, RedditRoleAssignmentAdmin
from .models import (
    User, UserRole, UserSecondaryAffiliation, ProvisionalUserApplication, Team, Poll, Ballot, BallotEntry, ResultSet,
    Result, AboutPage, RedditAccount, RedditRoleAssignment
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
    change_list_template = 'admin/poll/user/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('voter-activity/', self.admin_site.admin_view(self.voter_activity_view), name='poll_user_voter_activity'),
        ]
        return custom_urls + urls

    def voter_activity_view(self, request):
        role_by_tab = {'main': UserRole.Role.VOTER, 'provisional': UserRole.Role.PROVISIONAL}
        tab = request.GET.get('tab', 'main')
        if tab not in role_by_tab:
            tab = 'main'

        years = list(Poll.objects.order_by('-year').values_list('year', flat=True).distinct())
        try:
            selected_year = int(request.GET.get('year', years[0] if years else ''))
        except (TypeError, ValueError):
            selected_year = years[0] if years else None
        if selected_year not in years:
            selected_year = years[0] if years else None

        if request.method == 'POST':
            tab = request.POST.get('tab', tab)
            if tab not in role_by_tab:
                tab = 'main'
            try:
                selected_year = int(request.POST.get('year', selected_year))
            except (TypeError, ValueError):
                selected_year = years[0] if years else None
            selected_user_ids = request.POST.getlist('users')
            removed_count = UserRole.objects.filter(
                user_id__in=selected_user_ids, role=role_by_tab[tab], end_date__isnull=True,
            ).update(end_date=timezone.now())
            if removed_count:
                messages.success(request, f'Removed {removed_count} active voter role(s).')
            else:
                messages.warning(request, 'No active voter roles were selected.')
            return redirect('%s?tab=%s&year=%s' % (
                reverse('admin:poll_user_voter_activity'), tab, selected_year or ''
            ))

        ballot_filters = Q(
            user__ballot__poll__year=selected_year,
            user__ballot__submission_date__isnull=False,
            user__ballot__user_type=role_by_tab[tab],
        )
        voters = (
            UserRole.objects.filter(role=role_by_tab[tab], end_date__isnull=True)
            .values('user_id', 'user__username')
            .annotate(
                poll_count=Count('user__ballot__poll', filter=ballot_filters, distinct=True),
                required_poll_count=Count(
                    'user__ballot__poll', filter=ballot_filters & Q(user__ballot__poll__required=True), distinct=True,
                ),
            ).order_by('user__username')
        )
        context = {
            **self.admin_site.each_context(request), 'title': 'Voter activity', 'opts': self.model._meta,
            'active_tab': tab, 'years': years, 'selected_year': selected_year, 'voters': voters,
        }
        return TemplateResponse(request, 'admin/poll/user/voter_activity.html', context)


admin.site.register(User, UserAdmin)


@admin.action(description='Accept selected applications')
def accept_applications(model_admin, request, queryset):
    applications = list(queryset.filter(status=ProvisionalUserApplication.Status.OPEN))
    for application in applications:
        application.status = ProvisionalUserApplication.Status.ACCEPTED
        application.save(update_fields=['status'])
        role = UserRole(
            user=application.user,
            role=UserRole.Role.PROVISIONAL,
            start_date=timezone.now()
        )
        role.save()
    _send_decision_messages(model_admin, request, applications)


@admin.action(description='Reject selected applications')
def reject_applications(model_admin, request, queryset):
    applications = list(queryset.filter(status=ProvisionalUserApplication.Status.OPEN))
    for application in applications:
        application.status = ProvisionalUserApplication.Status.REJECTED
        application.save(update_fields=['status'])
    _send_decision_messages(model_admin, request, applications)


def _send_decision_messages(model_admin, request, applications):
    failed = [application for application in applications if not send_provisional_application_decision_message(application)]
    if failed:
        model_admin.message_user(
            request,
            'The decision was saved, but Reddit notifications could not be sent to: %s.' %
            ', '.join(application.user.username for application in failed),
            level='warning',
        )


class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_page', 'submission_date', 'status')
    list_filter = ['status']
    actions = [accept_applications, reject_applications]
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


class PollAdmin(admin.ModelAdmin):
    inlines = [ResultSetInline]
    list_display = ('year', 'week', 'required', 'open_date', 'publish_date', 'last_week')
    list_filter = ('required',)
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
admin.site.register(RedditAccount, RedditAccountAdmin)
admin.site.register(RedditRoleAssignment, RedditRoleAssignmentAdmin)
