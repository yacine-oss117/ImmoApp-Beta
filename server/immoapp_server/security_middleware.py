"""
Security middleware to add additional HTTP security headers.
"""

from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

if TYPE_CHECKING:
    from django.http import HttpResponse


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add important security headers to all responses.
    """

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        # Only add security headers if not in debug mode
        from django.conf import settings

        if settings.DEBUG:
            return response

        # Prevent clickjacking by disallowing framing
        response["X-Frame-Options"] = "DENY"

        # Prevent pages from loading when they detect reflected XSS attacks
        response["X-XSS-Protection"] = "1; mode=block"

        # Prevent MIME-type sniffing
        response["X-Content-Type-Options"] = "nosniff"

        # Referrer policy to control referrer information
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy to control browser features
        response["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "interest-cohort=()"
        )

        # Feature policy (deprecated but still supported by some browsers)
        response["Feature-Policy"] = "geolocation 'none'; " "microphone 'none'; " "camera 'none'"

        return response


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log important request information for security monitoring.
    """

    def process_request(self, request: HttpRequest) -> None:
        # Log important request headers for security analysis
        # This is just for monitoring - actual logging would go to a security SIEM
        return None

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        # Add security-related headers to response
        response["X-Download-Options"] = "noopen"
        return response
