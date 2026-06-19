from rest_framework import serializers

class AccountLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    android_id = serializers.CharField(required=False, allow_blank=False)
    imei = serializers.CharField(required=True, allow_blank=False)


class AccountLogoutSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    android_id = serializers.CharField(required=False, allow_blank=False)
    imei = serializers.CharField(required=True, allow_blank=False)