from rest_framework import serializers

from devices.models import Department, Device


class PushNotificationTargetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=("department", "device"))
    id = serializers.UUIDField()

    def validate(self, attrs):
        target_type = attrs["type"]
        target_id = attrs["id"]

        if target_type == "department":
            if not Department.objects.filter(pk=target_id).exists():
                raise serializers.ValidationError({"id": "Department not found."})
        elif target_type == "device":
            if not Device.objects.filter(pk=target_id).exists():
                raise serializers.ValidationError({"id": "Device not found."})

        return attrs


class ExternalPushNotificationRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, allow_blank=False)
    body = serializers.CharField(allow_blank=False)
    image_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    tag = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    target = PushNotificationTargetSerializer()


class ExternalPushNotificationResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    policy_id = serializers.UUIDField()
    action_id = serializers.UUIDField()
    queued_devices = serializers.IntegerField()
    command_ids = serializers.ListField(child=serializers.UUIDField())
