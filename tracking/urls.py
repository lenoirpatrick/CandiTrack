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
    path("sites/", views.site_list, name="site_list"),
    path("sites/nouveau/", views.site_create, name="site_create"),
    path("sites/<int:pk>/modifier/", views.site_update, name="site_update"),
    path("sites/<int:pk>/supprimer/", views.site_delete, name="site_delete"),
    path("sites/<int:pk>/logo/", views.site_refresh_logo, name="site_refresh_logo"),
    path("stats/", views.stats, name="stats"),
    path("cv/", views.cv_list, name="cv_list"),
    path("cv/charger/", views.cv_create, name="cv_create"),
    path("cv/<int:pk>/supprimer/", views.cv_delete, name="cv_delete"),
]
