from django.test import Client, SimpleTestCase
from rest_framework import status


class FirewallTestCase(SimpleTestCase):
    def test_firewall_blocks_unprotected_view(self):
        """
        GIVEN a view that lacks @permission_classes
        WHEN a request is made to it
        THEN the firewall should return 403 Forbidden.
        """
        client = Client()
        # This URL was registered to a view with no decorators
        response = client.get("/api/v1/firewall-verification/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        data = response.json()
        self.assertEqual(data["code"], "SECURITY_POLICY_MISSING")
        self.assertIn("Security Policy Required", data["error"])

    def test_firewall_allows_public_health_view(self):
        """
        GIVEN a view in the PUBLIC_API_ALLOW_LIST
        WHEN a request is made to it
        THEN it should bypass the firewall and return 200.
        """
        client = Client()
        response = client.get("/api/v1/health/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload.get("status"), "ok")

    def test_firewall_passes_protected_view_to_auth(self):
        """
        GIVEN a view with @permission_classes([IsAuthenticated])
        WHEN a request is made without a token
        THEN the firewall should ALLOW it (it has a policy)
        AND DRF should block it with 401 Unauthorized.
        """
        client = Client()
        response = client.get("/api/v1/clients/")

        # 401 means it passed the firewall (403) and reached DRF's Auth layer
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
