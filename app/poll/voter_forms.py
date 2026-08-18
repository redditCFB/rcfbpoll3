import re

from django import forms


class UsernameInputError(ValueError):
    """Raised when pasted username input contains an unsupported value."""


def parse_usernames(value):
    """Return unique usernames in first-seen order, preserving supplied spelling."""
    usernames = []
    seen = set()
    for supplied in re.split(r'[,\r\n]', value or ''):
        username = supplied.strip()
        if not username:
            continue
        if username.casefold().startswith('u/'):
            raise UsernameInputError('Enter Reddit usernames without the leading "u/".')
        key = username.casefold()
        if key not in seen:
            seen.add(key)
            usernames.append(username)
    return usernames


class BulkPromotionForm(forms.Form):
    usernames = forms.CharField(
        label='Usernames',
        widget=forms.Textarea(attrs={'class': 'vLargeTextField', 'rows': 12, 'cols': 80}),
        help_text='Paste one username per line, or separate usernames with commas. Do not include the leading "u/".',
    )

    def clean_usernames(self):
        try:
            usernames = parse_usernames(self.cleaned_data['usernames'])
        except UsernameInputError as error:
            raise forms.ValidationError(str(error)) from error
        if not usernames:
            raise forms.ValidationError('Enter at least one username.')
        return usernames
