# main/tests/test_bill_manager.py
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from main.models import Bill

User = get_user_model()


class TestBillManager(TestCase):
    def setUp(self):
        # A basic logged-in user for the "add bill" flow (add_item requires login)
        self.user = User.objects.create_user(username="tester", password="pass")

    # ─── Page render + totals ──────────────────────────────────────────────────

    def test_bill_manager_lists_bills_and_shows_total(self):
        Bill.objects.create(name="Internet", cost=Decimal("59.99"), status="active")
        Bill.objects.create(name="Electricity", cost=Decimal("120.00"), status="active")
        Bill.objects.create(name="Phone", cost=Decimal("30.50"), status="active")

        resp = self.client.get(reverse("BillManager"))
        self.assertEqual(resp.status_code, 200)
        # Bill names appear
        self.assertContains(resp, "Internet")
        self.assertContains(resp, "Electricity")
        self.assertContains(resp, "Phone")
        # Total text appears (string check, not exact float formatting)
        self.assertContains(resp, "Monthly Cost")
        self.assertContains(resp, "$")  # price sign present

    def test_chart_has_one_bar_per_bill(self):
        Bill.objects.create(name="A", cost=Decimal("10.00"), status="active")
        Bill.objects.create(name="B", cost=Decimal("20.00"), status="active")
        Bill.objects.create(name="C", cost=Decimal("30.00"), status="active")

        resp = self.client.get(reverse("BillManager"))
        self.assertEqual(resp.status_code, 200)
        # Each bill renders a <div class="bar"> in the chart
        bar_count = resp.content.decode().count('class="bar"')
        self.assertEqual(bar_count, 3)

    # ─── Add bill (via add_item) ───────────────────────────────────────────────

    def test_add_bill_creates_record_and_redirects(self):
        self.client.force_login(self.user)  # add_item is @login_required
        data = {
            "name": "Water",
            "cost": "45.00",
            "renewal_date": "",        # optional
            "contract_type": "Monthly" # will be stored; status auto 'active' in view
        }
        resp = self.client.post(reverse("add_item", args=["bill"]), data)
        # Should redirect back to BillManager
        self.assertIn(resp.status_code, (302, 200))
        self.assertTrue(Bill.objects.filter(name="Water", cost=Decimal("45.00")).exists())

    # ─── Delete bill ──────────────────────────────────────────────────────────

    def test_delete_bill_removes_record(self):
        bill = Bill.objects.create(name="Temp Bill", cost=Decimal("9.99"), status="active")
        resp = self.client.post(reverse("delete_bill", args=[bill.id]))
        self.assertIn(resp.status_code, (302, 200))
        self.assertFalse(Bill.objects.filter(id=bill.id).exists())

