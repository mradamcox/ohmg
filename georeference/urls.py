from django.urls import path

from .views import (
    SplitView,
    GeoreferenceView,
    ResourceView,
)

urlpatterns = [
    path('split/<int:docid>/', SplitView.as_view(), name="split_view"),
    path('georeference/<int:docid>/', GeoreferenceView.as_view(), name="georeference_view"),
    path('resource/<int:pk>', ResourceView.as_view(), name="resource_detail"),
]
