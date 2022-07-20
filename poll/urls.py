from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('poll/', views.poll_index, name='poll_index')
]