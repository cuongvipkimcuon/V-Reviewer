# core/arc_service.py - V6 MODULE 1: ARC ARCHITECTURE (Timeline & Context Partitioning)
"""
Manage arcs: SEQUENTIAL (timeline inheritance) vs STANDALONE (total isolation).
Context scoping: [Global Bible] + [Past Arc Summaries if sequential] + [Current Arc].
"""
from typing import Dict, List, Optional, Any

from config import init_services


class ArcService:
    """Arc CRUD and context scoping for V6."""

    ARC_TYPE_SEQUENTIAL = "SEQUENTIAL"
    ARC_TYPE_STANDALONE = "STANDALONE"

    @staticmethod
    def _supabase():
        s = init_services()
        return s["supabase"] if s else None

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    @staticmethod
    def get_arc(arc_id: str) -> Optional[Dict[str, Any]]:
        """Get a single arc by id."""
        supabase = ArcService._supabase()
        if not supabase or not arc_id:
            return None
        try:
            r = supabase.table("arcs").select("*").eq("id", arc_id).limit(1).execute()
            return r.data[0] if r.data else None
        except Exception:
            return None

    @staticmethod
    def list_arcs(story_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List arcs for a project, ordered by sort_order."""
        supabase = ArcService._supabase()
        if not supabase or not story_id:
            return []
        try:
            q = supabase.table("arcs").select("*").eq("story_id", story_id)
            if status:
                q = q.eq("status", status)
            r = q.order("sort_order").order("created_at").execute()
            return list(r.data) if r.data else []
        except Exception:
            return []

    @staticmethod
    def get_current_arc_id(story_id: str, from_session: Optional[Dict] = None) -> Optional[str]:
        """
        Resolve "current" arc for the project.
        If from_session has 'current_arc_id', use it; else use latest active arc by sort_order.
        """
        if from_session and from_session.get("current_arc_id"):
            return from_session["current_arc_id"]
        arcs = ArcService.list_arcs(story_id, status="active")
        if not arcs:
            return None
        return arcs[-1].get("id")

    @staticmethod
    def get_past_arc_summaries(story_id: str, current_arc_id: str) -> List[Dict[str, Any]]:
        """
        For SEQUENTIAL mode: return arcs that are "before" current in timeline.
        Order: follow prev_arc_id chain from current backwards, then by sort_order/created_at.
        Returns list of {id, name, summary} for injection as [Past Arc Summaries].
        """
        current = ArcService.get_arc(current_arc_id)
        if not current or current.get("type") != ArcService.ARC_TYPE_SEQUENTIAL:
            return []
        past = []
        seen = {current_arc_id}
        prev_id = current.get("prev_arc_id")
        while prev_id and prev_id not in seen:
            seen.add(prev_id)
            a = ArcService.get_arc(prev_id)
            if not a or a.get("story_id") != story_id:
                break
            past.append({"id": a.get("id"), "name": a.get("name") or "", "summary": a.get("summary") or ""})
            prev_id = a.get("prev_arc_id")
        past.reverse()
        return past

    # -------------------------------------------------------------------------
    # Context scoping (Module 1)
    # -------------------------------------------------------------------------
    @staticmethod
    def get_scope_description(story_id: str, current_arc_id: Optional[str]) -> str:
        """
        Returns human-readable scope: Standalone = [Global Bible] + [Current Arc].
        Sequential = [Global Bible] + [Past Arc Summaries] + [Current Arc].
        """
        if not current_arc_id:
            return "[Global Bible] (no arc selected)"
        arc = ArcService.get_arc(current_arc_id)
        if not arc:
            return "[Global Bible] + [Current Arc]"
        if arc.get("type") == ArcService.ARC_TYPE_SEQUENTIAL:
            past = ArcService.get_past_arc_summaries(story_id, current_arc_id)
            return "[Global Bible] + [Past Arc Summaries] (%d) + [Current Arc: %s]" % (
                len(past),
                arc.get("name") or current_arc_id[:8],
            )
        return "[Global Bible] + [Current Arc: %s] (Standalone)" % (arc.get("name") or current_arc_id[:8])

    @staticmethod
    def get_scope_for_search(
        story_id: str,
        current_arc_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Returns scope config for search/context:
        - global_bible: True (always include story-level Bible)
        - arc_summaries: list of {name, summary} for past arcs (Sequential only)
        - current_arc_id: for filtering chapters/chunks
        - scope_type: 'STANDALONE' | 'SEQUENTIAL'
        """
        out = {
            "global_bible": True,
            "arc_summaries": [],
            "current_arc_id": current_arc_id,
            "scope_type": ArcService.ARC_TYPE_STANDALONE,
        }
        if not current_arc_id:
            return out
        arc = ArcService.get_arc(current_arc_id)
        if not arc:
            return out
        out["scope_type"] = arc.get("type") or ArcService.ARC_TYPE_STANDALONE
        if out["scope_type"] == ArcService.ARC_TYPE_SEQUENTIAL:
            out["arc_summaries"] = ArcService.get_past_arc_summaries(story_id, current_arc_id)
        return out
