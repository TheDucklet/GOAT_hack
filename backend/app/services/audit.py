"""One audit writer shared by every administrative operation."""

from app.models import AuditLog


def audit(db, admin, action, object_id, details=None):
    db.add(AuditLog(admin_id=admin.id, action=action, object_id=object_id, details=details or {}))
