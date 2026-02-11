# Cache helpers: st.cache_data với TTL 5 phút. Invalidate bằng update_trigger (tham số thứ 2).
# Sau khi xóa/ghi DB: gọi st.cache_data.clear() và tăng st.session_state["update_trigger"] rồi st.rerun().
import streamlit as st


@st.cache_data(ttl=300)
def get_chapters_cached(project_id: str, update_trigger: int = 0):
    """Danh sách chapter đầy đủ cho project. update_trigger thay đổi -> cache miss."""
    if not project_id:
        return []
    try:
        from config import init_services
        services = init_services()
        if not services:
            return []
        r = (
            services["supabase"]
            .table("chapters")
            .select("*")
            .eq("story_id", project_id)
            .order("chapter_number")
            .execute()
        )
        return list(r.data) if r.data else []
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_bible_list_cached(project_id: str, update_trigger: int = 0):
    """Toàn bộ story_bible cho project (để list/filter). update_trigger thay đổi -> cache miss."""
    if not project_id:
        return []
    try:
        from config import init_services
        services = init_services()
        if not services:
            return []
        r = (
            services["supabase"]
            .table("story_bible")
            .select("*")
            .eq("story_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return list(r.data) if r.data else []
    except Exception:
        return []


def invalidate_cache_and_rerun():
    """Sau khi xóa/ghi DB: xóa cache RAM và tăng update_trigger rồi rerun. Gọi từ views."""
    st.cache_data.clear()
    st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
    st.rerun()


@st.cache_data(ttl=300)
def get_dashboard_metrics_cached(project_id: str, update_trigger: int = 0):
    """Dashboard: file_count, bible_count, rule_count, chat_count, recent_files, bible_prefix_list."""
    if not project_id:
        return {}
    try:
        from config import init_services
        services = init_services()
        if not services:
            return {}
        supabase = services["supabase"]
        files = supabase.table("chapters").select("count", count="exact").eq("story_id", project_id).execute()
        bible = supabase.table("story_bible").select("count", count="exact").eq("story_id", project_id).execute()
        rules = supabase.table("story_bible").select("count", count="exact").eq("story_id", project_id).ilike("entity_name", "%[RULE]%").execute()
        chat = supabase.table("chat_history").select("count", count="exact").eq("story_id", project_id).execute()
        recent = supabase.table("chapters").select("title, updated_at").eq("story_id", project_id).order("updated_at", desc=True).limit(5).execute()
        bible_entities = supabase.table("story_bible").select("entity_name").eq("story_id", project_id).execute()
        file_count = files.count if hasattr(files, "count") else len(files.data or [])
        bible_count = bible.count if hasattr(bible, "count") else len(bible.data or [])
        rule_count = rules.count if hasattr(rules, "count") else len(rules.data or [])
        chat_count = chat.count if hasattr(chat, "count") else len(chat.data or [])
        return {
            "file_count": file_count,
            "bible_count": bible_count,
            "rule_count": rule_count,
            "chat_count": chat_count,
            "recent_files": list(recent.data) if recent.data else [],
            "bible_entity_names": [x.get("entity_name") for x in (bible_entities.data or [])],
        }
    except Exception:
        return {}
