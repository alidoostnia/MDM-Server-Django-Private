from django.db import models
import uuid
from devices.models import Department, Device
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models import Index
from django.utils import timezone
from datetime import timedelta


def default_policy_expiration_date():
    return timezone.now() + timedelta(days=365)

# ------------------ Module ------------------
class Module(models.Model):
    module_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "Module"

    def __str__(self):
        return self.name


# ------------------ Module Field ------------------
class ModuleField(models.Model):
    field_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        db_table = "ModuleField"

    def __str__(self):
        return f"{self.module.name} - {self.name}"
    

# ------------------ Action Type ------------------
class ActionType(models.Model):
    action_type_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    input_schema = models.JSONField(blank=True, null=True, help_text="JSON Schema describing the expected Action.input structure.")
    example_input = models.JSONField(blank=True, null=True, help_text="An example JSON object for this action type. Admins can use this as a starting point.")

    
    class Meta:
        db_table = "ActionType"

    def __str__(self):
        return self.name

class TriggerMixin(models.Model):
    class TriggerKind(models.IntegerChoices):
        ONE_TIME = 1, "OneTime"
        ALWAYS = 2, "Always"
        REGEX = 3, "Regex"   # needs regex
        INTERVAL = 4, "Interval"  # needs start + interval
        EXACT_TIME = 5, "ExactTime"  # needs exact_time

    trigger_kind_id = models.PositiveSmallIntegerField(choices=TriggerKind.choices)

    # optional fields
    regex = models.CharField(max_length=200, blank=True, null=True)
    # start_time = models.DateTimeField(blank=True, null=True) # we use DurationField for interval triggers
    interval_time = models.DurationField(blank=True, null=True)
    exact_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    def as_trigger_json(self):
        """Serialize trigger settings into JSON."""
        if self.trigger_kind_id == self.TriggerKind.REGEX:
            return {
                "trigger_kind": self.TriggerKind(self.trigger_kind_id).label,
                "regex": self.regex,
            }
        elif self.trigger_kind_id == self.TriggerKind.INTERVAL:
            return {
                "trigger_kind": self.TriggerKind(self.trigger_kind_id).label,
                "interval_time": self.interval_time.total_seconds() if self.interval_time else None,
            }
        elif self.trigger_kind_id == self.TriggerKind.EXACT_TIME:
            return {
                "trigger_kind": self.TriggerKind(self.trigger_kind_id).label,
                "exact_time": self.exact_time.isoformat() if self.exact_time else None,
            }
        else:
            return {"trigger_kind": self.TriggerKind(self.trigger_kind_id).label}

    
# ------------------ Action ------------------
class Action(TriggerMixin):
    action_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action_type = models.ForeignKey(ActionType, on_delete=models.CASCADE, related_name="actions")
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    input = models.JSONField(null=True, blank=True)
    is_main_action = models.BooleanField(default=False)
    is_deletable = models.BooleanField(default=True)

    class Meta:
        db_table = "Action"

    def __str__(self):
        return f"{self.name} ({self.action_type.name}) \n ({self.action_id})"

# ------------------ Policy ------------------
class Policy(TriggerMixin):
    policy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expiration_date = models.DateTimeField(default=default_policy_expiration_date)

    module_field = models.ForeignKey(ModuleField, on_delete=models.CASCADE, related_name="policies")

    actions = models.ManyToManyField(Action, related_name="policies", blank=True, null=True)

    devices = models.ManyToManyField(Device, related_name="policies", through="PolicyDevice")

    departments = models.ManyToManyField(Department, related_name="policies", blank=True)

    class Meta:
        db_table = "Policy"
        verbose_name = "Policy"
        verbose_name_plural = "Policies"

    def __str__(self):
        return f"{self.name} (Policy {self.policy_id})"

    def get_target_devices(self):
        direct_ids = self.devices.values_list("pk", flat=True)
        department_ids = Device.objects.filter(
            department__in=self.departments.all()
        ).values_list("pk", flat=True)
        return Device.objects.filter(pk__in=direct_ids.union(department_ids)).distinct()

# ------------------ Policy Device (through table) ------------------
class PolicyDevice(models.Model):
    """Join table for Policy <-> Device to track per-device apply status."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey("Policy", on_delete=models.CASCADE, related_name="policy_devices")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="policy_devices")
    last_update = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("policy", "device")
        db_table = "PolicyDevice"

    def __str__(self):
        return f"{self.policy.name} -> {self.device}"

    def get_actions_json(self):
        actions_json = []
        for action in self.policy.actions.all():
            actions_json.append({
                "action_id": str(action.action_id),
                "action_type": action.action_type.name,
                "inputs": action.input,
                "trigger_on": action.as_trigger_json(),
            })
        return actions_json
    
    def current_apply_command(self):
        """
        Return the most-recent command for this PolicyDevice
        that is relevant to apply-state determination:

          - CREATE commands with status in (ACK, APPLIED)
          - DELETE commands with status == APPLIED

        Returns the newest such Command or None.
        """
        create_statuses = (Command.STATUS_ACK, Command.STATUS_APPLIED)
        q = (
            Q(command_type=Command.COMMAND_CREATE, status__in=create_statuses)
            | Q(command_type=Command.COMMAND_DELETE, status=Command.STATUS_APPLIED)
        )

        return self.commands.filter(q).order_by("-created_at").first()
    
    def is_applied(self) -> bool:
        """
        Determine whether this PolicyDevice is currently applied on the device.

        Logic:
        - Look up the most recent relevant command (see current_apply_command).
        - If none found -> not applied.
        - If latest is CREATE -> applied.
        - If latest is DELETE -> not applied.
        """
        latest = self.current_apply_command()
        if not latest:
            return False
        return latest.command_type == Command.COMMAND_CREATE
    
    
    
class Command(models.Model):
    
    COMMAND_CREATE = "CREATE"
    COMMAND_UPDATE = "UPDATE"
    COMMAND_DELETE = "DELETE"
    COMMAND_READ = "READ"
    COMMAND_READ_ALL = "READ_ALL"
    COMMAND_DELETE_ALL = "DELETE_ALL"

    COMMAND_TYPE_CHOICES = [
        (COMMAND_CREATE, "Create"),
        (COMMAND_UPDATE, "Update"),
        (COMMAND_DELETE, "Delete"),
        (COMMAND_READ, "Read"),
        (COMMAND_READ_ALL, "Read All"),
        (COMMAND_DELETE_ALL, "Delete All"),
    ]

    STATUS_PENDING = "PENDING"
    STATUS_SENT = "SENT"
    STATUS_ACK = "ACK"
    STATUS_FAILED = "FAILED"
    STATUS_APPLIED = "APPLIED"
    STATUS_CREATED = "CREATED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_ACK, "Acknowledged"),
        (STATUS_FAILED, "Failed"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_CREATED, "Created"),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # command_id
    
    # if command type is not READ ALL
    policy_device = models.ForeignKey(
        PolicyDevice, 
        on_delete=models.CASCADE, 
        related_name="commands", 
        null=True, 
        blank=True,
        help_text="The PolicyDevice this command applies to. Leave empty for device-level commands (e.g. READ_ALL/DELETE_ALL)."
    )
    
    # if command type is READ ALL
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="commands",
        blank=True,
        null=True,
        help_text="Use for device-level commands (e.g. READ_ALL/DELETE_ALL). If left empty, device is derived from policy_device."
    )
    
    command_type = models.CharField(max_length=10, choices=COMMAND_TYPE_CHOICES, default=COMMAND_CREATE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    attempts = models.PositiveSmallIntegerField(default=0)
    mqtt_message_id = models.CharField(max_length=200, blank=True, null=True)
    response = models.JSONField(blank=True, null=True)
    payload = models.JSONField(blank=True, null=True)  # store generated JSON payload
    created_at = models.DateTimeField(auto_now_add=True)
    last_update = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "Command"
        ordering = ("-created_at",)
        indexes = [
            Index(fields=["policy_device", "created_at"]),
            Index(fields=["policy_device", "command_type", "status", "created_at"]),
        ]
    
    def __str__(self):
        if self.policy_device and getattr(self.policy_device, "policy", None):
            policy_name = getattr(self.policy_device.policy, "name", str(self.policy_device.policy))
            dev = getattr(self.policy_device, "device", None)
            return f"{self.command_type} {policy_name} -> {dev}"
        if self.device:
            return f"{self.command_type} -> {self.device}"
        return f"{self.command_type}"

    def clean(self):
        """
        Validate that:
         - READ_ALL/DELETE_ALL commands must target a device (device or policy_device),
         - Other commands require a policy_device (so they know which policy to act on).
        """
        if self.command_type in (self.COMMAND_READ_ALL, self.COMMAND_DELETE_ALL):
            if not self.device and not self.policy_device:
                raise ValidationError(f"{self.command_type} commands require a device (either `device` or associated `policy_device`).")
        else:
            if not self.policy_device:
                raise ValidationError(f"{self.command_type} commands require a policy_device to be set.")

        if self.device and self.policy_device:
            pd_device = getattr(self.policy_device, "device", None)
            if pd_device and (pd_device.pk != self.device.pk):
                raise ValidationError("If both device and policy_device are set, they must reference the same device.")

    def save(self, *args, **kwargs):
        self.full_clean() 
        super().save(*args, **kwargs)
           
    def to_command_json(self):
        """
        Create the JSON payload that will be published to the device for this command.
        For READ_ALL/DELETE_ALL we produce a minimal payload that contains only command_id, command_type and agent_id.
        For other command types we include the policy-related info (derived from policy_device).
        """

        device = self.device or (self.policy_device.device if self.policy_device else None)
        if not device:
            raise ValueError("Cannot generate command JSON without a target device.")

        if self.command_type in (self.COMMAND_READ_ALL, self.COMMAND_DELETE_ALL):
            payload = {
                "command_id": str(self.id),
                "command_type": self.command_type,
                "agent_id": str(device.device_id),
                "created_at": self.created_at.isoformat(),
            }
            return payload

        if not self.policy_device or not self.policy_device.policy:
            raise ValueError(f"Cannot generate command JSON for {self.command_type} without an associated policy_device and policy.")
        
        policy = self.policy_device.policy
        actions_json = self.policy_device.get_actions_json()

        payload = {
            "command_id": str(self.id),
            "command_type": self.command_type,
            "policy_id": str(policy.policy_id),
            "agent_id": str(device.device_id),
            "created_at": policy.created_at.isoformat(),
            "exp_date": policy.expiration_date.isoformat() if policy.expiration_date else None,
            "module": policy.module_field.module.name,
            "module_field": policy.module_field.name,
            "actions": actions_json,
            "log_on": policy.as_trigger_json(),
        }
        
        return payload
    
    
class DevicePolicySnapshot(models.Model):
    """
    Persist applied policies reported by a device in response to READ / READ_ALL commands.
    Each snapshot ties to a device and the command that produced it.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="policy_snapshots")
    command = models.ForeignKey(Command, on_delete=models.SET_NULL, blank=True, null=True, related_name="snapshots")
    policy_id = models.UUIDField(blank=True, null=True) 
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "DevicePolicySnapshot"
        ordering = ("-created_at",)

    def __str__(self):
        created_label = self.created_at.isoformat() if self.created_at else "unknown-time"
        return f"Snapshot {self.device} @ {created_label}"
    
class PushNotificationLauncher(models.Model):
    """
    Dummy model – used ONLY to show Push Notification
    entry in Django Admin sidebar.
    """
    class Meta:
        managed = False
        verbose_name = "Push Notification"
        verbose_name_plural = "Push Notifications"