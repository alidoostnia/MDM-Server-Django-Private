from django.core.management.base import BaseCommand
from policies.models import Module, ModuleField, ActionType, Action, Policy
import json
from pathlib import Path
from django.db import IntegrityError
from django.utils.dateparse import parse_datetime

class Command(BaseCommand):
    help = 'Seed initial data for modules, module fields, action types, and actions'
    
    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding initial data...")
        
        # ---- Modules and Fields ----
        modules_with_fields = {
            "Advanced Diagnostics Logs": [],
            "Immediate Actions": [],
            "mdmagent": [],
            "Device Status & Heartbeat": [
                {"name": "battery_level", "description": ""},
                {"name": "is_charging", "description": ""},
                {"name": "uptime_ms", "description": ""},
                {"name": "screen_locked", "description": ""},
                {"name": "screen_on", "description": ""},
                {"name": "network_online", "description": ""},
                {"name": "heartbeat_timestamp", "description": ""},
            ],
            "Files": [
                {"name": "files", "description": ""},
                {"name": "suspicious_files", "description": ""},
                {"name": "media_counts", "description": ""},
                {"name": "scanned_count", "description": ""},
                {"name": "hashed_count", "description": ""},
                {"name": "scanning_done", "description": ""},
            ],
            "Geolocation": [
                {"name": "latitude", "description": ""},
                {"name": "longitude", "description": ""},
                {"name": "altitude", "description": ""},
                {"name": "accuracy", "description": ""},
                {"name": "speed", "description": ""},
                {"name": "bearing", "description": ""},
                {"name": "timestamp", "description": ""},
                {"name": "provider", "description": ""},
            ],
            "Hardware Info": [
                {"name": "cpuTempC", "description": ""},
                {"name": "model", "description": ""},
                {"name": "manufacturer", "description": ""},
                {"name": "serial", "description": ""},
                {"name": "imei", "description": ""},
                {"name": "androidId", "description": ""},
                {"name": "cpuArch", "description": ""},
                {"name": "ramTotal", "description": ""},
                {"name": "ramFree", "description": ""},
                {"name": "storageTotal", "description": ""},
                {"name": "storageFree", "description": ""},
                {"name": "screenWidth", "description": ""},
                {"name": "screenHeight", "description": ""},
                {"name": "density", "description": ""},
                {"name": "batteryCapacityPct", "description": ""},
                {"name": "batteryChargeCounter", "description": ""},
                {"name": "batteryHealth", "description": ""},
                {"name": "bluetooth", "description": ""},
                {"name": "wifi", "description": ""},
                {"name": "accel", "description": ""},
                {"name": "gyro", "description": ""},
            ],
            "Network & Connectivity": [
                {"name": "wifi_ssid", "description": ""},
                {"name": "wifi_bssid", "description": ""},
                {"name": "wifi_mac", "description": ""},
                {"name": "wifi_ip", "description": ""},
                {"name": "wifi_connected", "description": ""},
                {"name": "carrier_name", "description": ""},
                {"name": "network_type", "description": ""},
                {"name": "roaming", "description": ""},
                {"name": "signal_strength", "description": ""},
                {"name": "vpn_profiles", "description": ""},
                {"name": "bluetooth_on", "description": ""},
                {"name": "paired_bluetooth_devices", "description": ""},
                {"name": "tethering_on", "description": ""},
                {"name": "interfaces", "description": ""},
            ],
            "Security Status": [
                {"name": "screen_lock_present", "description": ""},
                {"name": "screen_lock_type", "description": ""},
                {"name": "screen_off_timeout_ms", "description": ""},
                {"name": "failed_attempts_threshold", "description": ""},
                {"name": "device_encryption_state", "description": ""},
                {"name": "external_storage_encrypted", "description": ""},
                {"name": "root_detected", "description": ""},
                {"name": "root_evidence", "description": ""},
                {"name": "selinux_mode", "description": ""},
                {"name": "play_services_installed", "description": ""},
                {"name": "play_protect_scan_status", "description": ""},
                {"name": "adb_enabled", "description": ""},
                {"name": "developer_options_enabled", "description": ""},
                {"name": "trusted_ca_count_sample", "description": ""},
                {"name": "trusted_ca_sample", "description": ""},
            ],
            "Software Info": [
                {"name": "installed_apps", "description": ""},
                {"name": "running_processes", "description": ""},
                {"name": "default_apps", "description": ""},
                {"name": "permissions_status", "description": ""},
                {"name": "banned_apps_installed", "description": ""},
            ],
            "System Configuration": [
                {"name": "android_version", "description": ""},
                {"name": "sdk_int", "description": ""},
                {"name": "build_number", "description": ""},
                {"name": "security_patch", "description": ""},
                {"name": "time_zone", "description": ""},
                {"name": "date_format_24h", "description": ""},
                {"name": "auto_time", "description": ""},
                {"name": "auto_time_zone", "description": ""},
                {"name": "language", "description": ""},
                {"name": "country", "description": ""},
                {"name": "accessibility_enabled", "description": ""},
                {"name": "touch_exploration_enabled", "description": ""},
                {"name": "font_scale", "description": ""},
                {"name": "device_owner", "description": ""},
            ],
            "User & Account Info": [
                {"name": "accounts", "description": ""},
                {"name": "has_work_profile", "description": ""},
                {"name": "device_owner_name", "description": ""},
                {"name": "local_users", "description": ""},
            ],
        }

                
        for module_name, fields in modules_with_fields.items():
            module, _created = Module.objects.update_or_create(
                name=module_name,
                defaults={"description": ""}
            )
            
            if _created:
                self.stdout.write(f"Created Module: {module_name}")
            
            for entry in fields:
                # support both string and dict entry styles
                if isinstance(entry, str):
                    field_name = entry
                    field_desc = ""
                elif isinstance(entry, dict):
                    field_name = entry.get("name")
                    field_desc = entry.get("description", "")
                else:
                    continue
                
                try:
                    field_obj, field_created = ModuleField.objects.update_or_create(
                        module=module,
                        name=field_name,
                        defaults={"description": field_desc}
                    )
                except IntegrityError:
                    self.stdout.write(f"Skipping field {field_name}: a ModuleField with that name already exists (global unique).")
                    continue

                
                if field_created:
                    self.stdout.write(f"  Created Field: {field_name} for Module: {module_name}")
        
        # ---- Action Types ----
        # Schema helper factories
        def bool_schema():
            return {"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"], "additionalProperties": False}
        
        def simple_string_schema(prop_name="value", required=False):
            schema = {"type": "object", "properties": {prop_name: {"type": "string"}}}
            if required:
                schema["required"] = [prop_name]
            schema["additionalProperties"] = False
            return schema
        
        def simple_int_schema(prop_name="length", minimum=0, required=False):
            schema = {"type": "object", "properties": {prop_name: {"type": "integer", "minimum": minimum}}}
            if required:
                schema["required"] = [prop_name]
            schema["additionalProperties"] = False
            return schema
        
        def enum_string_schema(prop_name, values, required=True):
            schema = {
                "type": "object",
                "properties": {prop_name: {"type": "string", "enum": values}},
                "additionalProperties": False,
            }
            if required:
                schema["required"] = [prop_name]
            return schema

        def example_for_bool(enabled=True, prop_name="enabled"):
            return {prop_name: enabled}

        def example_for_string(prop_name, value="example"):
            return {prop_name: value}

        def example_for_int(prop_name, value=1):
            return {prop_name: value}

        action_schemas = {
            "Ping": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "ScreenLock": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "Wipe": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "GeoLocate": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "Inventory": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "FullLock": ({"type": "object", "properties": {}, "additionalProperties": False}, {}),
            "AudioProfile": (
                enum_string_schema("type", ["NORMAL", "VIBRATE", "SILENT"]),
                example_for_string("type", "NORMAL"),
            ),
            "CreateVPNProfiles": (bool_schema(), example_for_bool(False)),
            "ActionTypeEnabled": (bool_schema(), example_for_bool(True)),
            "ResetActionType": (
                enum_string_schema("action_type", ["WIFI_ENFORCE"]),
                example_for_string("action_type", "WIFI_ENFORCE"),
            ),
            "InternalStorageActionType": (bool_schema(), example_for_bool(True)),
            "UseTLS": (bool_schema(), example_for_bool(True)),
            "DeployApplication": (bool_schema(), example_for_bool(True)),
            "ActionTypeQuality": (
                enum_string_schema("kind", ["COMPLEX"]),
                example_for_string("kind", "COMPLEX"),
            ),
            "MinimumActionTypeLength": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 8)),
            "MinimumUppercaseLetters": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 1)),
            "MinimumLowercaseLetters": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 1)),
            "MinimumNumericalDigits": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 1)),
            "MinimumNonLetterCharacters": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 1)),
            "MinimumSymbols": (simple_int_schema("length", minimum=0, required=True), example_for_int("length", 1)),
            "MaximumTimeToLock": (simple_int_schema("timeInSec", minimum=0, required=True), example_for_int("timeInSec", 60)),
            "MaximumFailedAttemptsForWipe": (simple_int_schema("num", minimum=0, required=True), example_for_int("num", 10)),
            "WifiPolicy": (
                enum_string_schema("mode", ["ALLOW_BOTH", "DISALLOW_BOTH"]),
                example_for_string("mode", "ALLOW_BOTH"),
            ),
            "WifiState": (bool_schema(), example_for_bool(True)),
            "WifiEnforce": (
                enum_string_schema("mode", ["NONE", "KEEP_ON", "KEEP_OFF"]),
                example_for_string("mode", "NONE"),
            ),
            "BluetoothPolicy": (
                {
                    "type": "object",
                    "properties": {"allowed": {"type": "boolean"}},
                    "required": ["allowed"],
                    "additionalProperties": False,
                },
                {"allowed": True},
            ),
            "BluetoothState": (bool_schema(), example_for_bool(True)),
            "BluetoothEnforce": (
                enum_string_schema("mode", ["NONE", "KEEP_ON", "KEEP_OFF"]),
                example_for_string("mode", "NONE"),
            ),
            "GpsPolicy": (
                enum_string_schema("mode", ["ALLOW_USER_TOGGLE", "DISALLOW_USER_TOGGLE"]),
                example_for_string("mode", "ALLOW_USER_TOGGLE"),
            ),
            "GpsState": (bool_schema(), example_for_bool(True)),
            "GpsEnforce": (
                enum_string_schema("mode", ["NONE", "KEEP_ON", "KEEP_OFF"]),
                example_for_string("mode", "NONE"),
            ),
            "CameraPolicy": (
                {
                    "type": "object",
                    "properties": {"allowed": {"type": "boolean"}},
                    "required": ["allowed"],
                    "additionalProperties": False,
                },
                {"allowed": True},
            ),
            "CameraAppAccess": (
                {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["BLOCK", "UNBLOCK"]},
                        "packages": {"type": "string"},
                    },
                    "required": ["mode", "packages"],
                    "additionalProperties": False,
                },
                {"mode": "BLOCK", "packages": "com.android.camera,com.google.android.GoogleCamera"},
            ),
            "ScreenCapturePolicy": (
                {
                    "type": "object",
                    "properties": {"allowed": {"type": "boolean"}},
                    "required": ["allowed"],
                    "additionalProperties": False,
                },
                {"allowed": True},
            ),
            "StatusBarPolicy": (
                {
                    "type": "object",
                    "properties": {"allowExpand": {"type": "boolean"}},
                    "required": ["allowExpand"],
                    "additionalProperties": False,
                },
                {"allowExpand": True},
            ),
            "AirplaneState": (bool_schema(), example_for_bool(True)),
            "HotspotState": (bool_schema(), example_for_bool(True)),
            "CellularDataState": (bool_schema(), example_for_bool(True)),
            "RoamingState": (bool_schema(), example_for_bool(True)),
            "NfcState": (bool_schema(), example_for_bool(True)),
            "UsbAdbState": (bool_schema(), example_for_bool(True)),
            "UsbConfigState": (
                enum_string_schema("config", ["mtp,adb", "mtp", "none"]),
                example_for_string("config", "mtp,adb"),
            ),
            "InstallPolicy": (
                enum_string_schema("mode", ["LOCK_UNKNOWN_SOURCES", "UNLOCK_UNKNOWN_SOURCES", "LOCK_INSTALL_APPS", "UNLOCK_INSTALL_APPS"]),
                example_for_string("mode", "LOCK_UNKNOWN_SOURCES"),
            ),
            "WebAccessPolicy": (
                {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["BLOCK_APPS", "UNBLOCK_APPS"]},
                        "packages": {"type": "string"},
                    },
                    "required": ["mode", "packages"],
                    "additionalProperties": False,
                },
                {"mode": "BLOCK_APPS", "packages": "com.android.chrome,org.mozilla.firefox"},
            ),
            "CallSmsPolicy": (
                enum_string_schema("mode", ["LOCK_CALLS", "UNLOCK_CALLS", "LOCK_SMS", "UNLOCK_SMS", "LOCK_CALLS_AND_SMS", "UNLOCK_CALLS_AND_SMS"]),
                example_for_string("mode", "LOCK_CALLS"),
            ),
            "SmsMmsPolicy": (
                {
                    "type": "object",
                    "properties": {"allowed": {"type": "boolean"}},
                    "required": ["allowed"],
                    "additionalProperties": False,
                },
                {"allowed": True},
            ),
            "SpeakerphoneState": (bool_schema(), example_for_bool(True)),
            "InstallApk": (simple_string_schema("url", required=True), example_for_string("url", "https://example.com/app.apk")),
            "RemoveApk": (simple_string_schema("package_id", required=True), example_for_string("package_id", "com.example.app")),
            "DeployFile": (
                {"type": "object", "properties": {"url": {"type": "string"}, "path": {"type": "string"}},
                 "required": ["url", "path"], "additionalProperties": False},
                {"url": "https://example.com/file.bin", "path": "/sdcard/Download/file.bin"}
            ),
            "RemoveFile": (
                {"type": "object", "properties": {"from": {"type": "string"}}, "required": ["from"], "additionalProperties": False},
                {"from": "/sdcard/Download/some_folder_or_file"}
            ),
            "CopyFile": (
                {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}}, "required": ["from", "to"], "additionalProperties": False},
                {"from": "/sdcard/Download/file.bin", "to": "/sdcard/Documents/file.bin"}
            ),
            "CutFile": (
                {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}}, "required": ["from", "to"], "additionalProperties": False},
                {"from": "/sdcard/Download/file.bin", "to": "/sdcard/Documents/file.bin"}
            ),
            "DeleteFile": (
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
                {"path": "/sdcard/Download/file.bin"}
            ),
            "MakeNotification": (
                {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "image_url": {"type": ["string", "null"]},
                        "tag": {"type": "string"}
                    },
                    "required": ["title", "body"],
                    "additionalProperties": False
                },
                {"title": "Hello", "body": "World", "image_url": "https://example.com/image.png", "tag": "demo-tag"}
            )
        }
        
        action_type_entries = [
            {"name": "Ping", "description": ""},
            {"name": "ScreenLock", "description": ""},
            {"name": "Wipe", "description": ""},
            {"name": "GeoLocate", "description": ""},
            {"name": "Inventory", "description": ""},
            {"name": "FullLock", "description": ""},
            {"name": "AudioProfile", "description": ""},
            {"name": "CreateVPNProfiles", "description": ""},
            {"name": "ActionTypeEnabled", "description": ""},
            {"name": "ResetActionType", "description": ""},
            {"name": "InternalStorageActionType", "description": ""},
            {"name": "UseTLS", "description": ""},
            {"name": "DeployApplication", "description": ""},
            {"name": "ActionTypeQuality", "description": ""},
            {"name": "MinimumActionTypeLength", "description": ""},
            {"name": "MinimumUppercaseLetters", "description": ""},
            {"name": "MinimumLowercaseLetters", "description": ""},
            {"name": "MinimumNumericalDigits", "description": ""},
            {"name": "MinimumNonLetterCharacters", "description": ""},
            {"name": "MinimumSymbols", "description": ""},
            {"name": "MaximumTimeToLock", "description": ""},
            {"name": "MaximumFailedAttemptsForWipe", "description": ""},
            {"name": "WifiPolicy", "description": ""},
            {"name": "WifiState", "description": ""},
            {"name": "WifiEnforce", "description": ""},
            {"name": "BluetoothPolicy", "description": ""},
            {"name": "BluetoothState", "description": ""},
            {"name": "BluetoothEnforce", "description": ""},
            {"name": "GpsPolicy", "description": ""},
            {"name": "GpsState", "description": ""},
            {"name": "GpsEnforce", "description": ""},
            {"name": "CameraPolicy", "description": ""},
            {"name": "CameraAppAccess", "description": ""},
            {"name": "ScreenCapturePolicy", "description": ""},
            {"name": "StatusBarPolicy", "description": ""},
            {"name": "AirplaneState", "description": ""},
            {"name": "HotspotState", "description": ""},
            {"name": "CellularDataState", "description": ""},
            {"name": "RoamingState", "description": ""},
            {"name": "NfcState", "description": ""},
            {"name": "UsbAdbState", "description": ""},
            {"name": "UsbConfigState", "description": ""},
            {"name": "InstallPolicy", "description": ""},
            {"name": "WebAccessPolicy", "description": ""},
            {"name": "CallSmsPolicy", "description": ""},
            {"name": "SmsMmsPolicy", "description": ""},
            {"name": "SpeakerphoneState", "description": ""},
            {"name": "InstallApk", "description": ""},
            {"name": "RemoveApk", "description": ""},
            {"name": "DeployFile", "description": ""},
            {"name": "RemoveFile", "description": ""},
            {"name": "CopyFile", "description": ""},
            {"name": "CutFile", "description": ""},
            {"name": "DeleteFile", "description": ""},
            {"name": "MakeNotification", "description": ""},
        ]
        
        expected_action_type_names = {entry["name"] for entry in action_type_entries}
        stale_action_types = ActionType.objects.exclude(name__in=expected_action_type_names)
        stale_count = stale_action_types.count()
        if stale_count:
            stale_action_types.delete()
            self.stdout.write(f"Removed stale ActionTypes: {stale_count}")

        for entry in action_type_entries:
            name = entry["name"]
            desc = entry.get("description", "")
            schema, example = action_schemas.get(
                name,
                ({"type": "object", "properties": {}, "additionalProperties": False}, {})
            )
            
            obj, created = ActionType.objects.update_or_create(
                name=name,
                defaults={
                    "description": desc,
                    "input_schema": schema,
                    "example_input": example
                }
            )
            if created:
                self.stdout.write(f"Created ActionType: {name}")
            
        # ---- Main (non-deletable) actions ----
        actions_file = Path(__file__).with_name("actions.json")
        with actions_file.open("r", encoding="utf-8") as file:
            main_actions = json.load(file)

        for action_entry in main_actions:
            action_type_obj = ActionType.objects.get(name=action_entry["action_type"])
            obj, created = Action.objects.update_or_create(
                action_id=action_entry["action_id"],
                defaults={
                    "name": action_entry["name"],
                    "description": action_entry["description"],
                    "input": action_entry["input"],
                    "action_type": action_type_obj,
                    "trigger_kind_id": Action.TriggerKind.ONE_TIME,
                    "regex": None,
                    "interval_time": None,
                    "exact_time": None,
                    "is_main_action": True,
                    "is_deletable": False,
                },
            )
            if created:
                self.stdout.write(f"Created main Action: {obj.name}")

        # ---- Policies ----
        policy_entries = [
            {
                "policy_id": "c7db89ec-2f68-4fe5-b0e9-14760fea4abd",
                "name": "Allow messaging and calling",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Allow messaging and calling"],
            },
            {
                "policy_id": "62174e37-79c7-4cd3-b53e-ff0d6a468732",
                "name": "Keep Bluetooth On",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Keep Bluetooth On"],
            },
            {
                "policy_id": "eedf5952-5ced-43b7-b77f-004986df8fb7",
                "name": "Allow turning Bluetooth on/off",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Allow turning Bluetooth on/off"],
            },
            {
                "policy_id": "5c2a591d-8146-4127-aba5-aa3a32596bbc",
                "name": "Allow installing apps",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Allow installing apps"],
            },
            {
                "policy_id": "c4517123-5f27-4fbc-b573-70b34801cce0",
                "name": "Disallow turning Bluetooth on",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Disallow turning Bluetooth on"],
            },
            {
                "policy_id": "e942187f-2847-46c2-8cdb-adc160b7f095",
                "name": "Turn on the Bluetooth",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Turn on the Bluetooth"],
            },
            {
                "policy_id": "3354b2ba-96b1-4503-acd4-95b1eb8644f3",
                "name": "Disallow installing apps",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Disallow installing apps"],
            },
            {
                "policy_id": "58718db0-a856-437e-a5d9-2bcab2540794",
                "name": "Allow using camera",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Allow using camera"],
            },
            {
                "policy_id": "6195d42f-31a4-41a2-875c-6c05a27e6c40",
                "name": "Disable Keep Bluetooth on",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Disable Keep Bluetooth on"],
            },
            {
                "policy_id": "4dda3055-56c0-4f97-bcec-09187e38277c",
                "name": "Turn off the Bluetooth",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Turn off the Bluetooth"],
            },
            {
                "policy_id": "e70ad319-5143-4fad-bd3a-814c2e9b7eb6",
                "name": "Disallow messaging and calling",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Disallow messaging and calling"],
            },
            {
                "policy_id": "8ba3dd4c-3528-4dc9-a911-bbed5417c3c0",
                "name": "Disallow using camera",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Disallow using camera"],
            },
            {
                "policy_id": "c9d419db-b1ab-4808-a78f-9b101fc2a1d1",
                "name": "Turn wifi off",
                "module_field_name": "cpuArch",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": ["Turn wifi off"],
            },
            {
                "policy_id": "195f804f-2ff3-4c1a-96b5-27f91579ef10",
                "name": "do not use me",
                "module_field_name": "cpuTempC",
                "trigger_kind_id": Policy.TriggerKind.ONE_TIME,
                "action_names": [],
            },
            {
                "policy_id": "f0e7a81e-777d-4ab0-ba43-4bab6ac4b718",
                "name": "get ram free",
                "module_field_name": "ramFree",
                "trigger_kind_id": Policy.TriggerKind.ALWAYS,
                "action_names": [],
            },
        ]

        for policy_entry in policy_entries:
            module_field = ModuleField.objects.get(name=policy_entry["module_field_name"])
            policy_obj, _ = Policy.objects.update_or_create(
                policy_id=policy_entry["policy_id"],
                defaults={
                    "name": policy_entry["name"],
                    "module_field": module_field,
                    "trigger_kind_id": policy_entry["trigger_kind_id"],
                    "regex": None,
                    "interval_time": None,
                    "exact_time": None,
                },
            )


            action_names = policy_entry.get("action_names", [])
            if action_names:
                actions = list(Action.objects.filter(name__in=action_names, is_main_action=True))
                policy_obj.actions.set(actions)
            else:
                policy_obj.actions.clear()

        self.stdout.write(self.style.SUCCESS("Seeding completed successfully."))