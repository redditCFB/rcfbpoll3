import secrets

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import RedditAccount, RedditRoleAssignment
from .reddit_forms import RedditAccountConnectForm
from .reddit_integration import RedditIntegrationError, oauth_client, required_scopes_for_roles


PENDING_OAUTH_SESSION_KEY = 'reddit_automation_oauth'


def _superuser_required(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied


class RedditAccountAdmin(admin.ModelAdmin):
    list_display = ('username', 'roles_display', 'scopes_display', 'scope_status', 'authorized_at', 'last_verified_at', 'reauthorize_link')
    search_fields = ('username',)
    readonly_fields = ('username', 'granted_scopes', 'authorized_at', 'last_verified_at', 'created_at', 'updated_at')
    exclude = ('encrypted_refresh_token',)
    change_list_template = 'admin/poll/redditaccount/change_list.html'

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description='Roles')
    def roles_display(self, obj):
        return ', '.join(a.get_role_display() for a in obj.role_assignments.all()) or '—'

    @admin.display(description='Granted scopes')
    def scopes_display(self, obj):
        return ', '.join(sorted(obj.granted_scopes or [])) or '—'

    @admin.display(description='Scope status')
    def scope_status(self, obj):
        missing = set()
        for assignment in obj.role_assignments.all():
            missing.update(required_scopes_for_roles((assignment.role,)) - set(obj.granted_scopes or []))
        if missing:
            return format_html('<span style="color: #ba2121">Reauthorization needed: {}</span>', ', '.join(sorted(missing)))
        return 'Ready'

    @admin.display(description='Actions')
    def reauthorize_link(self, obj):
        url = reverse('admin:poll_redditaccount_reauthorize', args=(obj.pk,))
        return format_html('<a href="{}">Reauthorize</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('connect/', self.admin_site.admin_view(self.connect_view), name='poll_redditaccount_connect'),
            path('oauth/callback/', self.admin_site.admin_view(self.oauth_callback), name='poll_redditaccount_oauth_callback'),
            path('<int:object_id>/reauthorize/', self.admin_site.admin_view(self.reauthorize_view), name='poll_redditaccount_reauthorize'),
        ]
        return custom_urls + urls

    def _start_oauth(self, request, roles, account_id=None):
        try:
            client = oauth_client()
            state = secrets.token_urlsafe(32)
            request.session[PENDING_OAUTH_SESSION_KEY] = {
                'state': state, 'roles': list(roles), 'account_id': account_id,
            }
            request.session.modified = True
            authorization_url = client.auth.url(
                scopes=sorted(required_scopes_for_roles(roles)), state=state, duration='permanent'
            )
        except RedditIntegrationError as exc:
            messages.error(request, str(exc))
            return redirect('admin:poll_redditaccount_changelist')
        return redirect(authorization_url)

    def connect_view(self, request):
        _superuser_required(request)
        form = RedditAccountConnectForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            return self._start_oauth(request, form.cleaned_data['roles'])
        context = {**self.admin_site.each_context(request), 'title': 'Connect Reddit account', 'form': form, 'opts': self.model._meta}
        return TemplateResponse(request, 'admin/poll/redditaccount/connect.html', context)

    def reauthorize_view(self, request, object_id):
        _superuser_required(request)
        account = self.get_object(request, object_id)
        if account is None:
            raise PermissionDenied
        roles = list(account.role_assignments.values_list('role', flat=True))
        if not roles:
            messages.error(request, 'Assign at least one role before reauthorizing this account.')
            return redirect('admin:poll_redditaccount_changelist')
        return self._start_oauth(request, roles, account_id=account.pk)

    def oauth_callback(self, request):
        _superuser_required(request)
        pending = request.session.pop(PENDING_OAUTH_SESSION_KEY, None)
        if not pending or not secrets.compare_digest(request.GET.get('state', ''), pending['state']):
            messages.error(request, 'The Reddit authorization state was invalid or expired.')
            return redirect('admin:poll_redditaccount_changelist')
        if request.GET.get('error'):
            messages.error(request, 'Reddit authorization was cancelled or denied.')
            return redirect('admin:poll_redditaccount_changelist')
        code = request.GET.get('code')
        if not code:
            messages.error(request, 'Reddit did not return an authorization code.')
            return redirect('admin:poll_redditaccount_changelist')
        try:
            client = oauth_client()
            refresh_token = client.auth.authorize(code)
            identity = client.user.me()
            if identity is None or not getattr(identity, 'name', None):
                raise RedditIntegrationError('Reddit did not return an authenticated account identity.')
            scopes = set(client.auth.scopes()) if callable(getattr(client.auth, 'scopes', None)) else set()
            if not scopes:
                scopes = set(required_scopes_for_roles(pending['roles']))
            account = RedditAccount.objects.filter(pk=pending.get('account_id')).first() if pending.get('account_id') else None
            if account and account.username.lower() != identity.name.lower():
                raise RedditIntegrationError('Reauthorization authenticated a different Reddit account.')
            if account is None:
                account, _ = RedditAccount.objects.get_or_create(username=identity.name)
            account.set_refresh_token(refresh_token)
            account.granted_scopes = sorted(scopes)
            account.authorized_at = timezone.now()
            account.last_verified_at = timezone.now()
            account.save()
            for role in pending['roles']:
                RedditRoleAssignment.objects.update_or_create(role=role, defaults={'account': account})
        except RedditIntegrationError as exc:
            messages.error(request, str(exc))
            return redirect('admin:poll_redditaccount_changelist')
        except Exception:
            messages.error(request, 'Reddit authorization could not be completed.')
            return redirect('admin:poll_redditaccount_changelist')
        messages.success(request, 'Connected as u/%s.' % account.username)
        return redirect('admin:poll_redditaccount_changelist')


class RedditRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('role', 'account')
    list_filter = ('role',)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
