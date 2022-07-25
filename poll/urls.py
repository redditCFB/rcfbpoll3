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
    path('poll/analysis/this_week/', views.analysis_this_week, name='analysis_this_week')
]
