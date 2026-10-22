"""A-01: declarative HTTP interface, without business-operation implementations."""

import inspect
import re
from dataclasses import dataclass

from fastapi import Depends, FastAPI, File, Query, Request, Response, Security, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie

from app import schemas as s


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    result: object
    access: str
    body: object = None
    status: int = 200
    paginate: bool = False
    upload: bool = False


OPERATIONS = [
    Operation(
        "POST", "/auth/register", s.UserOut, "public; registration always creates user", s.Credentials, 201
    ),
    Operation("POST", "/auth/login", s.MeOut, "public; validate credentials", s.LoginCredentials),
    Operation("POST", "/auth/logout", None, "authenticated; invalidate own session", status=204),
    Operation("GET", "/me", s.MeOut, "authenticated; own account and memberships"),
    Operation(
        "POST",
        "/memberships/requests",
        s.MembershipOut,
        "authenticated; own pending request",
        s.MembershipIn,
        201,
    ),
    Operation(
        "PATCH",
        "/memberships/{membership_id}/profile",
        s.MembershipOut,
        "authenticated; own membership only; position does not grant permissions",
        s.ProfileIn,
    ),
    Operation("GET", "/companies", list[s.CompanyOut], "authenticated; active memberships only"),
    Operation(
        "GET",
        "/companies/{company_id}/context",
        s.CompanyContextV2 | s.CompanyContext,
        "active membership in company",
    ),
    Operation(
        "GET",
        "/companies/{company_id}/feed",
        s.FeedOut | s.FeedSnapshotOut,
        "active membership in company; v2 snapshot belongs to this user and company",
        paginate=True,
    ),
    Operation(
        "POST",
        "/companies/{company_id}/insights",
        s.InsightOut,
        "active membership in company; visible event; own result",
        s.EventIn,
    ),
    Operation("GET", "/insights/{insight_id}", s.InsightOut, "own insight; active company membership"),
    Operation("POST", "/chats", s.ChatOut, "active company membership; own chat", s.ChatIn, 201),
    Operation(
        "POST",
        "/chats/{chat_id}/messages",
        s.JobOut,
        "own chat; active company membership; one pending question per chat",
        s.MessageIn,
        202,
    ),
    Operation(
        "GET",
        "/chats/{chat_id}/messages",
        list[s.MessageOut],
        "own chat; active company membership",
        paginate=True,
    ),
    Operation(
        "GET",
        "/jobs/{job_id}",
        s.JobOut,
        "job owner or admin; company-scoped jobs also require active membership",
    ),
    Operation(
        "GET",
        "/sources/{source_id}",
        s.EvidenceOut,
        "authenticated; company evidence requires active membership; news must be visible",
    ),
    Operation(
        "GET",
        "/sources/{source_id}/file",
        None,
        "authenticated; bank PDF only; verify source authorization before file access",
    ),
    Operation("POST", "/feedback", s.FeedbackOut, "own insight; active company membership", s.FeedbackIn),
    Operation("GET", "/admin/users", list[s.UserOut], "admin", paginate=True),
    Operation(
        "PATCH",
        "/admin/users/{user_id}",
        s.UserOut,
        "admin; audit role/status changes; prevent self-lockout",
        s.UserPatch,
    ),
    Operation("GET", "/admin/memberships", list[s.MembershipOut], "admin", paginate=True),
    Operation(
        "PATCH",
        "/admin/memberships/{membership_id}",
        s.MembershipOut,
        "admin; audit approval/rejection",
        s.MembershipPatch,
    ),
    Operation("GET", "/admin/documents", list[s.DocumentOut], "admin", paginate=True),
    Operation(
        "POST",
        "/admin/documents",
        s.UploadOut,
        "admin; PDF only; maximum 50 MiB; audit",
        status=202,
        upload=True,
    ),
    Operation("POST", "/admin/documents/{document_id}/reindex", s.JobOut, "admin; audit", status=202),
    Operation("GET", "/admin/news", list[s.AdminEventOut], "admin", paginate=True),
    Operation("PATCH", "/admin/news/{event_id}", s.VisibilityOut, "admin; audit", s.VisibilityIn),
    Operation("POST", "/admin/news/{event_id}/retry", s.JobOut, "admin; audit", status=202),
    Operation("GET", "/admin/jobs", list[s.JobOut], "admin", paginate=True),
    Operation("POST", "/admin/jobs/collect-news", s.JobOut, "admin; audit", status=202),
    Operation("GET", "/admin/stats", s.StatsOut, "admin"),
]

cookie = APIKeyCookie(name="goat_session", auto_error=False)


def install_contracts(app: FastAPI, access_dependency=None):
    implemented = {
        (method, route.path): route for route in app.routes for method in getattr(route, "methods", [])
    }
    for operation in OPERATIONS:
        existing = implemented.get((operation.method, operation.path))
        if existing is not None:
            existing.openapi_extra = {
                **(existing.openapi_extra or {}),
                "x-access": {
                    "rule": operation.access,
                    "csrf_required": not operation.access.startswith("public;")
                    and operation.method in {"POST", "PATCH"},
                },
                "x-implementation-status": "implemented",
            }
            existing.operation_id = (
                operation.method.lower() + "_" + re.sub(r"[^\w]+", "_", operation.path).strip("_")
            )
            continue

        async def contract_only(**kwargs):
            return JSONResponse(
                status_code=501,
                content={
                    "code": "not_implemented",
                    "message": "A-01 publishes this operation's contract only",
                    "request_id": kwargs["request"].state.request_id,
                    "field_errors": [],
                },
            )

        params = [inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY, annotation=Request)]
        params += [
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str)
            for name in re.findall(r"\{(\w+)\}", operation.path)
        ]
        if operation.body:
            params.append(
                inspect.Parameter("body", inspect.Parameter.KEYWORD_ONLY, annotation=operation.body)
            )
        if operation.upload:
            params.append(
                inspect.Parameter(
                    "file", inspect.Parameter.KEYWORD_ONLY, annotation=UploadFile, default=File(...)
                )
            )
        if operation.paginate:
            for name, default, lower in [("limit", 20, 1), ("offset", 0, 0)]:
                params.append(
                    inspect.Parameter(
                        name,
                        inspect.Parameter.KEYWORD_ONLY,
                        annotation=int,
                        default=Query(default, ge=lower, le=100 if name == "limit" else None),
                    )
                )
        public = operation.access.startswith("public;")
        if not public:
            params.append(
                inspect.Parameter(
                    "session",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=object,
                    default=Depends(access_dependency) if access_dependency else Security(cookie),
                )
            )
        contract_only.__signature__ = inspect.Signature(params)
        operation_id = operation.method.lower() + "_" + re.sub(r"[^\w]+", "_", operation.path).strip("_")
        responses = {
            501: {"model": s.ErrorOut, "description": "Contract only; implementation follows in A-02+"}
        }
        if operation.path == "/companies/{company_id}/insights":
            responses[202] = {"model": s.JobOut, "description": "Analysis queued"}
        if operation.path.endswith("/file"):
            responses[200] = {
                "description": "Authorized original PDF",
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            }
        app.add_api_route(
            operation.path,
            contract_only,
            methods=[operation.method],
            status_code=operation.status,
            response_model=operation.result,
            operation_id=operation_id,
            responses=responses,
            response_class=Response if operation.path.endswith("/file") else JSONResponse,
            tags=["admin" if operation.path.startswith("/admin/") else "application"],
            openapi_extra={
                "x-access": {
                    "rule": operation.access,
                    "csrf_required": not public and operation.method in {"POST", "PATCH"},
                },
                "x-implementation-status": "contract-only",
            },
        )
