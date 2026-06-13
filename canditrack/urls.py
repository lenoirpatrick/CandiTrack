"""URL configuration for canditrack project."""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

# L'admin Django est désactivé : toute la gestion passe par les pages de
# l'application (candidatures, sites, CV). On n'expose donc aucune route /admin/.
urlpatterns = [
    path('', include('tracking.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
