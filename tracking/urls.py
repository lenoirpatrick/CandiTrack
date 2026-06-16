from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("", views.candidature_list, name="candidature_list"),
    path("candidatures/nouvelle/", views.candidature_create, name="candidature_create"),
    path("candidatures/<int:pk>/", views.candidature_detail, name="candidature_detail"),
    path(
        "candidatures/<int:pk>/modifier/",
        views.candidature_update,
        name="candidature_update",
    ),
    path(
        "candidatures/<int:pk>/supprimer/",
        views.candidature_delete,
        name="candidature_delete",
    ),
    path("sites/", views.site_list, name="site_list"),
    path("sites/nouveau/", views.site_create, name="site_create"),
    path("sites/<int:pk>/", views.site_detail, name="site_detail"),
    path("sites/<int:pk>/modifier/", views.site_update, name="site_update"),
    path("sites/<int:pk>/supprimer/", views.site_delete, name="site_delete"),
    path("sites/<int:pk>/desactiver/", views.site_toggle_active, name="site_toggle_active"),
    path("stats/", views.stats, name="stats"),
    path("cv/", views.cv_list, name="cv_list"),
    path("cv/charger/", views.cv_create, name="cv_create"),
    path("cv/<int:pk>/", views.cv_detail, name="cv_detail"),
    path("cv/<int:pk>/analyser/", views.cv_analyze, name="cv_analyze"),
    path("cv/<int:pk>/modifier/<str:section>/", views.cv_edit, name="cv_edit"),
    path("cv/<int:pk>/archiver/", views.cv_toggle_active, name="cv_toggle_active"),
    path("cv/<int:pk>/defaut/", views.cv_set_default, name="cv_set_default"),
    path("cv/<int:pk>/export/<str:fmt>/", views.cv_export, name="cv_export"),
    path("cv/<int:pk>/imprimer/", views.cv_print, name="cv_print"),
    path("cv/<int:pk>/supprimer/", views.cv_delete, name="cv_delete"),
    # Références d'un CV (issue #62)
    path(
        "cv/<int:cv_pk>/references/ajouter/",
        views.reference_create,
        name="reference_create",
    ),
    path("references/<int:pk>/modifier/", views.reference_update, name="reference_update"),
    path("references/<int:pk>/supprimer/", views.reference_delete, name="reference_delete"),
    # Aide & configuration de l'extension (issue #6)
    path("aide/", views.help_page, name="help"),
    path("aide/extension.zip", views.extension_download, name="extension_download"),
    # Coaching IA (issue #33)
    path("api/coaching/", views.ai_coaching, name="ai_coaching"),
    path("api/candidatures/<int:pk>/relance/", views.ai_relance, name="ai_relance"),
    # API for the Chrome extension (issue #2)
    path("api/candidatures/", views.api_candidature_create, name="api_candidature_create"),
]
