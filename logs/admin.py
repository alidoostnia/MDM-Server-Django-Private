import csv
import io
import json
import base64
import uuid
from datetime import datetime
from django.utils.timezone import localtime, make_aware, is_naive
from django.utils.dateparse import parse_datetime

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import path, reverse

from pymongo import MongoClient
from bson.json_util import dumps as bson_dumps
from bson.binary import Binary
from bson.objectid import ObjectId

from devices.models import Device
from policies.models import Policy

from django.template.response import TemplateResponse
from .models import FakeDeviceLogsModel

LOGS_PER_PAGE = getattr(settings, "LOGS_PER_PAGE", 50)
COLLECTION_NAME = getattr(settings, "LOGS_COLLECTION", "device_logs")
DEFAULT_LIVE_REFRESH_MS = getattr(settings, "DEVICE_LOGS_LIVE_REFRESH_MS", 5000)



def get_mongo_collection():
    """Return a pymongo collection instance with short timeout."""
    uri = getattr(settings, "MONGO_URI", None)
    if not uri:
        raise RuntimeError("MONGO_URI not set in settings.py")

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
    except Exception as e:
        raise RuntimeError(f"Cannot connect to MongoDB: {e}")

    # Extract DB name from URI if present; fallback to "mdm_logs"
    dbname = uri.rsplit("/", 1)[-1].split("?")[0] or "mdm_logs"
    db = client[dbname]
    return db[COLLECTION_NAME]


@admin.register(FakeDeviceLogsModel)
class DeviceLogsLinkAdmin(admin.ModelAdmin):
    """Fake model to show a link to MongoDB logs in the admin home."""

    def changelist_view(self, request, extra_context=None):
        # redirect to your custom view instead of any model page
        from django.shortcuts import redirect

        return redirect(reverse("admin:device_logs"))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DeviceLogsAdminView:
    def get_urls(self):
        urls = [
            path("device-logs/", admin.site.admin_view(self.device_logs_view), name="device_logs"),
            path("device-logs/live/", admin.site.admin_view(self.device_logs_live), name="device_logs_live"),
            path("device-logs/export/", admin.site.admin_view(self.device_logs_export), name="device_logs_export"),
            path("device-logs/<str:doc_id>/", admin.site.admin_view(self.device_logs_detail), name="device_logs_detail"),
        ]
        return urls

    def _build_time_query(self, start, end):
        """Return a (possibly empty) dict to query by notedOn (ISO strings)."""
        time_query = {}
        if not start and not end:
            return {}

        try:
            if start:
                start_dt = datetime.fromisoformat(start)
                time_query.setdefault("$gte", start_dt.isoformat())
        except Exception:
            pass

        try:
            if end:
                end_dt = datetime.fromisoformat(end)
                time_query.setdefault("$lte", end_dt.isoformat())
        except Exception:
            pass

        return time_query

    def _apply_text_search_fallback(self, mongo_query, q):
        """If $text fails, use case-insensitive regex fallback on known fields."""
        if "$text" in mongo_query:
            return mongo_query
        if q:
            mongo_query["$or"] = [
                {"logStash": {"$regex": q, "$options": "i"}},
                {"actionStash": {"$regex": q, "$options": "i"}},
                {"moduleName": {"$regex": q, "$options": "i"}},
            ]
        return mongo_query

    def _normalize_object_id(self, raw_id):
        if raw_id is None:
            return ""

        if isinstance(raw_id, uuid.UUID):
            return str(raw_id)

        if isinstance(raw_id, Binary):
            try:
                return str(uuid.UUID(bytes=bytes(raw_id)))
            except Exception:
                return str(raw_id).strip()

        if isinstance(raw_id, dict):
            if "$uuid" in raw_id:
                try:
                    return str(uuid.UUID(str(raw_id.get("$uuid", "")).strip()))
                except Exception:
                    pass

            if "$binary" in raw_id:
                binary_data = raw_id.get("$binary", {})
                base64_value = binary_data.get("base64") if isinstance(binary_data, dict) else ""
                if base64_value:
                    try:
                        decoded = base64.b64decode(base64_value)
                        if len(decoded) == 16:
                            return str(uuid.UUID(bytes=decoded))
                    except Exception:
                        pass

            if "$oid" in raw_id:
                return str(raw_id.get("$oid", "")).strip()

        normalized = str(raw_id).strip()

        try:
            return str(uuid.UUID(normalized))
        except Exception:
            compact = normalized.replace("-", "")
            try:
                return str(uuid.UUID(compact))
            except Exception:
                return normalized

    def _decorate_doc(self, raw_doc, device_map, policy_map):
        doc = json.loads(bson_dumps(raw_doc))

        if isinstance(raw_doc.get("_id"), ObjectId):
            id_str = str(raw_doc["_id"])
        else:
            id_data = doc.get("_id", {})
            id_str = id_data.get("$oid") if isinstance(id_data, dict) else str(id_data)
        doc["id_str"] = id_str

        if "notedOn" in doc:
            try:
                dt = parse_datetime(doc["notedOn"])
                if dt:
                    if is_naive(dt):
                        dt = make_aware(dt)
                    doc["pretty_time"] = localtime(dt).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    doc["pretty_time"] = ""
            except Exception:
                doc["pretty_time"] = ""

        elif "ts" in doc:
            try:
                dt = datetime.fromtimestamp(float(doc["ts"]))
                dt = make_aware(dt)
                doc["pretty_time"] = localtime(dt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                doc["pretty_time"] = ""

        else:
            doc["pretty_time"] = ""

        normalized_device_id = self._normalize_object_id(doc.get("deviceId"))
        normalized_policy_id = self._normalize_object_id(doc.get("policyId"))
        doc["deviceId"] = normalized_device_id
        doc["policyId"] = normalized_policy_id

        doc["device_name"] = device_map.get(normalized_device_id, "Unknown device") if normalized_device_id else "—"
        doc["policy_name"] = policy_map.get(normalized_policy_id, "Unknown policy") if normalized_policy_id else "—"
        return doc

    def _get_filters(self, request):
        return {
            "q": request.GET.get("q", "").strip(),
            "device_id": request.GET.get("device_id", "").strip(),
            "policy_id": request.GET.get("policy_id", "").strip(),
            "start": request.GET.get("start", "").strip(),
            "end": request.GET.get("end", "").strip(),
            "live": request.GET.get("live", "0") == "1",
            "refresh_ms": max(1000, int(request.GET.get("refresh_ms", DEFAULT_LIVE_REFRESH_MS))),
        }

    def _build_mongo_query(self, filters):
        mongo_query = {}

        if filters["device_id"]:
            mongo_query["deviceId"] = filters["device_id"]
        if filters["policy_id"]:
            mongo_query["policyId"] = filters["policy_id"]

        if filters["q"]:
            mongo_query["$text"] = {"$search": filters["q"]}

        noted_time_query = self._build_time_query(filters["start"], filters["end"])
        if noted_time_query:
            mongo_query["notedOn"] = noted_time_query

        return mongo_query

    def _device_policy_maps(self):
        device_map = {str(item["device_id"]): item["device_name"] for item in Device.objects.values("device_id", "device_name")}
        policy_map = {str(item["policy_id"]): item["name"] for item in Policy.objects.values("policy_id", "name")}
        return device_map, policy_map

    def _device_policy_options(self, coll, filters):
        base_query = self._build_mongo_query(filters)
        base_query.pop("deviceId", None)
        base_query.pop("policyId", None)
        base_query.pop("$text", None)

        device_ids = sorted(
            filter(
                None,
                {
                    self._normalize_object_id(v)
                    for v in coll.distinct("deviceId", filter=base_query)
                },
            )
        )
        policy_ids = sorted(
            filter(
                None,
                {
                    self._normalize_object_id(v)
                    for v in coll.distinct("policyId", filter=base_query)
                },
            )
        )

        device_map, policy_map = self._device_policy_maps()
        device_options = [{"id": dev_id, "name": device_map.get(dev_id, f"Unknown ({dev_id[:8]})")} for dev_id in device_ids]
        policy_options = [{"id": policy_id, "name": policy_map.get(policy_id, f"Unknown ({policy_id[:8]})")} for policy_id in policy_ids]
        return device_options, policy_options, device_map, policy_map

    def _fetch_docs(self, coll, mongo_query, page=1, limit=LOGS_PER_PAGE):
        try:
            total = coll.count_documents(mongo_query)
        except Exception:
            mongo_query.pop("$text", None)
            mongo_query = self._apply_text_search_fallback(mongo_query, "")
            total = coll.count_documents(mongo_query)

        skip = max(0, page - 1) * limit
        cursor = coll.find(mongo_query).sort("notedOn", -1).skip(skip).limit(limit)
        docs = list(cursor)
        return docs, total, mongo_query

    def device_logs_view(self, request):
        request.current_app = self.admin_site.name
        
        try:
            coll = get_mongo_collection()
        except Exception as exc:
            context = {
                "title": "Device Logs (MongoDB)",
                "error_message": str(exc),
            }
            return render(request, "admin/logs/device_logs_error.html", context, status=503)

        filters = self._get_filters(request)
        page = max(1, int(request.GET.get("page", "1")))
        mongo_query = self._build_mongo_query(filters)
        raw_docs, total, _ = self._fetch_docs(coll, mongo_query, page=page)
        device_options, policy_options, device_map, policy_map = self._device_policy_options(coll, filters)
        docs = [self._decorate_doc(raw_doc, device_map, policy_map) for raw_doc in raw_docs]

        from django.core.paginator import Paginator

        paginator = Paginator(range(total), LOGS_PER_PAGE)
        page_obj = paginator.get_page(page)

        params = request.GET.copy()
        if "page" in params:
            params.pop("page")
        base_qs = params.urlencode()

        context = dict(
            self.admin_site.each_context(request),
            title="Device Logs (MongoDB)",
            docs=docs,
            total=total,
            page_obj=page_obj,
            request=request,
            base_qs=base_qs,
            filters=filters,
            device_options=device_options,
            policy_options=policy_options,
            refresh_ms=filters["refresh_ms"],
        )
        return render(request, "admin/logs/device_logs.html", context)

    def device_logs_live(self, request):
        try:
            coll = get_mongo_collection()
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)

        filters = self._get_filters(request)
        mongo_query = self._build_mongo_query(filters)
        raw_docs, total, _ = self._fetch_docs(coll, mongo_query, page=1)
        _, _, device_map, policy_map = self._device_policy_options(coll, filters)
        docs = [self._decorate_doc(raw_doc, device_map, policy_map) for raw_doc in raw_docs]

        rows_html = render_to_string("admin/logs/includes/device_logs_rows.html", {"docs": docs})
        return JsonResponse({"ok": True, "rows_html": rows_html, "total": total, "updated_at": datetime.utcnow().isoformat()})

    def device_logs_detail(self, request, doc_id):
        """Show pretty JSON for a single document."""
        request.current_app = self.admin_site.name
        
        try:
            coll = get_mongo_collection()
        except Exception as exc:
            return HttpResponse(f"Mongo config error: {exc}", status=500)

        try:
            oid = ObjectId(doc_id)
            doc = coll.find_one({"_id": oid})
        except Exception:
            doc = coll.find_one({"_id": doc_id})

        if not doc:
            raise Http404("Document not found")

        pretty = json.loads(bson_dumps(doc))
        pretty_json = json.dumps(pretty, indent=2, ensure_ascii=False)
        
        context = dict(
            self.admin_site.each_context(request),
            doc=pretty,
            pretty_json=pretty_json    
        )
        
        return render(request, "admin/logs/device_log_detail.html", context)

    def _excel_response(self, docs):
        f = io.StringIO()
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["time", "device_id", "device_name", "policy_id", "policy_name", "module", "log", "action"])
        for d in docs:
            writer.writerow(
                [
                    d.get("pretty_time", ""),
                    d.get("deviceId", ""),
                    d.get("device_name", ""),
                    d.get("policyId", ""),
                    d.get("policy_name", ""),
                    d.get("moduleName", ""),
                    d.get("logStash", ""),
                    d.get("actionStash", ""),
                ]
            )

        response = HttpResponse(f.getvalue(), content_type="application/vnd.ms-excel; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="device_logs_export.xls"'
        return response

    def device_logs_export(self, request):
        """Export matching logs as JSON or Excel-compatible XLS."""
        try:
            coll = get_mongo_collection()
        except Exception as exc:
            return HttpResponse(f"Mongo config error: {exc}", status=500)

        filters = self._get_filters(request)
        export_format = request.GET.get("export", "json").strip().lower() or "json"
        mongo_query = self._build_mongo_query(filters)

        try:
            cursor = coll.find(mongo_query).sort("notedOn", -1)
        except Exception:
            mongo_query.pop("$text", None)
            mongo_query = self._apply_text_search_fallback(mongo_query, filters["q"])
            cursor = coll.find(mongo_query).sort("notedOn", -1)

        device_map, policy_map = self._device_policy_maps()
        docs = [self._decorate_doc(d, device_map, policy_map) for d in cursor]

        if export_format == "excel":
            return self._excel_response(docs)

        content = json.dumps(docs, indent=2, ensure_ascii=False)
        response = HttpResponse(content, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="device_logs_export.json"'
        return response


# register URLs into admin
view = DeviceLogsAdminView()
view.admin_site = admin.site
admin.site.get_urls = (lambda orig_get_urls: (lambda: view.get_urls() + orig_get_urls()))(admin.site.get_urls)