# main/tests/test_document_storage.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from main.models import Document

User = get_user_model()

class TestDocumentStorage(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="DocUser", password="pass")
        self.client.force_login(self.user)

    def test_document_page_renders(self):
        resp = self.client.get(reverse("document_manager"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Documents")

    def test_upload_document(self):
        file = SimpleUploadedFile("test.txt", b"hello world")
        resp = self.client.post(reverse("document_upload"), {"file": file})
        self.assertIn(resp.status_code, (200, 302))

        self.assertTrue(
            Document.objects.filter(user=self.user, name="test.txt").exists()
        )