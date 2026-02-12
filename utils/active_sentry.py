# utils/active_sentry.py - V6 MODULE 5: ACTIVE SENTRY (The Validator)
"""
Proactive conflict detection: Bible integrity, cross-sheet logic.
On upload/import: validate and log to validation_logs. User can Force Sync with Bible or Keep Exception.
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from config import init_services


def _supabase():
    s = init_services()
    return s["supabase"] if s else None


def _get_bible_entities(story_id: str) -> List[Dict[str, Any]]:
    """Fetch bible entities (entity_name, description) for project."""
    supabase = _supabase()
    if not supabase or not story_id:
        return []
    try:
        r = supabase.table("story_bible").select("entity_name, description").eq("story_id", story_id).execute()
        return list(r.data) if r.data else []
    except Exception:
        return []


def _log_conflict(
    story_id: str,
    arc_id: Optional[str],
    log_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Insert into validation_logs. Returns id or None."""
    supabase = _supabase()
    if not supabase:
        return None
    try:
        payload = {
            "story_id": story_id,
            "log_type": log_type,
            "message": message,
            "details": details or {},
            "status": "pending",
        }
        if arc_id:
            payload["arc_id"] = arc_id
        r = supabase.table("validation_logs").insert(payload).execute()
        if r.data and len(r.data) > 0:
            return r.data[0].get("id")
    except Exception:
        pass
    return None


class ValidationWorker:
    """
    On file upload / chunk import:
    1. Bible Integrity: Does "Material: Tarpaulin" match a definition in story_bible?
    2. Cross-Sheet: Does Price in Order List match Price in Quotation Sheet?
    """

    @staticmethod
    def check_bible_integrity(
        story_id: str,
        chunk_content: str,
        chunk_meta: Optional[Dict] = None,
        arc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Heuristic: look for patterns like "Material: X", "Status: Y" in chunk_content.
        Compare X, Y to bible entity names/descriptions. If no match, log conflict.
        Returns list of {log_id, message, details} for conflicts found.
        """
        import re
        bible = _get_bible_entities(story_id)
        if not bible:
            return []
        conflicts = []
        # Build set of known terms from Bible (entity_name and first words of description)
        known = set()
        for b in bible:
            name = (b.get("entity_name") or "").strip()
            if name:
                known.add(name.lower())
            desc = (b.get("description") or "").strip()
            for w in desc.split()[:20]:
                if len(w) > 2:
                    known.add(w.lower())
        # Simple pattern: "Key: Value" in content
        for m in re.finditer(r"(?i)(\w+)\s*:\s*([^\n,;]+)", chunk_content):
            key, val = m.group(1).strip(), m.group(2).strip()
            if not val or len(val) < 2:
                continue
            val_lower = val.lower()
            if val_lower not in known and key.lower() in ("material", "status", "type", "category", "name"):
                log_id = _log_conflict(
                    story_id,
                    arc_id,
                    "bible_integrity",
                    "Value '%s' (from %s) not found in Bible definitions." % (val, key),
                    {"key": key, "value": val, "chunk_meta": chunk_meta},
                )
                if log_id:
                    conflicts.append({"log_id": log_id, "message": "Bible integrity: %s = %s" % (key, val), "details": {"key": key, "value": val}})
        return conflicts

    @staticmethod
    def check_cross_sheet(
        story_id: str,
        chunks: List[Dict[str, Any]],
        arc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Heuristic: if chunks contain both "Order" sheet and "Quotation" sheet (from meta_json),
        compare Price (or similar) columns. If mismatch, log.
        Returns list of conflicts.
        """
        orders = []
        quotations = []
        for c in chunks:
            meta = c.get("meta_json") or {}
            sm = meta.get("source_metadata", meta) if isinstance(meta, dict) else {}
            sheet = (sm.get("sheet_name") or "").lower()
            content = (c.get("content") or c.get("raw_content") or "").lower()
            if "order" in sheet or "order" in content[:200]:
                orders.append(c)
            if "quotation" in sheet or "quote" in sheet or "quotation" in content[:200]:
                quotations.append(c)
        conflicts = []
        if not orders or not quotations:
            return conflicts
        import re
        def extract_prices(text):
            out = []
            for m in re.finditer(r"(?i)price\s*:\s*([0-9.,]+)", text):
                out.append(m.group(1).replace(",", ""))
            for m in re.finditer(r"(?i)([0-9.,]+)\s*(?:vnd|usd|usd)", text):
                out.append(m.group(1).replace(",", ""))
            return out
        order_prices = set()
        for o in orders:
            order_prices.update(extract_prices(o.get("content", "") + " " + o.get("raw_content", "")))
        for q in quotations:
            qp = extract_prices(q.get("content", "") + " " + q.get("raw_content", ""))
            for p in qp:
                if p and order_prices and p not in order_prices:
                    log_id = _log_conflict(
                        story_id,
                        arc_id,
                        "cross_sheet",
                        "Price %s in Quotation not found in Order list." % p,
                        {"price": p, "order_prices": list(order_prices)[:10]},
                    )
                    if log_id:
                        conflicts.append({"log_id": log_id, "message": "Cross-sheet price mismatch: %s" % p, "details": {"price": p}})
        return conflicts

    @staticmethod
    def run_on_chunks(
        story_id: str,
        chunks: List[Dict[str, Any]],
        arc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run Bible integrity on each chunk and cross-sheet on full set. Return all conflicts."""
        all_conflicts = []
        for c in chunks:
            all_conflicts.extend(
                ValidationWorker.check_bible_integrity(
                    story_id,
                    c.get("content", "") or c.get("raw_content", ""),
                    c.get("meta_json"),
                    arc_id,
                )
            )
        all_conflicts.extend(ValidationWorker.check_cross_sheet(story_id, chunks, arc_id))
        return all_conflicts


def get_pending_conflicts(story_id: str, arc_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List validation_logs with status = pending."""
    supabase = _supabase()
    if not supabase:
        return []
    try:
        q = supabase.table("validation_logs").select("*").eq("story_id", story_id).eq("status", "pending")
        if arc_id:
            q = q.eq("arc_id", arc_id)
        r = q.order("created_at", desc=True).execute()
        return list(r.data) if r.data else []
    except Exception:
        return []


def resolve_conflict(log_id: int, action: str, resolved_by: Optional[str] = None) -> bool:
    """action: 'resolved_force_sync' | 'resolved_keep_exception'. Returns True if updated."""
    if action not in ("resolved_force_sync", "resolved_keep_exception"):
        return False
    supabase = _supabase()
    if not supabase:
        return False
    try:
        from datetime import datetime, timezone
        supabase.table("validation_logs").update({
            "status": action,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": resolved_by or "",
        }).eq("id", log_id).execute()
        return True
    except Exception:
        return False
