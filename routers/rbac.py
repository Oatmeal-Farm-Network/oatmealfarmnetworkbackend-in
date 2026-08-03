"""
routers/rbac.py
Audit logging + Role-Based Access Control.
- AuditLog: system-wide action history for a business
- BusinessRole: custom roles (Owner, Manager, Field Supervisor, Worker, View Only)
- BusinessRolePermission: feature-key flags per role
- BusinessUserRole: assigns a role to a team member (PeopleID)
"""
import json
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/rbac", tags=["rbac"])
_ready = False

DEFAULT_ROLES = [
    ("Owner",            "Full access to all features and settings"),
    ("Manager",          "Access to operations, reports, and team management"),
    ("Field Supervisor", "Manages work orders, field crews, and crop records"),
    ("Worker",           "Log work, view assigned tasks, greenhouse readings"),
    ("View Only",        "Read-only access to all data"),
]

AUDIT_ROUTER = APIRouter(prefix="/api/audit", tags=["audit"])


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='AuditLog')
        CREATE TABLE AuditLog (
            AuditLogID  INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            PeopleID    INT           NULL,
            EntityType  NVARCHAR(100) NOT NULL,
            EntityID    INT           NULL,
            Action      NVARCHAR(50)  NOT NULL,
            OldValues   NVARCHAR(MAX) NULL,
            NewValues   NVARCHAR(MAX) NULL,
            IpAddress   NVARCHAR(45)  NULL,
            UserAgent   NVARCHAR(500) NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessRole')
        CREATE TABLE BusinessRole (
            RoleID      INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            RoleName    NVARCHAR(100) NOT NULL,
            Description NVARCHAR(500) NULL,
            IsSystem    BIT           NOT NULL DEFAULT 0,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessRolePermission')
        CREATE TABLE BusinessRolePermission (
            PermID      INT IDENTITY PRIMARY KEY,
            RoleID      INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            FeatureKey  NVARCHAR(100) NOT NULL,
            CanView     BIT           NOT NULL DEFAULT 1,
            CanEdit     BIT           NOT NULL DEFAULT 0,
            CanDelete   BIT           NOT NULL DEFAULT 0,
            UpdatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessUserRole')
        CREATE TABLE BusinessUserRole (
            UserRoleID  INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            PeopleID    INT           NOT NULL,
            RoleID      INT           NOT NULL,
            AssignedBy  INT           NULL,
            AssignedAt  DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.commit()
    _ready = True


def record_audit(db: Session, business_id: int, people_id: Optional[int],
                 action: str, resource: str, resource_id: Optional[int] = None,
                 details: Optional[dict] = None, actor_name: Optional[str] = None):
    """Call this from any endpoint to append an audit record. Silently ignores errors."""
    try:
        _ensure(db)
        # The live AuditLog table uses EntityType/EntityID/NewValues (not
        # Resource/ResourceID/Details, and it has no ActorName column).
        db.execute(text("""
            INSERT INTO AuditLog (BusinessID, PeopleID, Action, EntityType, EntityID, NewValues)
            VALUES (:bid, :pid, :action, :res, :rid, :det)
        """), {
            "bid": business_id, "pid": people_id,
            "action": action, "res": resource, "rid": resource_id,
            "det": json.dumps(details) if details else None,
        })
    except Exception:
        pass


# ─── Audit Log endpoints ──────────────────────────────────────────────────────

@AUDIT_ROUTER.get("/logs")
def list_audit_logs(
    business_id: int = Query(...),
    resource: Optional[str] = None,
    action: Optional[str] = None,
    people_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    _ensure(db)
    # Alias the live columns to the names the UI expects (Resource/Details).
    q = ("SELECT AuditLogID, BusinessID, PeopleID, Action, "
         "EntityType AS Resource, EntityID AS ResourceID, NewValues AS Details, "
         "IpAddress AS IPAddress, CreatedAt "
         "FROM AuditLog WHERE BusinessID=:bid")
    params: dict = {"bid": business_id}
    if resource:
        q += " AND EntityType=:res"; params["res"] = resource
    if action:
        q += " AND Action=:act"; params["act"] = action
    if people_id:
        q += " AND PeopleID=:pid"; params["pid"] = people_id
    q += " ORDER BY CreatedAt DESC"
    q += f" OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY"
    rows = db.execute(text(q), params).fetchall()
    result = []
    for r in rows:
        row = dict(r._mapping)
        if row.get("Details"):
            try:
                row["Details"] = json.loads(row["Details"])
            except Exception:
                pass
        result.append(row)
    return result


@AUDIT_ROUTER.get("/summary")
def audit_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT EntityType AS Resource, Action, COUNT(*) AS Cnt
        FROM AuditLog
        WHERE BusinessID=:bid
          AND CreatedAt >= DATEADD(DAY, -30, GETDATE())
        GROUP BY EntityType, Action
        ORDER BY Cnt DESC
    """), {"bid": business_id}).fetchall()
    total = db.execute(text("SELECT COUNT(*) FROM AuditLog WHERE BusinessID=:bid"), {"bid": business_id}).scalar()
    return {
        "total_events": total,
        "last_30_days": [{"resource": r.Resource, "action": r.Action, "count": r.Cnt} for r in rows],
    }


# ─── Role management endpoints ───────────────────────────────────────────────

@router.get("/roles")
def list_roles(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT r.*,
               (SELECT COUNT(*) FROM BusinessUserRole ur WHERE ur.RoleID = r.RoleID) AS MemberCount
        FROM BusinessRole r
        WHERE r.BusinessID=:bid
        ORDER BY r.RoleID
    """), {"bid": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/roles/seed-defaults")
def seed_default_roles(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Idempotently create the 5 standard roles if none exist yet."""
    _ensure(db)
    existing = db.execute(text("SELECT COUNT(*) FROM BusinessRole WHERE BusinessID=:bid"),
                           {"bid": business_id}).scalar()
    if existing and existing > 0:
        return {"message": "Roles already seeded.", "count": existing}
    for name, desc in DEFAULT_ROLES:
        db.execute(text("""
            INSERT INTO BusinessRole (BusinessID, RoleName, Description, IsSystem)
            VALUES (:bid, :name, :desc, 1)
        """), {"bid": business_id, "name": name, "desc": desc})
    db.commit()
    return {"message": f"Created {len(DEFAULT_ROLES)} default roles.", "count": len(DEFAULT_ROLES)}


@router.post("/roles")
def create_role(body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO BusinessRole (BusinessID, RoleName, Description, IsSystem)
        OUTPUT INSERTED.RoleID
        VALUES (:bid, :name, :desc, 0)
    """), {"bid": body["business_id"], "name": body["RoleName"], "desc": body.get("Description")}).fetchone()
    db.commit()
    return {"RoleID": r[0]}


@router.put("/roles/{role_id}")
def update_role(role_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE BusinessRole SET RoleName=:name, Description=:desc
        WHERE RoleID=:rid AND BusinessID=:bid AND IsSystem=0
    """), {"name": body["RoleName"], "desc": body.get("Description"),
           "rid": role_id, "bid": body["business_id"]})
    db.commit()
    return {"ok": True}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    # Don't allow deleting system roles
    row = db.execute(text("SELECT IsSystem FROM BusinessRole WHERE RoleID=:rid AND BusinessID=:bid"),
                     {"rid": role_id, "bid": business_id}).fetchone()
    if not row:
        raise HTTPException(404, "Role not found")
    if row.IsSystem:
        raise HTTPException(400, "Cannot delete system roles")
    db.execute(text("DELETE FROM BusinessRolePermission WHERE RoleID=:rid AND BusinessID=:bid"),
               {"rid": role_id, "bid": business_id})
    db.execute(text("DELETE FROM BusinessUserRole WHERE RoleID=:rid AND BusinessID=:bid"),
               {"rid": role_id, "bid": business_id})
    db.execute(text("DELETE FROM BusinessRole WHERE RoleID=:rid AND BusinessID=:bid"),
               {"rid": role_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ─── Permissions per role ────────────────────────────────────────────────────

@router.get("/roles/{role_id}/permissions")
def get_role_permissions(role_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT * FROM BusinessRolePermission WHERE RoleID=:rid AND BusinessID=:bid
    """), {"rid": role_id, "bid": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.put("/roles/{role_id}/permissions")
def set_role_permissions(role_id: int, body: dict, db: Session = Depends(get_db)):
    """Upsert permissions for a role. body.permissions = [{feature_key, can_view, can_edit, can_delete}]"""
    _ensure(db)
    bid = body["business_id"]
    for perm in body.get("permissions", []):
        fk = perm["feature_key"]
        exists = db.execute(text("""
            SELECT PermID FROM BusinessRolePermission
            WHERE RoleID=:rid AND BusinessID=:bid AND FeatureKey=:fk
        """), {"rid": role_id, "bid": bid, "fk": fk}).fetchone()
        if exists:
            db.execute(text("""
                UPDATE BusinessRolePermission
                SET CanView=:cv, CanEdit=:ce, CanDelete=:cd, UpdatedAt=GETDATE()
                WHERE PermID=:pid
            """), {"cv": perm.get("can_view", True), "ce": perm.get("can_edit", False),
                   "cd": perm.get("can_delete", False), "pid": exists.PermID})
        else:
            db.execute(text("""
                INSERT INTO BusinessRolePermission (RoleID, BusinessID, FeatureKey, CanView, CanEdit, CanDelete)
                VALUES (:rid, :bid, :fk, :cv, :ce, :cd)
            """), {"rid": role_id, "bid": bid, "fk": fk,
                   "cv": perm.get("can_view", True), "ce": perm.get("can_edit", False),
                   "cd": perm.get("can_delete", False)})
    db.commit()
    return {"ok": True}


# ─── User role assignments ───────────────────────────────────────────────────

@router.get("/members")
def list_members(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT ur.UserRoleID, ur.PeopleID, ur.RoleID, ur.AssignedAt,
               r.RoleName, r.Description,
               LTRIM(RTRIM(ISNULL(p.PeopleFirstName,'') + ' ' + ISNULL(p.PeopleLastName,''))) AS MemberName,
               p.Peopleemail AS Email
        FROM BusinessUserRole ur
        JOIN BusinessRole r ON r.RoleID = ur.RoleID
        LEFT JOIN People p ON p.PeopleID = ur.PeopleID
        WHERE ur.BusinessID=:bid
        ORDER BY r.RoleName, p.PeopleLastName
    """), {"bid": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/members")
def assign_member(body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    # Remove existing role for this person+business before assigning new one
    db.execute(text("""
        DELETE FROM BusinessUserRole WHERE BusinessID=:bid AND PeopleID=:pid
    """), {"bid": body["business_id"], "pid": body["PeopleID"]})
    r = db.execute(text("""
        INSERT INTO BusinessUserRole (BusinessID, PeopleID, RoleID, AssignedBy)
        OUTPUT INSERTED.UserRoleID
        VALUES (:bid, :pid, :rid, :by)
    """), {"bid": body["business_id"], "pid": body["PeopleID"],
           "rid": body["RoleID"], "by": body.get("AssignedBy")}).fetchone()
    db.commit()
    return {"UserRoleID": r[0]}


@router.delete("/members/{user_role_id}")
def remove_member(user_role_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BusinessUserRole WHERE UserRoleID=:id AND BusinessID=:bid"),
               {"id": user_role_id, "bid": business_id})
    db.commit()
    return {"ok": True}


@router.get("/people-search")
def people_search(business_id: int = Query(...), q: str = Query(""), db: Session = Depends(get_db)):
    """Search People by name or email for member assignment. Returns up to 20 matches."""
    if len(q) < 2:
        return []
    rows = db.execute(text("""
        SELECT TOP 20 p.PeopleID,
               LTRIM(RTRIM(ISNULL(p.PeopleFirstName,'') + ' ' + ISNULL(p.PeopleLastName,''))) AS FullName,
               p.Peopleemail AS Email
        FROM People p
        WHERE (ISNULL(p.PeopleFirstName,'') + ' ' + ISNULL(p.PeopleLastName,'') LIKE :q
               OR p.Peopleemail LIKE :q)
        ORDER BY p.PeopleFirstName, p.PeopleLastName
    """), {"q": f"%{q}%"}).fetchall()
    return [{"people_id": r.PeopleID, "full_name": r.FullName, "email": r.Email} for r in rows]


@router.get("/my-permissions")
def get_my_permissions(business_id: int = Query(...), people_id: int = Query(...), db: Session = Depends(get_db)):
    """Return the effective permission set for a specific team member."""
    _ensure(db)
    user_role = db.execute(text("""
        SELECT ur.RoleID, r.RoleName
        FROM BusinessUserRole ur
        JOIN BusinessRole r ON r.RoleID = ur.RoleID
        WHERE ur.BusinessID=:bid AND ur.PeopleID=:pid
    """), {"bid": business_id, "pid": people_id}).fetchone()
    if not user_role:
        return {"role": None, "permissions": {}}
    perms = db.execute(text("""
        SELECT FeatureKey, CanView, CanEdit, CanDelete
        FROM BusinessRolePermission
        WHERE RoleID=:rid AND BusinessID=:bid
    """), {"rid": user_role.RoleID, "bid": business_id}).fetchall()
    return {
        "role": {"role_id": user_role.RoleID, "role_name": user_role.RoleName},
        "permissions": {r.FeatureKey: {"can_view": bool(r.CanView), "can_edit": bool(r.CanEdit), "can_delete": bool(r.CanDelete)} for r in perms},
    }
