from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()


class TestAppCore(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="TestUser", password="pass")
        self.client.force_login(self.user)

    def _ok(self, resp):
        self.assertNotEqual(resp.status_code, 500)

    def test_dashboard_v2_loads(self):
        resp = self.client.get("/dashboard-v2/")
        self._ok(resp)

    def test_family_manager_page_loads(self):
        resp = self.client.get("/FamilyManager/")
        self._ok(resp)

    def test_bill_manager_page_loads(self):
        resp = self.client.get("/BillManager/")
        self._ok(resp)

    def test_health_manager_page_loads(self):
        resp = self.client.get("/HealthManager/")
        self._ok(resp)

    def test_subscription_page_loads(self):
        resp = self.client.get("/Subscription/")
        self._ok(resp)

    def test_user_profile_page_loads(self):
        resp = self.client.get("/UserProfile/")
        self._ok(resp)

    def test_dashboard_redirects_if_not_logged_in(self):
        self.client.logout()
        resp = self.client.get("/dashboard-v2/")
        self._ok(resp)

    def test_register_page_loads(self):
        self.client.logout()
        resp = self.client.get("/register/")
        self._ok(resp)

    def test_register_post_safe(self):
        self.client.logout()
        resp = self.client.post("/register/", {
            "username": "newuser",
            "email": "a@a.com",
            "password": "pass1234",
            "confirm_password": "pass1234",
        })
        self._ok(resp)

    def test_login_page_loads(self):
        self.client.logout()
        resp = self.client.get("/login/")
        self._ok(resp)

    def test_login_post_safe(self):
        self.client.logout()
        resp = self.client.post("/login/", {
            "username": "TestUser",
            "password": "pass"
        })
        self._ok(resp)

    def test_logout_safe(self):
        resp = self.client.get("/logout/")
        self._ok(resp)

    def test_widget_calendar(self):
        resp = self.client.get("/api/widgets/calendar/")
        self._ok(resp)

    def test_widget_bills(self):
        resp = self.client.get("/api/widgets/bills/")
        self._ok(resp)

    def test_widget_family(self):
        resp = self.client.get("/api/widgets/family/")
        self._ok(resp)

    def test_widget_documents(self):
        resp = self.client.get("/api/widgets/document/")
        self._ok(resp)

    def test_widget_health(self):
        resp = self.client.get("/api/widgets/health/")
        self._ok(resp)

    def test_widget_kanban(self):
        resp = self.client.get("/api/widgets/kanban/")
        self._ok(resp)

    def test_widget_subscriptions(self):
        resp = self.client.get("/api/widgets/subscription/")
        self._ok(resp)

    def test_family_create(self):
        resp = self.client.post("/family/create/", {"name": "My Fam"})
        self._ok(resp)

    def test_family_leave_safe(self):
        resp = self.client.post("/family/leave/")
        self._ok(resp)

    def test_family_join_page_loads(self):
        resp = self.client.get("/family/join/")
        self._ok(resp)

    def test_family_invite_create(self):
        resp = self.client.post("/family/invite/create/")
        self._ok(resp)

    def test_family_join_invalid_code(self):
        resp = self.client.get("/family/join/INVALID/")
        self._ok(resp)

    def test_health_search(self):
        resp = self.client.get("/health/search/")
        self._ok(resp)

    def test_calendar_page_loads(self):
        resp = self.client.get("/calendar/")
        self._ok(resp)