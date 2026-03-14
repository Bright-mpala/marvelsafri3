from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    # Booking management
    path('', views.booking_list, name='list'),
    # Use UUID primary keys for bookings (inherited from BaseModel)
    path('<uuid:pk>/', views.booking_detail, name='detail'),
    path('<uuid:pk>/rebook/', views.booking_rebook, name='rebook'),
    path('<uuid:pk>/download-confirmation/', views.booking_download_confirmation, name='download_confirmation'),
    path('<uuid:pk>/invoice/', views.booking_download_invoice, name='download_invoice'),
    path('create/<str:property_id>/', views.booking_create, name='create'),
    path('<uuid:pk>/modify/', views.booking_modify, name='modify'),
    path('<uuid:pk>/cancel/', views.booking_cancel, name='cancel'),
]
