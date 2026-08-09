from django import forms

from .models import RedditRoleAssignment


class RedditAccountConnectForm(forms.Form):
    roles = forms.MultipleChoiceField(
        choices=RedditRoleAssignment.Role.choices,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label='Roles',
    )
