import json
import time
import logging
import paho.mqtt.client as mqtt

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from devices.models import Device
from policies.models import PolicyDevice, Command as CMD, DevicePolicySnapshot
from django.db.models import Q
from policies.tasks import send_command_to_device # Importing the task to send policies
from devices.tasks import store_log # Importing the task to store logs


logger = logging.getLogger(__name__)

MAX_REPUBLISH_ATTEMPTS = 5
MQTT_CLIENT_ID = "django_mqtt_worker" # if you scale, use unique client ids per instance

class Command(BaseCommand):
    help = "MQTT worker: subscribe to logs/status/states and handle re-publishing & states of policies."
    
    def handle(self, *args, **options):
        client = mqtt.Client(client_id=MQTT_CLIENT_ID, userdata=None)
        if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
            client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_disconnect = self.on_disconnect
        
        while True:
            try:
                client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
                logger.info("Connected to MQTT broker at %s:%s", settings.MQTT_HOST, settings.MQTT_PORT)
                client.loop_forever()
            except Exception as exc:
                logger.exception("MQTT connection error, retrying in 3s: %s", exc)
                time.sleep(3)
    
    def on_connect(self, client, userdata, flags, rc):
        logger.info("MQTT on_connect rc=%s", rc)
        
        client.subscribe("logs/+", qos=1)
        client.subscribe("status/+", qos=1)
        client.subscribe("state/+/+/+", qos=1)
        
        logger.info("Subscribed to topics: logs/+, status/+, state/+/+/+")
        
    def on_disconnect(self, client, userdata, rc):
        logger.warning("MQTT disconnected with rc=%s", rc)
    
    def on_message(self, client, userdata, msg):
        close_old_connections()
        topic = msg.topic
        payload_text = msg.payload.decode("utf-8", errors="ignore")
        logger.debug("MQTT message on %s: %s", topic, payload_text)
        
        try:
            if topic.startswith("logs/"):
                # logs/<agent_id>
                parts = topic.split("/", 1)
                if len(parts) != 2:
                    logger.warning("Invalid logs topic: %s", topic)
                    return
                
                _, agent_id = parts
                device = Device.objects.filter(device_id=agent_id).first()
                
                if not device:
                    logger.warning("Log from unknown device %s: %s", agent_id, payload_text)
                    return
                
                try:
                    log_data = json.loads(payload_text)
                except Exception:
                    log_data = {"message": payload_text}

                store_log.delay(agent_id, log_data)
                return

            if topic.startswith("status/"):
                # status/<device_id>
                parts = topic.split("/", 1)
                if len(parts) != 2:
                    logger.warning("Invalid status topic: %s", topic)
                    return
                _, device_id = parts
                status_val = payload_text.strip().lower()

                self.handle_status(device_id, status_val)
                return

            if topic.startswith("state/"):
                # state/<device_id>/<policy_id>/<command_id>
                parts = topic.split("/")
                if len(parts) < 4:
                    logger.warning("Invalid state topic: %s", topic)
                    return
                _, device_id, policy_id, command_id = parts[:4]
                self.handle_state(device_id, policy_id, command_id, payload_text)
                return

            logger.debug("Unhandled topic: %s", topic)
        except Exception:
            logger.exception("Failed processing MQTT message on %s", topic)
    
    def handle_status(self, device_id: str, status_val: str):
        close_old_connections()
        
        # find device (try matching device_id exactly).
        device = Device.objects.filter(device_id=device_id).first()
        if not device:
            logger.warning("Status for unknown device %s: %s", device_id, status_val)
            return

        when = timezone.now()
        try:
            with transaction.atomic():
                device.last_seen = when
                device.status = Device.STATUS_ONLINE if status_val == "online" else Device.STATUS_OFFLINE
                device.save(update_fields=["last_seen", "status"])
            logger.info("Updated device %s status=%s", device_id, device.status)
        except Exception:
            logger.exception("Failed to update device status for %s", device_id)
            return

        # If device went online, requeue pending policies
        if status_val == "online":
            self.handle_device_online(device_id)

    def handle_device_online(self, device_id: str):
        """
        Re-publish pending policies for this device (status == PENDING and attempts < MAX_REPUBLISH_ATTEMPTS).
        """
        close_old_connections()
        pending_cmds = CMD.objects.filter(
            Q(policy_device__device__device_id=device_id) | Q(device__device_id=device_id),
            status__in=[CMD.STATUS_PENDING, CMD.STATUS_SENT],
            attempts__lt=MAX_REPUBLISH_ATTEMPTS
        )

        count = pending_cmds.count()
        logger.info("Found %d pending commands for device %s", count, device_id)

        for cmd in pending_cmds:
            try:
                send_command_to_device.delay(str(cmd.pk))
                if cmd.policy_device and cmd.policy_device.policy:
                    policy_id = cmd.policy_device.policy.policy_id
                logger.info("Requeued command %s for policy %s -> device %s", cmd.pk, policy_id, device_id)
            except Exception:
                logger.exception("Failed requeueing command %s", cmd.pk)

    def handle_state(self, device_id: str, policy_id: str, command_id: str, payload_text: str):
        close_old_connections()
        try:
            data = json.loads(payload_text)
        except Exception:
            logger.warning("Invalid JSON in State payload: %s", payload_text)
            return

        cmd = CMD.objects.select_related("policy_device__device", "device", "policy_device__policy").filter(pk=command_id).first()
        if not cmd:
            logger.warning("State for unknown command_id %s (device=%s policy=%s)", command_id, device_id, policy_id)
            return

        # Determine expected device id for the command
        cmd_device = None
        if cmd.device:
            cmd_device = cmd.device.device_id
        elif cmd.policy_device and cmd.policy_device.device:
            cmd_device = cmd.policy_device.device.device_id
        
        if not cmd_device:
            logger.warning("Command %s has no associated device (inconsistent)", cmd.pk)
            return
        
        # Validate device matches the topic
        if str(cmd_device) != str(device_id):
            logger.warning("State device_id mismatch for command %s: expected %s, got %s", cmd.pk, cmd_device, device_id)
            return
        
        # For policy-scoped commands ensure policy id matches topic.
        if cmd.command_type not in (CMD.COMMAND_READ_ALL, CMD.COMMAND_DELETE_ALL):
            if not cmd.policy_device or str(cmd.policy_device.policy.policy_id) != str(policy_id):
                logger.warning("Policy mismatch for command %s: expected policy %s but got topic policy %s", cmd.pk,
                            getattr(cmd.policy_device.policy, "policy_id", None), policy_id)
                return
        else:
            # READ_ALL/DELETE_ALL are device-level and should use policy id "ALL" in topic.
            if policy_id != "ALL":
                logger.warning("Policy mismatch for %s command %s: expected 'ALL' but got topic policy %s", cmd.command_type, cmd.pk, policy_id)
                return


        state = data.get("state", "").upper()
        accepted_states = {CMD.STATUS_ACK, CMD.STATUS_APPLIED, CMD.STATUS_FAILED}
        
        if state not in accepted_states:
            logger.warning("Unknown state value from device %s for command %s (policy %s): %s", device_id, command_id, policy_id, state)
            return
        
        try:
            with transaction.atomic():
                cmd.status = state
                cmd.response = data.get("response", data)
                cmd.last_update = timezone.now()
                cmd.save(update_fields=["status", "response", "last_update"])
            logger.info("Command %s State %s by device %s", cmd.pk, state, device_id)
            
            if cmd.command_type in (CMD.COMMAND_READ, CMD.COMMAND_READ_ALL):
                try:
                    resp = cmd.response or {}

                    # READ_ALL expected structure: {"policies": [ {...}, {...} ] }
                    if isinstance(resp.get("policies"), list):
                        policies = resp.get("policies", [])
                        for p in policies:
                            DevicePolicySnapshot.objects.create(
                                device=cmd.device or cmd.policy_device.device,
                                command=cmd,
                                policy_id=p.get("policy_id"),
                                snapshot=p
                            )
                    # Single policy read: {"policy": { ... } } or response directly the policy object
                    elif isinstance(resp.get("policy"), dict):
                        p = resp.get("policy")
                        DevicePolicySnapshot.objects.create(
                            device=cmd.device or cmd.policy_device.device,
                            command=cmd,
                            policy_id=p.get("policy_id"),
                            snapshot=p
                        )
                    else:
                        # If resp itself looks like a policy mapping with 'policy_id' key, store it.
                        if isinstance(resp, dict) and resp.get("policy_id"):
                            DevicePolicySnapshot.objects.create(
                                device=cmd.device or cmd.policy_device.device,
                                command=cmd,
                                policy_id=resp.get("policy_id"),
                                snapshot=resp
                            )
                        else:
                            # Unknown shape — still store the whole response as a snapshot (policy_id=None)
                            DevicePolicySnapshot.objects.create(
                                device=cmd.device or cmd.policy_device.device,
                                command=cmd,
                                policy_id=None,
                                snapshot=resp
                            )
                except Exception:
                    logger.exception("Failed to persist READ response snapshots for command %s", cmd.pk)
                    logger.debug("Response data: %s", cmd.response)

        except Exception:
            logger.exception("Failed to update Command State (id: %s)", getattr(cmd, "pk", None))