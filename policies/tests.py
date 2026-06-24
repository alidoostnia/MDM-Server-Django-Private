from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from devices.models import Account, Department, Device
from .models import Action, ActionType, Command, Module, ModuleField, Policy


class ExternalPushNotificationAPITests(APITestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Operations")
        self.device = Device.objects.create(
            device_name="ops-phone-1",
            imeis="123456789012345",
            department=self.department,
        )
        self.module = Module.objects.create(name="Device Status & Heartbeat")
        self.module_field = ModuleField.objects.create(
            module=self.module,
            name="screen_on",
            description="",
        )
        self.action_type = ActionType.objects.create(name="MakeNotification")
        self.staff_user = Account.objects.create(
            username="staff",
            password="x",
            first_name="Staff",
            last_name="User",
            phone_number="09120000001",
            is_staff=True,
        )
        self.regular_user = Account.objects.create(
            username="regular",
            password="x",
            first_name="Regular",
            last_name="User",
            phone_number="09120000002",
        )
        self.url = reverse("external-push-notification")

    @patch("policies.services.send_command_to_device.delay")
    def test_staff_user_can_queue_device_push_notification(self, mocked_delay):
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            self.url,
            {
                "title": "Maintenance",
                "body": "Restart at 22:00.",
                "image_url": "https://example.com/notice.png",
                "tag": "maintenance",
                "target": {
                    "type": "device",
                    "id": str(self.device.pk),
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(response.data["queued_devices"], 1)
        self.assertEqual(len(response.data["command_ids"]), 1)

        policy = Policy.objects.get(pk=response.data["policy_id"])
        action = Action.objects.get(pk=response.data["action_id"])
        command = Command.objects.get(pk=response.data["command_ids"][0])

        self.assertEqual(action.action_type, self.action_type)
        self.assertEqual(action.input["title"], "Maintenance")
        self.assertEqual(action.input["image_url"], "https://example.com/notice.png")
        self.assertEqual(command.policy_device.policy, policy)
        self.assertEqual(command.policy_device.device, self.device)
        self.assertEqual(command.status, Command.STATUS_PENDING)
        mocked_delay.assert_called_once_with(str(command.pk))

    def test_regular_user_cannot_queue_push_notification(self):
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.post(
            self.url,
            {
                "title": "Maintenance",
                "body": "Restart at 22:00.",
                "target": {
                    "type": "device",
                    "id": str(self.device.pk),
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
