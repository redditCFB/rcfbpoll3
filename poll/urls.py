from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('poll/', views.poll_index, name='poll_index'),
    path('poll/this_week/', views.this_week, name='this_week'),
    path('poll/last_week/', views.last_week, name='last_week'),
    path('poll/view/<int:poll_id>/', views.poll_view, name='poll_view'),
    path('poll/view/<int:poll_id>/team/<int:team_id>/', views.team_view, name='team_view'),
    path('poll/voters/<int:poll_id>/', views.voters_view, name='voters_view'),
    path('poll/ballots/<int:poll_id>/<int:user_type>/', views.ballots_view, name='ballots_view'),
    path('poll/analysis/<int:poll_id>/', views.analysis_view, name='analysis_view'),
    path('poll/analysis/this_week/', views.analysis_this_week, name='analysis_this_week'),
    path('ballot/<int:ballot_id>/', views.ballot_view, name='ballot_view'),
    path('about/', views.about, name='about'),
    path('poll_post/', views.poll_post, name='poll_post'),
    path('my_ballots/', views.my_ballots, name='my_ballots'),
    path('apply_for_provisional/', views.apply_for_provisional, name='apply_for_provisional'),
    path('create_ballot/<int:poll_id>/', views.create_ballot, name='create_ballot'),
    path('ballot/edit/<int:ballot_id>/', views.edit_ballot, name='edit_ballot'),
    path('ballot/save/<int:ballot_id>/', views.save_ballot, name='save_ballot'),
    path('ballot/validiate/<int:ballot_id>/', views.validate_ballot, name='validate_ballot'),
    path('ballot/submit/<int:ballot_id>/', views.submit_ballot, name='submit_ballot')
]
