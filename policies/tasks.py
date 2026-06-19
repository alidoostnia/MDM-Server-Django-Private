import json
import paho.mqtt.client as mqtt
from celery import shared_task
from django.conf import settings
from .models import PolicyDevice, Command
import time
from django.db import close_old_connections, transaction


@shared_task(bind=True, max_retries=3)
def send_command_to_device(self, command_id: str):
    """
    Ensure there's a Command for this PolicyDevice and publish it.
    If command_id provided, operate on that Command; otherwise create a new one.
    """
    close_old_connections()
    try:
        cmd = Command.objects.select_related(
            "policy_device__policy__module_field__module",
            "policy_device__device",
            "device"
        ).get(pk=command_id)          
        
        payload = cmd.to_command_json()
        
        device = cmd.device or (cmd.policy_device.device if cmd.policy_device else None)
        if device is None:
            raise ValueError(f"Cannot send command {cmd.pk}: no target device available.")
        
        client = mqtt.Client()
        if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
            client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
        topic = f"policies/{device.device_id}"
        client.loop_start()
        info = client.publish(topic, json.dumps(payload), qos=1)
        
         
        with transaction.atomic():
            cmd = Command.objects.select_for_update().get(pk=cmd.pk)
            
            if getattr(info, "rc", None) == mqtt.MQTT_ERR_SUCCESS:
                    cmd.status = Command.STATUS_SENT
                    cmd.mqtt_message_id = str(getattr(info, "mid", ""))
            else:
                cmd.status = Command.STATUS_PENDING
            
            cmd.attempts = (cmd.attempts or 0) + 1
            cmd.payload = payload
            cmd.save(update_fields=["status", "mqtt_message_id", "attempts", "payload", "last_update"])
        
        client.loop_stop()
        client.disconnect()

    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)