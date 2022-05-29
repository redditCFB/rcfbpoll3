from django.contrib import admin

from .models import User, ProvisionalUserApplication, Team, Poll, Ballot, ResultSet


admin.site.register(User)
admin.site.register(ProvisionalUserApplication)
admin.site.register(Team)
admin.site.register(Poll)
admin.site.register(Ballot)
admin.site.register(ResultSet)
