from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('poll/', views.poll_index, name='poll_index'),
    path('poll/this_week/', views.this_week, name='this_week'),
    path('poll/last_week/', views.last_week, name='last_week'),
    path('poll/view/<int:poll_id>/', views.poll_view, name='poll_view'),
    path('poll/view/<int:poll_id>/team/<int:team_id>/', views.team_view, name='team_view')
]
