from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.hashers import check_password
from .models import Account
from .serializers import AccountLoginSerializer, AccountLogoutSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.settings import api_settings
from datetime import datetime, timezone
# for swagger documentation
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi


def timestamp_to_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

class AccountLoginAPIView(APIView):

    @swagger_auto_schema(
        request_body=AccountLoginSerializer,
        responses={
            200: openapi.Response(
                description="Successful login",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'device_id': openapi.Schema(
                            type=openapi.TYPE_STRING,
                            description='Device ID',
                            nullable=True
                        ),
                        'refresh': openapi.Schema(type=openapi.TYPE_STRING),
                        'access': openapi.Schema(type=openapi.TYPE_STRING),
                        'access_exp': openapi.Schema(type=openapi.TYPE_STRING),
                        'refresh_exp': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: "Bad Request",
            401: "Unauthorized"
        }
    )
    def post(self, request):
        serializer = AccountLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        imei = serializer.validated_data["imei"]

        # android_id is now optional & unused
        android_id = serializer.validated_data.get("android_id")

        try:
            account = Account.objects.select_related("device").get(username=username)
        except Account.DoesNotExist:
            return Response(
                {"error": "Invalid username or password"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not check_password(password, account.password):
            return Response(
                {"error": "Invalid username or password"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        device = getattr(account, "device", None)

        if device is None:
            if not (account.is_staff or account.is_superuser):
                return Response(
                    {
                        "code": "DEVICE_REQUIRED",
                        "error": "This account has no device attached",
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            device_id = None
        else:
            if device.imeis != imei:
                return Response(
                    {"code": "DEVICE_MISMATCH", "error": "Invalid IMEI"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            device_id = str(device.device_id)

        refresh = RefreshToken.for_user(account)
        access_token = refresh.access_token

        account.last_login = datetime.now(timezone.utc)
        account.save(update_fields=["last_login"])

        return Response({
            "device_id": device_id,
            "refresh": str(refresh),
            "access": str(access_token),
            "access_exp": timestamp_to_iso(access_token.payload.get("exp")),
            "refresh_exp": timestamp_to_iso(refresh.payload.get("exp")),
        })
    


class AccountTokenRefreshAPIView(APIView):  
    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='Refresh Token'),
            }
        ),
        responses={
            200: openapi.Response(
                description="New access and refresh tokens",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'access': openapi.Schema(type=openapi.TYPE_STRING, description='Access Token'),
                        'access_exp': openapi.Schema(type=openapi.TYPE_STRING, description='Access Token Expiration'),
                        'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='New Refresh Token'),
                        'refresh_exp': openapi.Schema(type=openapi.TYPE_STRING, description='Refresh Token Expiration'),
                    }
                )
            ),
            400: "Bad Request",
            401: "Unauthorized"
        }
    )
    
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            refresh = RefreshToken(refresh_token)
            refresh.blacklist()
            
            user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
            
            if not user_id:
                return Response({"error": "Invalid refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
            
            user = Account.objects.get(account_id=user_id)
            
            new_refresh = RefreshToken.for_user(user)
            access_token = new_refresh.access_token
            
            return Response({
                "access": str(access_token),
                "access_exp": timestamp_to_iso(access_token.payload.get("exp")),
                "refresh": str(new_refresh),
                "refresh_exp": timestamp_to_iso(new_refresh.payload.get("exp")),
            })
        except TokenError:
            return Response({"error": "Invalid or expired refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
        
        
        
        
class AccountLogoutAPIView(APIView):

    @swagger_auto_schema(
        request_body=AccountLogoutSerializer,
        responses={
            200: "Logged out successfully",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
        }
    )
    def post(self, request):
        serializer = AccountLogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        android_id = serializer.validated_data.get("android_id")
        imei = serializer.validated_data["imei"]

        try:
            account = Account.objects.select_related("device").get(username=username)
        except Account.DoesNotExist:
            return Response({"error": "Invalid username or password"}, status=status.HTTP_401_UNAUTHORIZED)

        if not check_password(password, account.password):
            return Response({"error": "Invalid username or password"}, status=status.HTTP_401_UNAUTHORIZED)

        device = getattr(account, "device", None)
        if device is None:
            if account.is_staff or account.is_superuser:
                return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)
            return Response(
                {
                    "code": "DEVICE_REQUIRED",
                    "error": "This account has no device attached",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if device.imeis != imei:
            return Response(
                {
                    "code": "DEVICE_MISMATCH",
                    "error": "Invalid device identifiers",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)