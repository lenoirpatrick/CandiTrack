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
    path("stats/", views.stats, name="stats"),
    path("cv/", views.cv_list, name="cv_list"),
]
