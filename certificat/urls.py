from django.urls import path
from . import views
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path("", views.home, name="home"),
    path("raportare/", views.raportare, name="raportare"),
    path("administrare/", views.administrare, name="administrare"),
    path("genereaza/", views.generate_docx_aviz, name="generate_docx"),
    path("documentranges/", views.my_document_ranges, name="documentrange_list"),
    path("gestiuni/", views.list_gestiuni, name="gestiuni_list"),
    path("gestiuni/delete/<int:pk>/", views.delete_gestiune, name="delete_gestiune"),
    path("tipologii/", views.list_tipologii, name="tipologii_list"),
    path("tipologii/delete/<int:pk>/", views.delete_tipologie, name="delete_tipologie"),
    path("userprofile/edit/<int:user_id>/", views.edit_user_profile, name="edit_user_profile"),
    path("user/delete/<int:user_id>/", views.delete_user, name="delete_user"),
    path("role/edit/<int:role_id>/", views.edit_role, name="edit_role"),
    path("documentranges/edit/<int:pk>/", views.edit_document_range, name="edit_document_range"),
    path("documentranges/delete/<int:pk>/", views.delete_document_range, name="delete_document_range"),
    path("gestiuni/edit/<int:pk>/", views.edit_gestiune, name="edit_gestiune"),
    path("speciemapping/edit/<int:pk>/", views.edit_speciemapping, name="edit_speciemapping"),
    path("speciemapping/update/", views.update_speciemapping, name="update_speciemapping"),
    path("genereaza_aviz/", views.generate_docx_aviz, name="generate_docx_aviz"),
    path("documente-generated/", views.generated_documents_list, name="generated_documents_list"),
    path("documente-generated/delete/<int:doc_id>/", views.delete_generated_document, name="delete_generated_document"),
    path("documente-generated/edit/<int:doc_id>/", views.edit_generated_document, name="edit_generated_document"),
    path("document-preview/<str:aviz>/", views.document_preview, name="document_preview"),
    path('document-details/<str:aviz_number>/', views.document_details, name='document_details_api'),
    path("manual/", views.view_manual, name="view_manual"),
    path("manual/download/", views.download_manual, name="download_manual"),
    path("manual/download/<int:manual_id>/", views.download_manual, name="download_manual_specific"),
    path('administrare/serie-data/', views.list_serie_extra_data, name='list_serie_extra_data'),
    path('administrare/serie-data/delete/<int:pk>/', views.delete_serie_extra_data, name='delete_serie_extra_data'),
    path('administrare/serie-data/bulk-delete/', views.bulk_delete_serie_data, name='bulk_delete_serie_data'),
    path("manual/upload/", views.upload_manual_direct, name="upload_manual_direct"),
    path("manual/delete/<int:manual_id>/", views.delete_manual, name="delete_manual"),
    path('administrare/sterge-avize/', views.delete_all_documents, name='delete_all_documents'),
    path('change-password/', views.change_password, name='change_password'),
    path("documente-generated/update-data/<int:doc_id>/", views.update_document_data, name="update_document_data"),
    path("documente-generated/restore/<int:doc_id>/", views.restore_document, name="restore_document"),
    path('administrare/serie-data/details-ajax/<int:pk>/', views.serie_extra_data_details_ajax, name='serie_extra_data_details_ajax'),
    path("redirect-mfa/", views.redirect_to_mfa, name="redirect_to_mfa"),
    path("sso-login/", views.sso_login, name="sso_login"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
