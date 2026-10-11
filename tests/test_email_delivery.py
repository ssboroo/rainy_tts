import os
import unittest
from unittest.mock import patch
from email.message import EmailMessage
from app import email_delivery

class FakeResponse:
    status_code = 200

class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs=kwargs
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def post(self,url,**kwargs):
        assert url == "https://api.resend.com/emails"
        assert kwargs["json"]["to"] == ["subscriber@example.com"]
        assert kwargs["json"]["from"] == "RAINY Voice Studio <voice@rainy.studio>"
        assert "api" not in kwargs["json"]
        return FakeResponse()

class ResendDeliveryTest(unittest.TestCase):
    @patch.dict(os.environ,{"RESEND_API_KEY":"test-key","SMTP_FROM":"RAINY Voice Studio <voice@rainy.studio>"})
    def test_https_delivery_without_smtp(self):
        msg=EmailMessage()
        msg["From"]="RAINY Voice Studio <voice@rainy.studio>"
        msg["To"]="subscriber@example.com"
        msg["Subject"]="Verify"
        msg.set_content("verification")
        msg.add_alternative("<strong>Verify</strong>",subtype="html")
        with patch("app.email_delivery.httpx.Client",FakeClient):
            self.assertIsNone(email_delivery.send_message(msg))
    @patch.dict(os.environ,{"RESEND_API_KEY":"", "SMTP_FROM":"voice@rainy.studio"})
    def test_disabled_without_key(self):
        self.assertFalse(email_delivery.api_configured())
        with self.assertRaises(RuntimeError):
            email_delivery.send_message(EmailMessage())
