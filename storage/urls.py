from django.urls import path
from . import views

urlpatterns = [
    path('generate-upload-url/', views.generate_presigned_upload, name='generate_presigned_upload'),
    path('complete-upload/', views.complete_upload, name='complete_upload'),
    path('generate-download-url/', views.get_presigned_download, name='get_presigned_download'),
    path('files/', views.list_files, name='list_files'),
    path('files/<uuid:file_id>/', views.delete_file, name='delete_file'),
]