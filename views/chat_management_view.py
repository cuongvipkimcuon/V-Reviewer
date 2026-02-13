# views/chat_management_view.py - Quản lý Bible entries [CHAT] (Auto Crystallize)
"""Tab quản lý [CHAT]: xem, sửa nội dung, xóa. Không add tay - chỉ Auto Crystallize tạo."""
import streamlit as st

from config import init_services
from ai_engine import AIService
from utils.auth_manager import check_permission
from utils.cache_helpers import get_bible_list_cached, invalidate_cache_and_rerun


def render_chat_management_tab(project_id, persona):
    st.header("💬 Chat Knowledge")
    st.caption("Điểm nhớ từ hội thoại (Auto Crystallize). Chỉ sửa nội dung hoặc xóa. Không add tay.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    st.session_state.setdefault("update_trigger", 0)
    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]
    bible_data_all = get_bible_list_cached(project_id, st.session_state.get("update_trigger", 0))
    chat_data = [e for e in bible_data_all if (e.get("entity_name") or "").startswith("[CHAT]")]
    user = st.session_state.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_email = getattr(user, "email", None) if user else None
    can_write = check_permission(str(user_id or ""), user_email or "", project_id, "write")
    can_delete = check_permission(str(user_id or ""), user_email or "", project_id, "delete")

    st.metric("Tổng [CHAT] entries", len(chat_data))

    if not chat_data:
        st.info("Chưa có điểm nhớ [CHAT]. Auto Crystallize sẽ tạo khi đủ 30 tin nhắn trong Chat.")
        return

    for entry in chat_data:
        with st.expander(f"**{entry.get('entity_name', '')}**", expanded=False):
            st.markdown(entry.get("description", ""))
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✏️ Sửa nội dung", key=f"chat_edit_{entry['id']}") and can_write:
                    st.session_state["chat_editing"] = entry
            with col2:
                if can_delete and st.button("🗑️ Xóa", key=f"chat_del_{entry['id']}"):
                    try:
                        supabase.table("story_bible").delete().eq("id", entry["id"]).execute()
                        st.success("Đã xóa.")
                        invalidate_cache_and_rerun()
                    except Exception as e:
                        st.error(str(e))

    if st.session_state.get("chat_editing") and can_write:
        e = st.session_state["chat_editing"]
        st.markdown("---")
        st.subheader(f"Sửa: {e.get('entity_name', '')}")
        st.caption("Chỉ sửa nội dung (description). Tiền tố [CHAT] không thay đổi.")
        with st.form("edit_chat_form"):
            new_desc = st.text_area("Nội dung", value=e.get("description", ""), height=150)
            if st.form_submit_button("💾 Cập nhật"):
                vec = AIService.get_embedding(f"{e.get('entity_name', '')}: {new_desc}")
                upd = {"description": new_desc}
                if vec:
                    upd["embedding"] = vec
                try:
                    supabase.table("story_bible").update(upd).eq("id", e["id"]).execute()
                    st.success("Đã cập nhật.")
                    st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                    del st.session_state["chat_editing"]
                    invalidate_cache_and_rerun()
                except Exception as ex:
                    upd.pop("embedding", None)
                    supabase.table("story_bible").update(upd).eq("id", e["id"]).execute()
                    st.success("Đã cập nhật.")
                    del st.session_state["chat_editing"]
                    invalidate_cache_and_rerun()
            if st.form_submit_button("Hủy"):
                del st.session_state["chat_editing"]
                st.rerun()
