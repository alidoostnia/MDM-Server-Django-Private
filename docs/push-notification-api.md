# External Push Notification API

This API lets trusted external services queue push notifications for devices that are already managed by the MDM server.

The endpoint does not introduce a separate notification delivery mechanism. It reuses the existing server flow:

1. Create a `MakeNotification` action.
2. Create a one-time policy.
3. Attach the policy to the target device or department.
4. Create pending command records for target devices.
5. Queue the existing Celery task that publishes commands over MQTT.
6. Let the existing MQTT worker process device status and command state feedback.

## Endpoint

```http
POST /api/policies/push-notifications/
```

## Authentication

Use the existing JWT authentication.

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

The authenticated account must be staff or superuser. This keeps external notification sending restricted to trusted service accounts or administrators.

## Request Body

```json
{
  "title": "Server maintenance",
  "body": "Your device will restart at 22:00.",
  "image_url": "https://example.com/notice.png",
  "tag": "maintenance",
  "target": {
    "type": "device",
    "id": "2adff9e7-1a88-4f8d-bfd1-78a7aa8f1b10"
  }
}
```

For department targeting:

```json
{
  "title": "Department notice",
  "body": "Please sync your device.",
  "target": {
    "type": "department",
    "id": "08c87dde-7303-4ce7-98f8-b1be7b2a36e4"
  }
}
```

## Fields

| Field | Required | Description |
| --- | --- | --- |
| `title` | Yes | Notification title shown by the device client. |
| `body` | Yes | Notification body shown by the device client. |
| `image_url` | No | Optional image URL. Use `null` or omit it when no image is needed. |
| `tag` | No | Optional client-side grouping or replacement tag. |
| `target.type` | Yes | Must be `device` or `department`. |
| `target.id` | Yes | UUID of the target device or department. |

## Success Response

Status: `202 Accepted`

```json
{
  "status": "queued",
  "policy_id": "3a1248f4-a55c-45f2-bf09-dd22eb0d3fb4",
  "action_id": "2d99c053-df5a-4928-aa55-1fba884e7f65",
  "queued_devices": 1,
  "command_ids": [
    "8de7caa9-50f5-4a33-8ad8-b987929c4b99"
  ]
}
```

`queued_devices` is the number of device commands created. If a department has no devices, the response is still accepted with `queued_devices` set to `0`.

## Error Responses

Unauthenticated requests return `401 Unauthorized`.

Authenticated non-staff accounts return `403 Forbidden`.

Invalid payloads or unknown targets return `400 Bad Request`.

Example:

```json
{
  "target": {
    "id": [
      "Device not found."
    ]
  }
}
```

## Delivery Payload

The device still receives the existing policy command over MQTT on:

```text
policies/<device_id>
```

The notification data is carried inside the command's `actions` array:

```json
{
  "action_type": "MakeNotification",
  "inputs": {
    "title": "Server maintenance",
    "body": "Your device will restart at 22:00.",
    "image_url": "https://example.com/notice.png",
    "tag": "maintenance"
  }
}
```

Use `image_url` in API requests. The active server schema uses snake_case for this field.
