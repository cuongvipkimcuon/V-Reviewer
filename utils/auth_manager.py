# utils/auth_manager.py - Kiểm tra quyền theo project_members
from typing import List, Optional, Dict, Any
import json

# Owner: Read, Write, Delete, Approve
# Partner: Read, Request Write (gửi pending_changes), không Delete/Approve
# Viewer: Chỉ Read

ACTIONS = ("read", "write", "delete", "approve", "request_write")
ROLE_OWNER = "owner"
ROLE_PARTNER = "partner"
ROLE_VIEWER = "viewer"


def _get_services():
    try:
        from config import init_services
        return init_services()
    except Exception:
        return None


def get_user_role(user_id: str, user_email: str, story_id: str) -> Optional[str]:
    """
    Trả về role của user với project: 'owner' | 'partner' | 'viewer' | None (không có quyền).
    Owner nếu stories.user_id = user_id; ngược lại tra project_members theo user_email.
    """
    services = _get_services()
    if not services:
        return None
    supabase = services["supabase"]
    try:
        story = supabase.table("stories").select("user_id").eq("id", story_id).execute()
        if story.data and len(story.data) > 0:
            if str(story.data[0].get("user_id")) == str(user_id):
                return ROLE_OWNER
        res = supabase.table("project_members").select("role").eq(
            "story_id", story_id
        ).eq("user_email", user_email).execute()
        if res.data and len(res.data) > 0:
            r = (res.data[0].get("role") or "").lower()
            if r in (ROLE_OWNER, ROLE_PARTNER, ROLE_VIEWER):
                return r
        return None
    except Exception:
        return None


def check_permission(
    user_id: str,
    user_email: str,
    story_id: str,
    action: str,
) -> bool:
    """
    Kiểm tra user có quyền thực hiện action không.
    action: 'read' | 'write' | 'delete' | 'approve' | 'request_write'
    """
    if not user_id and not user_email:
        return False
    role = get_user_role(user_id, user_email, story_id)
    if role is None:
        return False
    if role == ROLE_OWNER:
        return action in ("read", "write", "delete", "approve", "request_write")
    if role == ROLE_PARTNER:
        return action in ("read", "request_write")
    if role == ROLE_VIEWER:
        return action == "read"
    return False


def get_user_projects(user_id: str, user_email: str) -> List[Dict[str, Any]]:
    """
    Trả về list project: của chính mình (stories.user_id = user_id) + project được share (project_members.user_email).
    Mỗi phần tử: dict từ bảng stories, có thêm key 'role' ('owner' | 'partner' | 'viewer').
    """
    services = _get_services()
    if not services:
        return []
    supabase = services["supabase"]
    result = []
    seen_ids = set()
    try:
        own = supabase.table("stories").select("*").eq("user_id", user_id).execute()
        if own.data:
            for p in own.data:
                pid = p.get("id")
                if pid and pid not in seen_ids:
                    p = dict(p)
                    p["role"] = ROLE_OWNER
                    result.append(p)
                    seen_ids.add(pid)
    except Exception:
        pass
    try:
        members = supabase.table("project_members").select("story_id, role").eq(
            "user_email", user_email
        ).execute()
        if members.data:
            for m in members.data:
                sid = m.get("story_id")
                if sid and sid not in seen_ids:
                    story = supabase.table("stories").select("*").eq("id", sid).execute()
                    if story.data and len(story.data) > 0:
                        p = dict(story.data[0])
                        p["role"] = (m.get("role") or ROLE_VIEWER).lower()
                        result.append(p)
                        seen_ids.add(sid)
    except Exception:
        pass
    return result


def submit_pending_change(
    story_id: str,
    requested_by_email: str,
    table_name: str,
    target_key: Dict[str, Any],
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
) -> Optional[str]:
    """
    Insert vào pending_changes (dành cho Partner). Trả về id record hoặc None nếu lỗi.
    """
    services = _get_services()
    if not services:
        return None
    try:
        supabase = services["supabase"]
        payload = {
            "story_id": story_id,
            "requested_by_email": requested_by_email,
            "table_name": table_name,
            # Đảm bảo JSONB hợp lệ, tránh lỗi serialization
            "target_key": json.loads(json.dumps(target_key or {}, default=str)),
            "old_data": json.loads(json.dumps(old_data or {}, default=str)),
            "new_data": json.loads(json.dumps(new_data or {}, default=str)),
            "status": "pending",
        }
        r = supabase.table("pending_changes").insert(payload).execute()
        if r.data and len(r.data) > 0:
            return r.data[0].get("id")
    except Exception as e:
        print(f"submit_pending_change error: {e}")
    return None


def get_pending_changes(story_id: str, status: str = "pending") -> List[Dict[str, Any]]:
    """Lấy danh sách pending_changes theo story_id và status."""
    services = _get_services()
    if not services:
        return []
    try:
        r = (
            services["supabase"]
            .table("pending_changes")
            .select("*")
            .eq("story_id", story_id)
            .eq("status", status)
            .order("created_at", desc=True)
            .execute()
        )
        return list(r.data) if r.data else []
    except Exception:
        return []


def approve_pending_change(pending_id: str) -> bool:
    """
    Approve: áp dụng new_data vào bảng tương ứng, rồi đổi status thành 'approved' (hoặc xóa record).
    Trả về True nếu thành công.
    """
    services = _get_services()
    if not services:
        return False
    supabase = services["supabase"]
    try:
        row = (
            supabase.table("pending_changes")
            .select("*")
            .eq("id", pending_id)
            .execute()
        )
        if not row.data or len(row.data) == 0:
            return False
        rec = row.data[0]
        table_name = (rec.get("table_name") or "").strip().lower()
        target_key = rec.get("target_key") or {}
        new_data = rec.get("new_data") or {}
        story_id = rec.get("story_id")

        if table_name == "chapters":
            payload = {**new_data, "story_id": story_id}
            if "chapter_number" in target_key:
                payload["chapter_number"] = target_key["chapter_number"]
            supabase.table("chapters").upsert(
                payload, on_conflict="story_id,chapter_number"
            ).execute()
        elif table_name == "story_bible":
            if target_key.get("id"):
                # update existing
                upd = {k: v for k, v in new_data.items() if k != "id"}
                supabase.table("story_bible").update(upd).eq(
                    "id", target_key["id"]
                ).execute()
            else:
                # insert new
                insert_data = {**new_data, "story_id": story_id}
                supabase.table("story_bible").insert(insert_data).execute()
        else:
            pass

        supabase.table("pending_changes").update({"status": "approved"}).eq(
            "id", pending_id
        ).execute()
        return True
    except Exception:
        return False


def reject_pending_change(pending_id: str) -> bool:
    """Đổi status pending_changes thành 'rejected'."""
    services = _get_services()
    if not services:
        return False
    try:
        services["supabase"].table("pending_changes").update(
            {"status": "rejected"}
        ).eq("id", pending_id).execute()
        return True
    except Exception:
        return False
