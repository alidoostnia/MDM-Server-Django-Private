import json
import csv
import io
import uuid
from datetime import timedelta

from django.contrib import admin, messages
from django.urls import path, reverse
from django.shortcuts import redirect, get_object_or_404
from django.utils.html import format_html
from django.utils import timezone
from django import forms
from django.db import close_old_connections, transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, Http404
from django.db.models.deletion import ProtectedError
from .models import Policy, PolicyDevice, Module, ModuleField, ActionType, Action, Command, DevicePolicySnapshot, PushNotificationLauncher
from devices.models import Department, Device
from .forms import PolicyAdminForm, ActionAdminForm
# celery task
from .tasks import send_command_to_device
from django.template.loader import render_to_string

class CommandInline(admin.TabularInline):
    model = Command
    readonly_fields = (
        "id",
        "status",
        "attempts",
        "mqtt_message_id",
        "response",
        "payload",
        "created_at",
        "last_update",
        "send_button",
    )
    fields = ("id", "command_type", "status", "attempts", "created_at", "last_update", "send_button")
    extra = 0
    can_delete = False

    def send_button(self, instance):
        """Per-row 'Send' button for a Command shown in inline."""
        if not instance or not instance.pk:
            return ""
        url = reverse("admin:policies_command_send", args=[str(instance.pk)])
        return format_html('<a class="button admin-action-button" href="{}">Send</a>', url)
    send_button.short_description = "Send"

class PolicyDeviceInline(admin.TabularInline):
    model = PolicyDevice
    readonly_fields = ("last_update", "commands_button")
    fields = ("device", "last_update", "commands_button")
    extra = 0
    can_delete = False

    def commands_button(self, instance):
        # link to change view of the PolicyDevice (where inline commands appear)
        if not instance.pk:
            return ""
        url = reverse("admin:policies_policydevice_change", args=[str(instance.pk)])
        return format_html('<a class="button admin-action-button" href="{}">View Commands</a>', url)
    commands_button.short_description = "Commands"

@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Main Info", {
            "fields": ("name", "expiration_date", "module_field", "actions", "departments"),
        }),
        ("Log Trigger Settings", {
            "fields": ("trigger_kind_id", "regex", "interval_time", "exact_time"),
            "classes": ("collapse",),  # optional: collapsible section
        }),
    )
    
    form = PolicyAdminForm
    list_display = ("name", "module_field", "trigger_kind", "created_at", "expiration_date", "total_devices", "apply_summary", "policy_actions")    
    filter_horizontal = ("actions", "departments")
    inlines = [PolicyDeviceInline]
    actions=["apply_selected_policies", "custom_delete_selected"]
    list_filter = ("trigger_kind_id", "created_at", "expiration_date")
    search_fields = ("name", "departments__name")
    
    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions
    
    def trigger_kind(self, obj):
        return obj.get_trigger_kind_id_display()
    trigger_kind.short_description = "Trigger kind"
    
    def delete_view(self, request, object_id, extra_context=None):
        """
        Intercept default admin delete confirmation. If any related PolicyDevice is applied,
        refuse deletion and redirect back to the policy change page with an error message.
        """
        obj = get_object_or_404(self.model, pk=object_id)

        try:
            applied_pds = []
            for pd in obj.policy_devices.select_related("device").all():
                try:
                    if pd.is_applied():
                        applied_pds.append(pd)
                except Exception:
                    # conservative: treat unknown as applied
                    applied_pds.append(pd)

            if applied_pds:
                self.message_user(
                    request,
                    "Cannot delete policy: it is applied to one or more devices. Revoke application on devices first.",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(reverse("admin:%s_%s_change" % (self.model._meta.app_label, self.model._meta.model_name), args=[object_id]))
        except Exception:
            # conservative fallback
            self.message_user(request, "Unable to determine apply state; deletion refused.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:%s_%s_change" % (self.model._meta.app_label, self.model._meta.model_name), args=[object_id]))

        return super().delete_view(request, object_id, extra_context=extra_context)

    def delete_model(self, request, obj):
        try:
            for pd in obj.policy_devices.all():
                if pd.is_applied():
                    self.message_user(request, "Cannot delete policy: it is applied to one or more devices.", level=messages.ERROR)
                    return
        except Exception:
            self.message_user(request, "Unable to determine apply state; deletion refused.", level=messages.ERROR)
            return

        try:
            super().delete_model(request, obj)
            self.message_user(request, "Policy deleted.", level=messages.SUCCESS)
        except ProtectedError:
            self.message_user(request, "Cannot delete policy: it is protected / applied.", level=messages.ERROR)

    def custom_delete_selected(self, request, queryset):
        succeeded = 0
        skipped = []

        for policy in queryset:
            try:
                # if any attached PolicyDevice is applied, skip this policy
                blocked = False
                for pd in policy.policy_devices.all():
                    try:
                        if pd.is_applied():
                            blocked = True
                            break
                    except Exception:
                        blocked = True
                        break
                
                if blocked:
                    skipped.append(str(policy))
                    continue

                # safe to delete
                policy.delete()
                succeeded += 1
            except Exception:
                skipped.append(str(policy))

        if succeeded:
            self.message_user(request, f"{succeeded} Policies deleted.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Skipped {len(skipped)} policies because they are applied or state unknown: {', '.join(skipped)}", level=messages.ERROR)

    custom_delete_selected.short_description = "Delete selected policies (skip applied)"

    def policy_actions(self, obj):
        apply_devices_url = reverse("admin:policies_policy_apply", args=[obj.pk])
        apply_departments_url = reverse("admin:policies_policy_apply_departments", args=[obj.pk])
        delete_devices_url = reverse("admin:policies_policy_delete_devices", args=[obj.pk])
        delete_departments_url = reverse("admin:policies_policy_delete_departments", args=[obj.pk])

        return format_html(
            """
            <div class="form-actions admin-policy-actions-inline">
                <label class="admin-policy-action-label" for="policy-action-{4}">Choose action</label>
                <select id="policy-action-{4}" class="admin-schema-select form-control" name="action_url">
                    <option value="{0}">Apply to all devices</option>
                    <option value="{1}">Apply to all departments</option>
                    <option value="{2}">Delete from all devices</option>
                    <option value="{3}">Delete from all departments</option>
                </select>
                <button
                    type="button"
                    class="button admin-action-button admin-policy-action-submit"
                    onclick="window.location.href=document.getElementById('policy-action-{4}').value;"
                >
                    Apply
                </button>
            </div>
            """,
            apply_devices_url,
            apply_departments_url,
            delete_devices_url,
            delete_departments_url,
            obj.pk,
        )
    policy_actions.short_description = "Policy Actions"
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "push-notification/",
                self.admin_site.admin_view(self.quick_push_notification_view),
                name="policies_policy_quick_push_notification",
            ),
            path(
                "push-notification/options/",
                self.admin_site.admin_view(self.quick_push_notification_options_view),
                name="policies_policy_quick_push_notification_options",
            ),
            path(
                "<uuid:policy_id>/apply/",
                self.admin_site.admin_view(self.apply_policy_view),
                 name="policies_policy_apply",
            ),
            path(
                "<uuid:policy_id>/apply_departments/",
                self.admin_site.admin_view(self.apply_policy_departments_view),
                name="policies_policy_apply_departments",
            ),
            path(
                "<uuid:policy_id>/delete_devices/",
                self.admin_site.admin_view(self.delete_from_all_devices_view),
                name="policies_policy_delete_devices",
            ),
            path(
                "<uuid:policy_id>/delete_departments/",
                self.admin_site.admin_view(self.delete_from_all_departments_view),
                name="policies_policy_delete_departments",
            ),
        ]
        return custom_urls + urls

    def _resolve_push_notification_module_field(self):
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

    def quick_push_notification_options_view(self, request):
        target_type = request.GET.get("target_type")
        if target_type == "department":
            options = [
                {"id": str(item.pk), "label": item.name}
                for item in Department.objects.order_by("name")
            ]
            return JsonResponse({"options": options})

        if target_type == "device":
            options = [
                {"id": str(item.pk), "label": item.device_name}
                for item in Device.objects.order_by("device_name")
            ]
            return JsonResponse({"options": options})

        return JsonResponse({"options": []})

    def quick_push_notification_view(self, request):
        if request.method != "POST":
            return redirect("admin:index")

        title = (request.POST.get("title") or "").strip()
        body = (request.POST.get("body") or "").strip()
        image_url = (request.POST.get("image_url") or "").strip()
        tag = (request.POST.get("tag") or "").strip()
        target_type = (request.POST.get("target_type") or "").strip()
        target_id = (request.POST.get("target_id") or "").strip()

        if not title or not body:
            self.message_user(request, "Title and body are required.", level=messages.ERROR)
            return redirect("admin:index")

        if target_type not in {"department", "device"} or not target_id:
            self.message_user(request, "Choose a valid target type and target.", level=messages.ERROR)
            return redirect("admin:index")

        action_type = ActionType.objects.filter(name="MakeNotification").first()
        if not action_type:
            self.message_user(
                request,
                "ActionType 'MakeNotification' is missing. Please run seed_data first.",
                level=messages.ERROR,
            )
            return redirect("admin:index")

        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        schedule_time = timezone.now() + timedelta(seconds=5)
        expiration_date = schedule_time + timedelta(hours=1)
        module_field = self._resolve_push_notification_module_field()
        if not module_field:
            self.message_user(
                request,
                "No ModuleField records were found. Please run seed_data before sending push notifications.",
                level=messages.ERROR,
            )
            return redirect("admin:index")

        action_payload = {
            "title": title,
            "body": body,
            "image_url": image_url or None,
            "tag": tag,
        }

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
                    raise Http404("Department not found")
                policy.departments.add(department)
                target_devices = Device.objects.filter(department=department)
            else:
                device = Device.objects.filter(pk=target_id).first()
                if not device:
                    raise Http404("Device not found")
                target_devices = Device.objects.filter(pk=device.pk)

            queued = 0
            for device in target_devices:
                policy_device, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
                cmd = Command.objects.create(
                    policy_device=policy_device,
                    command_type=Command.COMMAND_CREATE,
                    status=Command.STATUS_PENDING,
                )
                send_command_to_device.delay(str(cmd.pk))
                queued += 1

        if queued == 0:
            self.message_user(
                request,
                "Push notification policy created but no devices were found for the selected target.",
                level=messages.WARNING,
            )
        else:
            self.message_user(
                request,
                f"Push notification created and queued for {queued} device(s).",
                level=messages.SUCCESS,
            )

        return redirect("admin:index")
    
    def apply_summary(self, obj):
        cmds = Command.objects.filter(policy_device__policy=obj)
        context = {
            "sent": cmds.filter(status=Command.STATUS_SENT).count(),
            "ack": cmds.filter(status=Command.STATUS_ACK).count(),
            "applied": cmds.filter(status=Command.STATUS_APPLIED).count(),
            "failed": cmds.filter(status=Command.STATUS_FAILED).count(),
            "created": cmds.filter(status=Command.STATUS_CREATED).count(),
            "pending": cmds.filter(status=Command.STATUS_PENDING).count(),
        }
        return render_to_string("admin/policies/policy_summary.html", context)
    apply_summary.short_description = "Commands"

    def total_devices(self, obj):
        return obj.get_target_devices().count()
    total_devices.short_description = "Devices"


    def apply_policy_view(self, request, policy_id):
        close_old_connections()
        policy = get_object_or_404(Policy, pk=policy_id)
        for device in policy.get_target_devices():
            pd, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
            with transaction.atomic():
                # create a new command and queue it
                cmd = Command.objects.create(policy_device=pd, command_type=Command.COMMAND_CREATE, status=Command.STATUS_PENDING)
                # queue send task
            send_command_to_device.delay(str(cmd.pk))
        self.message_user(request, "Apply queued for all devices.", level=messages.SUCCESS)
        return redirect("admin:policies_policy_changelist")
    
    def apply_selected_policies(modeladmin, request, queryset):
        close_old_connections()
        for policy in queryset:
            for device in policy.get_target_devices():
                pd, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
                with transaction.atomic():
                    cmd = Command.objects.create(policy_device=pd, command_type=Command.COMMAND_CREATE, status=Command.STATUS_PENDING)
                send_command_to_device.delay(str(cmd.pk))
        modeladmin.message_user(request, "Apply queued for selected policies.", level=messages.SUCCESS)
    apply_selected_policies.short_description = "Apply selected policies to all included devices"

    def apply_policy_departments_view(self, request, policy_id):
        close_old_connections()
        policy = get_object_or_404(Policy, pk=policy_id)
        all_departments = Department.objects.all()
        policy.departments.set(all_departments)

        queued = 0
        for device in policy.get_target_devices():
            pd, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
            with transaction.atomic():
                cmd = Command.objects.create(
                    policy_device=pd,
                    command_type=Command.COMMAND_CREATE,
                    status=Command.STATUS_PENDING,
                )
            send_command_to_device.delay(str(cmd.pk))
            queued += 1

        self.message_user(
            request,
            f"Policy linked to all departments. Apply queued for {queued} devices.",
            level=messages.SUCCESS,
        )
        return redirect("admin:policies_policy_changelist")

    def delete_from_all_devices_view(self, request, policy_id):
        close_old_connections()
        policy = get_object_or_404(Policy, pk=policy_id)
        queued = 0

        for device in policy.get_target_devices():
            pd, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
            with transaction.atomic():
                cmd = Command.objects.create(
                    policy_device=pd,
                    command_type=Command.COMMAND_DELETE,
                    status=Command.STATUS_PENDING,
                )
            send_command_to_device.delay(str(cmd.pk))
            queued += 1

        self.message_user(request, f"Delete queued for {queued} devices.", level=messages.SUCCESS)
        return redirect("admin:policies_policy_changelist")

    def delete_from_all_departments_view(self, request, policy_id):
        close_old_connections()
        policy = get_object_or_404(Policy, pk=policy_id)
        department_devices = Device.objects.filter(department__in=policy.departments.all()).distinct()

        queued = 0
        for device in department_devices:
            pd, _ = PolicyDevice.objects.get_or_create(policy=policy, device=device)
            with transaction.atomic():
                cmd = Command.objects.create(
                    policy_device=pd,
                    command_type=Command.COMMAND_DELETE,
                    status=Command.STATUS_PENDING,
                )
            send_command_to_device.delay(str(cmd.pk))
            queued += 1

        policy.departments.clear()

        self.message_user(
            request,
            f"Policy removed from all departments. Delete queued for {queued} devices.",
            level=messages.SUCCESS,
        )
        return redirect("admin:policies_policy_changelist")



class ModuleFieldInline(admin.TabularInline):
    model = ModuleField
    extra = 0

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    inlines = [ModuleFieldInline]
    search_fields = ("name",)


class ActionInline(admin.TabularInline):
    model = Action
    extra = 0

@admin.register(ActionType)
class ActionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    inlines = [ActionInline]
    search_fields = ("name",)


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Main Info", {
            "fields": ("name", "description", "action_type", "input", "dynamic_input_fields_display"),
        }),
        ("Trigger Settings", {
            "fields": ("trigger_kind_id", "regex", "exact_time"),
            "classes": ("collapse",),
        }),
    )
    
    class Media:
        js = ("policies/js/admin_action_input_helper.js",)
    
    form = ActionAdminForm
    list_display = ("name", "action_type", "trigger_kind", "main_action_status", "input_preview",)
    search_fields = ("name", "action_type__name")
    list_filter = ("action_type", "trigger_kind_id",)
    readonly_fields = ("dynamic_input_fields_display",)
    
    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def has_delete_permission(self, request, obj=None):
        if obj and not obj.is_deletable:
            return False
        return super().has_delete_permission(request, obj)

    def main_action_status(self, obj):
        if obj.is_main_action:
            return "Main action (not deletable)"
        return "Custom"
    main_action_status.short_description = "Action category"
    
    def trigger_kind(self, obj):
        return obj.get_trigger_kind_id_display()
    trigger_kind.short_description = "Trigger kind"
    
    def input_preview(self, obj):
        return format_html("<pre class='admin-json-preview'>{}</pre>", obj.input if obj.input else "{}")
    input_preview.short_description = "Input (JSON)"
    
    def dynamic_input_fields_display(self, obj):
        """Render a container for schema-driven dynamic input fields."""
        dummy_uuid = "00000000-0000-0000-0000-000000000000"
        base_url = reverse("admin:policies_actiontype_schema", args=[dummy_uuid])
        initial_value = obj.input if obj and getattr(obj, "input", None) is not None else {}
        return format_html(
            "<div id='action-type-schema-fields' data-base-url='{}' data-initial-input='{}'></div>",
            base_url,
            json.dumps(initial_value),
        )
    dynamic_input_fields_display.short_description = ""
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "actiontype-schema/<str:actiontype_id>/",
                self.admin_site.admin_view(self.actiontype_schema_view),
                name="policies_actiontype_schema",
            ),
        ]
        return custom_urls + urls

    def actiontype_schema_view(self, request, actiontype_id):
        """
        Admin-only JSON endpoint returning schema metadata for the selected ActionType.
        Return 200 with schema:null when not found so front-end can safely clear dynamic fields.
        Try to be forgiving about the format of actiontype_id (UUID string, PK, or name).
        """
        
        # try UUID first
        at = None
        try:
            # if it's a UUID-like string, convert and lookup by pk
            possible_uuid = uuid.UUID(actiontype_id)
            try:
                at = ActionType.objects.get(pk=possible_uuid)
            except ActionType.DoesNotExist:
                at = None
        except (ValueError, TypeError):
            # not a UUID — try primary key and name fallback
            try:
                at = ActionType.objects.get(pk=actiontype_id)
            except ActionType.DoesNotExist:
                try:
                    at = ActionType.objects.get(name=actiontype_id)
                except ActionType.DoesNotExist:
                    at = None

        # if not found, return schema:null with 200 so front-end clears field state
        if not at:
            return JsonResponse({"schema": None})

        return JsonResponse({"schema": at.input_schema})

@admin.register(PolicyDevice)
class PolicyDeviceAdmin(admin.ModelAdmin):
    list_display = ("policy", "device", "last_update", "latest_command", "apply_button", "read_all_button")
    inlines = [CommandInline]
    readonly_fields = ("last_update",)
    search_fields = ("policy__name", "device__device_id")
    actions = ["custom_delete_selected"]
    
    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions
    
    def delete_view(self, request, object_id, extra_context=None):
        """
        Intercept the default delete confirmation flow. If the object is applied, refuse
        deletion immediately and redirect back to the object change page with an error message.
        Otherwise, fall back to the default behavior (which will show confirmation and then delete).
        """
        obj = get_object_or_404(self.model, pk=object_id)

        try:
            if obj.is_applied():
                self.message_user(
                    request,
                    "Cannot delete this PolicyDevice: it is applied on the device. Revoke the policy first.",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(reverse("admin:%s_%s_change" % (self.model._meta.app_label, self.model._meta.model_name), args=[object_id]))
        except Exception:
            self.message_user(
                request,
                "Unable to determine apply state; deletion refused.",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse("admin:%s_%s_change" % (self.model._meta.app_label, self.model._meta.model_name), args=[object_id]))

        return super().delete_view(request, object_id, extra_context=extra_context)

    
    def delete_model(self, request, obj):
        try:
            if obj.is_applied():
                self.message_user(request, "Cannot delete this PolicyDevice: it is applied on the device.", level=messages.ERROR)
                return
        except Exception:
            self.message_user(request, "Unable to determine apply state; deletion refused.", level=messages.ERROR)
            return

        # safe to delete
        super().delete_model(request, obj)
        self.message_user(request, "PolicyDevice deleted successfully.", level=messages.SUCCESS)


    def custom_delete_selected(self, request, queryset):
        succeeded = 0
        failed = []

        for obj in queryset:
            try:
                if obj.is_applied():
                    failed.append(str(obj))
                    continue
            except Exception:
                failed.append(str(obj))
                continue

            obj.delete()
            succeeded += 1

        if succeeded:
            self.message_user(request, f"{succeeded} PolicyDevice records deleted.", level=messages.SUCCESS)
        if failed:
            self.message_user(
                request,
                f"Skipped {len(failed)} PolicyDevice records because they are applied or state unknown: {', '.join(failed)}",
                level=messages.ERROR,
            )

    custom_delete_selected.short_description = "Delete selected PolicyDevice (skip applied)"


    def latest_command(self, obj):
        latest = obj.commands.order_by("-created_at").first()
        if not latest:
            return "—"
        return format_html("{}. {} ({})", latest.command_type, latest.status, latest.created_at.isoformat())
    latest_command.short_description = "Latest Command"
    
    def apply_button(self, obj):
        if not obj.pk:
            return ""
        url = reverse("admin:policies_policydevice_apply", args=[str(obj.pk)])
        return format_html('<a class="button admin-action-button" href="{}">Apply</a>', url)
    apply_button.short_description = "Apply"
    
    def read_all_button(self, obj):
        """Button on PolicyDevice change list and change view to trigger READ_ALL for the device."""
        if not obj or not obj.pk:
            return ""
        url = reverse("admin:policies_policydevice_read_all", args=[str(obj.pk)])
        return format_html('<a class="button admin-action-button" href="{}">Read All (from device)</a>', url)
    read_all_button.short_description = "Read All"

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:policy_device_id>/apply/",
                self.admin_site.admin_view(self.apply_policy_device_view),
                name="policies_policydevice_apply",
            ),
            path(
                "<uuid:policy_device_id>/create_command/",
                self.admin_site.admin_view(self.create_command_and_send_view),
                name="policies_policydevice_create_command",
            ),
            path(
                "<uuid:policy_device_id>/read_all/",
                self.admin_site.admin_view(self.read_all_and_send_view),
                name="policies_policydevice_read_all",
            ),
        ]
        return custom_urls + urls

    def apply_policy_device_view(self, request, policy_device_id):
        close_old_connections()
        pd = get_object_or_404(PolicyDevice, pk=policy_device_id)
        
        with transaction.atomic():
            cmd = Command.objects.create(policy_device=pd, command_type=Command.COMMAND_CREATE, status=Command.STATUS_PENDING)
        send_command_to_device.delay(str(cmd.pk))
        
        self.message_user(
            request,
            f"Apply queued for device {pd.device} (policy {pd.policy.name}).",
            level=messages.SUCCESS
        )
        return redirect("admin:policies_policydevice_change", pd.pk)

    def create_command_and_send_view(self, request, policy_device_id):
        """
        This view is used by the 'Create & Send Command' button shown on the PolicyDevice change page.
        It creates a new Command and enqueues send_command_to_device.
        """
        close_old_connections()
        pd = get_object_or_404(PolicyDevice, pk=policy_device_id)

        with transaction.atomic():
            cmd = Command.objects.create(policy_device=pd, command_type=Command.COMMAND_CREATE, status=Command.STATUS_PENDING)
        send_command_to_device.delay(str(cmd.pk))

        self.message_user(request, "Command created and queued.", level=messages.SUCCESS)
        return redirect("admin:policies_policydevice_change", pd.pk)

    def read_all_and_send_view(self, request, policy_device_id):
        """
        Create a READ_ALL command that targets the device directly (device-level command) and send it.
        """
        close_old_connections()
        pd = get_object_or_404(PolicyDevice, pk=policy_device_id)
        device = pd.device

        with transaction.atomic():
            cmd = Command.objects.create(device=device, policy_device=pd, command_type=Command.COMMAND_READ_ALL, status=Command.STATUS_PENDING)

        send_command_to_device.delay(str(cmd.pk))

        self.message_user(request, f"READ_ALL queued for device {device}.", level=messages.SUCCESS)
        return redirect("admin:policies_policydevice_change", pd.pk)
    

@admin.register(Command)
class CommandAdmin(admin.ModelAdmin):
    list_display = ("command_subject", "command_type", "status", "attempts", "pretty_response", "created_at", "last_update", "send_button")
    list_filter = ("command_type", "status", "created_at")
    search_fields = ("id", "policy_device__policy__name", "policy_device__device__device_id")
    readonly_fields = ("id",  "status", "attempts", "mqtt_message_id", "pretty_response", "response", "payload", "created_at", "last_update")
    actions = ["resend_selected_commands"]

    def command_subject(self, obj):
        if obj.policy_device:
            return str(obj.policy_device)
        if obj.device:
            return obj.device.device_name
        return "—"
    command_subject.short_description = "Target"
    
    def pretty_response(self, obj):
        if not obj.response:
            return "—"
        return format_html("<pre class='admin-json-box admin-response-preview'>{}</pre>", json.dumps(obj.response, indent=2))
    pretty_response.short_description = "Response"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:command_id>/send/",
                self.admin_site.admin_view(self.send_command_view),
                name="policies_command_send",
            ),
        ]
        return custom_urls + urls

    def send_button(self, obj):
        if not obj or not obj.pk:
            return ""
        url = reverse("admin:policies_command_send", args=[str(obj.pk)])
        return format_html('<a class="button admin-action-button" href="{}">Send</a>', url)
    send_button.short_description = "Send"

    def send_command_view(self, request, command_id):
        """
        Admin view to enqueue sending a specific Command.
        """
        close_old_connections()
        cmd = get_object_or_404(Command, pk=command_id)

        try:
            send_command_to_device.delay(str(cmd.pk))
            self.message_user(request, f"Command {cmd.pk} requeued for sending.", level=messages.SUCCESS)
        except Exception as exc:
            self.message_user(request, f"Failed to enqueue command {cmd.pk}: {exc}", level=messages.ERROR)

        # Redirect back to the Command change page if it exists, otherwise policydevice change
        return redirect("admin:policies_command_changelist")

    def resend_selected_commands(self, request, queryset):
        count = 0
        for cmd in queryset:
            try:
                send_command_to_device.delay(str(cmd.pk))
                count += 1
            except Exception:
                self.message_user(request, f"Failed to requeue command {cmd.pk}", level=messages.ERROR)
        self.message_user(request, f"Requeued {count} commands.", level=messages.SUCCESS)
    resend_selected_commands.short_description = "Resend selected commands"
    
@admin.register(DevicePolicySnapshot)
class DevicePolicySnapshotAdmin(admin.ModelAdmin):
    list_display = ("__str__", "device_link", "policy_link", "command_link", "snapshot_truncated")
    list_filter = ("device", "created_at")
    search_fields = ("device__device_id", "policy_id", "command__id")
    readonly_fields = ("snapshot_pretty", "device", "command", "policy_id", "created_at", "snapshot")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ["export_as_json", "export_as_csv"]
    
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("device", "command__policy_device__policy")
    
    def device_link(self, obj):
        if not obj.device:
            return "—"
        try:
            url = reverse("admin:devices_device_change", args=[obj.device.pk])
            return format_html('<a href="{}">{}</a>', url, obj.device.device_name)
        except Exception:
            return str(obj.device)
    device_link.short_description = "Device"
    device_link.admin_order_field = "device__device_id"
    
    def policy_link(self, obj):
        policy = None
        if obj.command and obj.command.policy_device:
            policy = obj.command.policy_device.policy
        elif obj.policy_id:
            policy = Policy.objects.filter(policy_id=obj.policy_id).first()

        if not policy:
            return "—"

        try:
            url = reverse("admin:policies_policy_change", args=[policy.pk])
            return format_html('<a href="{}">{}</a>', url, policy.name)
        except Exception:
            return policy.name
    policy_link.short_description = "Policy"
    
    def command_link(self, obj):
        if not obj.command:
            return "—"
        try:
            url = reverse("admin:policies_command_change", args=[obj.command.pk])
            return format_html('<a href="{}">{}</a>', url, str(obj.command.id)[:8])
        except Exception:
            return str(obj.command.id)
    command_link.short_description = "Command"
    command_link.admin_order_field = "command__created_at"
    
    def snapshot_truncated(self, obj):
        """
        Small preview in list view. Truncate long JSON for readability.
        """
        try:
            pretty = json.dumps(obj.snapshot, indent=2)
        except Exception:
            pretty = str(obj.snapshot)
        # show first ~200 chars
        truncated = pretty if len(pretty) <= 200 else pretty[:200] + "...\n( truncated )"
        return format_html("<pre class='admin-json-preview'>{}</pre>", truncated)
    snapshot_truncated.short_description = "Snapshot (preview)"
    
    def snapshot_pretty(self, obj):
        if not obj or obj.snapshot is None:
            return "—"
        try:
            pretty = json.dumps(obj.snapshot, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.snapshot)
        return format_html("<pre class='admin-json-full'>{}</pre>", pretty)
    snapshot_pretty.short_description = "Snapshot (full JSON)"
    
    def raw_snapshot(self, obj):
        return json.dumps(obj.snapshot, ensure_ascii=False)
    raw_snapshot.short_description = "Raw JSON"
    
    def export_as_json(self, request, queryset):
        """
        Export selected snapshots as a JSON array. Returns a downloadable file.
        """
        if not queryset.exists():
            self.message_user(request, "No snapshots selected.", level=messages.WARNING)
            return None

        data = []
        for s in queryset.order_by("-created_at"):
            data.append({
                "id": str(s.id),
                "device_id": s.device.device_id if s.device else None,
                "command_id": str(s.command.id) if s.command else None,
                "policy_id": str(s.policy_id) if s.policy_id else None,
                "created_at": s.created_at.isoformat(),
                "snapshot": s.snapshot,
            })

        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        response = HttpResponse(content, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="device_policy_snapshots.json"'
        return response
    export_as_json.short_description = "Export selected snapshots as JSON"
    
    
    def export_as_csv(self, request, queryset):
        """
        Export selected snapshots as CSV. Snapshot JSON is placed in one column (as string).
        """
        if not queryset.exists():
            self.message_user(request, "No snapshots selected.", level=messages.WARNING)
            return None

        # Create in-memory CSV
        f = io.StringIO()
        writer = csv.writer(f)
        writer.writerow(["id", "device_id", "command_id", "policy_id", "created_at", "snapshot_json"])
        for s in queryset.order_by("-created_at"):
            snapshot_text = json.dumps(s.snapshot, ensure_ascii=False)
            writer.writerow([
                str(s.id),
                s.device.device_id if s.device else "",
                str(s.command.id) if s.command else "",
                str(s.policy_id) if s.policy_id else "",
                s.created_at.isoformat(),
                snapshot_text,
            ])

        f.seek(0)
        response = HttpResponse(f.read().encode("utf-8"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="device_policy_snapshots.csv"'
        return response
    export_as_csv.short_description = "Export selected snapshots as CSV"
    

@admin.register(PushNotificationLauncher)
class PushNotificationLauncherAdmin(admin.ModelAdmin):
    # This prevents the dummy model from having its own empty page
    def changelist_view(self, request, extra_context=None):
        # Redirect back to dashboard but tell it to open the modal
        return redirect(f"{reverse('admin:index')}?open_push=1")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False