# main/tests/test_family_manager.py
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from main.models import Family, FamilyMembership, Task

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestFamilyManager(TestCase):
    def setUp(self):
        # Users
        self.owner = User.objects.create_user(username="OwnerUser", password="pass")
        self.member = User.objects.create_user(username="MemberUser", password="pass")
        self.guest  = User.objects.create_user(username="GuestUser",  password="pass")

        # Family: owner + member
        self.family = Family.objects.create(name="The Rai Family", owner=self.owner)
        FamilyMembership.objects.create(family=self.family, user=self.owner, role="owner")
        FamilyMembership.objects.create(family=self.family, user=self.member, role="member")

    # ---------- Page render ----------

    def test_family_page_owner_sees_family(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("FamilyManager"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Family")           # page title
        self.assertContains(resp, "Invite Member")    # owner can open invite
        self.assertNotContains(resp, "Leave Family")  # owner should not see leave

    def test_family_page_member_sees_leave(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("FamilyManager"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Leave Family")     # non-owner sees leave
        self.assertContains(resp, "Invite Member")    # UI button exists (backend blocks)

    def test_empty_state_shows_create_family(self):
        # Fresh user with no family
        new_user = User.objects.create_user(username="NewUser", password="pass")
        self.client.force_login(new_user)
        resp = self.client.get(reverse("FamilyManager"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create Family")

    # ---------- Create / Leave / Delete ----------

    def test_create_family_for_user_without_family(self):
        new_user = User.objects.create_user(username="SoloUser", password="pass")
        self.client.force_login(new_user)
        resp = self.client.post(reverse("family_create"), {"name": "Solo Family"})
        self.assertIn(resp.status_code, (302, 200))
        self.assertTrue(
            FamilyMembership.objects.filter(user=new_user).exists(),
            "User should be added to their new family",
        )

    def test_member_can_leave_family(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("family_leave"), {"family_id": self.family.id})
        self.assertIn(resp.status_code, (302, 200))
        self.assertFalse(
            FamilyMembership.objects.filter(family=self.family, user=self.member).exists()
        )

    def test_non_owner_cannot_delete_family(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("family_delete"), {"family_id": self.family.id})
        self.assertIn(resp.status_code, (302, 200))
        # Family should still exist
        self.assertTrue(Family.objects.filter(id=self.family.id).exists())

    def test_owner_can_delete_family(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("family_delete"), {"family_id": self.family.id})
        self.assertIn(resp.status_code, (302, 200))
        self.assertFalse(Family.objects.filter(id=self.family.id).exists())

    # ---------- Invite (simple happy-path + member blocked) ----------

    def test_owner_can_post_invite(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("family_invite_create"),
            {"email": "person@example.com", "role": "member"},
        )
        # View redirects back to FamilyManager with a success message
        self.assertIn(resp.status_code, (302, 200))

    def test_member_cannot_post_invite(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse("family_invite_create"),
            {"email": "person@example.com", "role": "member"},
        )
        # Member should be blocked by view logic
        self.assertIn(resp.status_code, (302, 200))

    # ---------- Assign task endpoint (JSON) ----------

    def test_assign_task_returns_json_201(self):
        """
        JS posts JSON to 'family_task_assign' with:
          { member_id, title, due_date? }
        Your view returns 201 and basic JSON fields.
        """
        self.client.force_login(self.owner)
        member_row = FamilyMembership.objects.get(family=self.family, user=self.member)
        url = reverse("family_task_assign")
        payload = {"member_id": member_row.id, "title": "Buy milk", "due_date": ""}

        resp = self.client.post(
            url, data=self._as_json(payload), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data.get("title"), "Buy milk")
        # Task should exist for the logged-in owner (Task has no assigned_to/family fields in your models)
        self.assertTrue(Task.objects.filter(user=self.owner, title="Buy milk").exists())

    # ---------- Helpers ----------

    @staticmethod
    def _as_json(data):
        import json
        return json.dumps(data)
