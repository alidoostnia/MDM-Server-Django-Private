from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from .permissions import CanSendPushNotifications
from .serializers import (
    ExternalPushNotificationRequestSerializer,
    ExternalPushNotificationResponseSerializer,
)
from .services import PushNotificationServiceError, create_push_notification


@swagger_auto_schema(
    method="post",
    operation_description=(
        "Queue a push notification for an existing MDM device or department. "
        "This endpoint reuses the existing MakeNotification policy/command/MQTT delivery path."
    ),
    request_body=ExternalPushNotificationRequestSerializer,
    responses={
        202: ExternalPushNotificationResponseSerializer,
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, CanSendPushNotifications])
def create_external_push_notification(request):
    serializer = ExternalPushNotificationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    target = data["target"]

    try:
        result = create_push_notification(
            title=data["title"],
            body=data["body"],
            image_url=data.get("image_url"),
            tag=data.get("tag") or "",
            target_type=target["type"],
            target_id=str(target["id"]),
        )
    except PushNotificationServiceError as exc:
        return Response({"msg": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "status": "queued",
            "policy_id": str(result.policy.pk),
            "action_id": str(result.action.pk),
            "queued_devices": result.queued_devices,
            "command_ids": result.command_ids,
        },
        status=status.HTTP_202_ACCEPTED,
    )
