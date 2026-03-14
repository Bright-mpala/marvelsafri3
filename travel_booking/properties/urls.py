from django.urls import path
from . import views
from . import views_secure

app_name = 'properties'

urlpatterns = [
    # Property listing and browsing (public)
    path('', views.PropertyListView.as_view(), name='list'),
    path('search/', views.PropertySearchView.as_view(), name='search'),
    
    # Property creation (secure - uses service layer)
    path('create/', views_secure.PropertyCreateView.as_view(), name='create'),
    path('create/success/<slug:slug>/', views_secure.PropertySubmissionSuccessView.as_view(), name='create_success'),
    
    # Owner dashboard
    path('my-properties/', views_secure.OwnerPropertyListView.as_view(), name='owner_list'),

    # Host analytics
    path('host/analytics/', views_secure.HostAnalyticsView.as_view(), name='host_analytics'),
    
    # Admin moderation workflow
    path('admin/property/pending/', views_secure.AdminPendingPropertiesView.as_view(), name='admin_property_pending'),
    path('admin/property/<slug:slug>/review/', views_secure.AdminPropertyReviewView.as_view(), name='admin_property_review'),
    path('admin/property/<slug:slug>/approve/', views_secure.AdminPropertyApproveView.as_view(), name='admin_property_approve'),
    path('admin/property/<slug:slug>/reject/', views_secure.AdminPropertyRejectView.as_view(), name='admin_property_reject'),
    # Backwards-compatible aliases
    path('admin/pending/', views_secure.AdminPendingPropertiesView.as_view(), name='admin_pending'),
    path('admin/review/<slug:slug>/', views_secure.AdminPropertyReviewView.as_view(), name='admin_review'),
    
    # Property actions (AJAX)
    path('<str:slug>/submit/', views_secure.PropertySubmitForReviewView.as_view(), name='submit_for_review'),
    path('<str:slug>/deactivate/', views_secure.PropertyDeactivateView.as_view(), name='deactivate'),
    path('<str:slug>/favorite/', views.toggle_favorite, name='toggle_favorite'),
    
    # Property detail and edit
    path('<str:slug>/', views.PropertyDetailView.as_view(), name='detail'),
    path('<str:slug>/edit/', views_secure.PropertyEditView.as_view(), name='edit'),
    
    # AJAX endpoints
    path('api/availability/<str:property_id>/', views.property_availability, name='availability'),
]
