from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from devices.models import Department, Device
from .models import Action, ActionType, Command, ModuleField, Policy, PolicyDevice
from .tasks import send_command_to_device


class PushNotificationServiceError(Exception):
    pass


@dataclass(frozen=True)
class PushNotificationResult:
    policy: Policy
    action: Action
    queued_devices: int
    command_ids: list[str]


def resolve_push_notification_module_field():
    preferred_seed_fields = [
        "screen_on",
        "screen_locked",
        "network_online",
        "heartbeat_timestamp",
    ]

    for field_name in preferred_seed_fields:
        module_field = ModuleField.objects.filter(name=field_name).first()
        if module_field:
            return module_field

    return ModuleField.objects.order_by("?").first()


def create_push_notification(
    *,
    title: str,
    body: str,
    image_url: str | None = None,
    tag: str = "",
    target_type: str,
    target_id: str,
):
    action_type = ActionType.objects.filter(name="MakeNotification").first()
    if not action_type:
        raise PushNotificationServiceError("ActionType 'MakeNotification' is missing. Please run seed_data first.")

    module_field = resolve_push_notification_module_field()
    if not module_field:
        raise PushNotificationServiceError("No ModuleField records were found. Please run seed_data first.")

    timestamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    schedule_time = timezone.now() + timedelta(seconds=5)
    expiration_date = schedule_time + timedelta(hours=1)
    action_payload = {
        "title": title,
        "body": body,
        "image_url": image_url or None,
        "tag": tag or "",
    }

    command_ids = []

    with transaction.atomic():
        action = Action.objects.create(
            action_type=action_type,
            name=f"push-notif-action-{timestamp}",
            description="Auto-created quick push notification action.",
            input=action_payload,
            trigger_kind_id=Action.TriggerKind.EXACT_TIME,
            exact_time=schedule_time,
        )

        policy = Policy.objects.create(
            name=f"push-notif-{timestamp}",
            module_field=module_field,
            trigger_kind_id=Policy.TriggerKind.ONE_TIME,
            expiration_date=expiration_date,
        )
        policy.actions.add(action)

        if target_type == "department":
            department = Department.objects.filter(pk=target_id).first()
            if not department:
                raise PushNotificationServiceError("Department not found.")
            policy.departments.add(department)
            target_devices = Device.objects.filter(department=department)
        elif target_type == "device":
            device = Device.objects.filter(pk=target_id).first()
            if not device:
                raise PushNotificationServiceError("Device not found.")
            target_devices = Device.objects.filter(pk=device.pk)
        else:
            raise PushNotificationServiceError("Target type must be 'department' or 'device'.")

        for device in target_devices:
            policy_device, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
            cmd = Command.objects.create(
                policy_device=policy_device,
                command_type=Command.COMMAND_CREATE,
                status=Command.STATUS_PENDING,
            )
            command_ids.append(str(cmd.pk))
            send_command_to_device.delay(str(cmd.pk))

    return PushNotificationResult(
        policy=policy,
        action=action,
        queued_devices=len(command_ids),
        command_ids=command_ids,
    )
