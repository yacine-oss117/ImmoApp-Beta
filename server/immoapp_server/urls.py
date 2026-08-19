"""
URL configuration for immoapp_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from server.api.auth_account_views import (
    AccountActivateView,
    PasswordForgotView,
    PasswordResetView,
    StepUpAuthView,
)
from server.api.auth_oidc_views import OidcConfigView, OidcTokenView
from server.api.auth_views import SecureTokenObtainPairView, SecureTokenRefreshView

urlpatterns = [
    path(settings.DJANGO_ADMIN_PATH, admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/", include("server.api.urls")),
    path("api/auth/token/", SecureTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", SecureTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/password/forgot/", PasswordForgotView.as_view(), name="password_forgot"),
    path("api/auth/password/reset/", PasswordResetView.as_view(), name="password_reset"),
    path("api/auth/account/activate/", AccountActivateView.as_view(), name="account_activate"),
    path("api/auth/step-up/", StepUpAuthView.as_view(), name="step_up_auth"),
    path("api/auth/oidc/config/", OidcConfigView.as_view(), name="oidc_config"),
    path("api/auth/oidc/token/", OidcTokenView.as_view(), name="oidc_token"),
]
