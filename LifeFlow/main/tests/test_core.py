from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


class TestAppCore(TestCase):
    """Core smoke tests for key LifeFlow pages & dashboard widgets."""

    def setUp(self):
        self.user = User.objects.create_user(username="TestUser", password="pass")
        self.client.force_login(self.user)

    def test_dashboard_v2_loads(self):
        resp = self.client.get("/dashboard-v2/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dashboard")

    def test_family_manager_page_loads(self):
        resp = self.client.get("/FamilyManager/")
        self.assertEqual(resp.status_code, 200)

    def test_bill_manager_page_loads(self):
        resp = self.client.get("/BillManager/")
        self.assertEqual(resp.status_code, 200)

    def test_health_manager_page_loads(self):
        resp = self.client.get("/HealthManager/")
        self.assertEqual(resp.status_code, 200)

    def test_subscription_page_loads(self):
        resp = self.client.get("/Subscription/")
        self.assertEqual(resp.status_code, 200)

    def test_user_profile_page_loads(self):
        resp = self.client.get("/UserProfile/")
        self.assertEqual(resp.status_code, 200)


    def test_dashboard_redirects_if_not_logged_in(self):
        self.client.logout()
        resp = self.client.get("/dashboard-v2/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.url)

    def _assert_json_ok(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(resp.headers.get("Content-Type"), ["application/json", "application/json; charset=utf-8"])

    def test_widget_calendar(self):
        self._assert_json_ok("/api/widgets/calendar/")

    def test_widget_bills(self):
        self._assert_json_ok("/api/widgets/bills/")

    def test_widget_family(self):
        self._assert_json_ok("/api/widgets/family/")

    def test_widget_documents(self):
        self._assert_json_ok("/api/widgets/document/")

    def test_widget_health(self):
        self._assert_json_ok("/api/widgets/health/")

    def test_widget_kanban(self):
        self._assert_json_ok("/api/widgets/kanban/")

    def test_widget_subscriptions(self):
        self._assert_json_ok("/api/widgets/subscription/")


    def test_family_create(self):
        resp = self.client.post("/family/create/", {"name": "My Fam"})
        self.assertIn(resp.status_code, (200, 302))

    def test_family_leave_no_family(self):
        """Should handle gracefully even if no family exists."""
        resp = self.client.post("/family/leave/")
        self.assertIn(resp.status_code, (200, 302))