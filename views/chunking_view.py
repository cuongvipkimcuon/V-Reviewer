# views/chunking_view.py - Danh sách chunks đã lưu: xem, sửa nội dung, vector lại, xóa
"""Chunking: chỉ quản lý chunks đã lưu. Logic tách chunk (Workstation) nằm trong utils.chunk_tools."""
from datetime import timedelta

import streamlit as st

from config import init_services
from ai_engine import AIService
from utils.auth_manager import check_permission


def _ensure_chunks_table(supabase):
    """Đảm bảo bảng chunks tồn tại (schema v6)."""
    try:
        supabase.table("chunks").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def render_chunking_tab(project_id):
    """Tab Chunking - Chỉ hiển thị và quản lý chunks đã lưu: sửa nội dung, vector lại, xóa."""
    st.subheader("✂️ Chunks đã lưu")
    st.caption("Chunks được vector hóa để search trong Chat. Sửa nội dung rồi bấm **Cập nhật & Vector lại** để không phải chunk lại từ đầu.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    if not _ensure_chunks_table(supabase):
        st.warning("Bảng chunks chưa tồn tại. Chạy schema_v6_migration.sql trong Supabase.")
        return

    user = st.session_state.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_email = getattr(user, "email", None) if user else None
    can_write = bool(
        project_id and user_id
        and check_permission(str(user_id), user_email or "", project_id, "write")
    )
    can_delete = check_permission(str(user_id or ""), user_email or "", project_id, "delete")

    @st.fragment(run_every=timedelta(seconds=30))
    def _chunks_list_fresh():
        r = supabase.table("chunks").select(
            "id, content, raw_content, source_type, meta_json, arc_id, chapter_id, sort_order"
        ).eq("story_id", project_id).order("sort_order").execute()
        chunks_list = r.data or []
        st.metric("Tổng chunks", len(chunks_list))
        for c in chunks_list:
            cid = c.get("id")
            content = (c.get("content") or c.get("raw_content") or "").strip()
            meta = c.get("meta_json") or {}
            sm = meta.get("source_metadata", meta) if isinstance(meta, dict) else meta
            label = (
                sm.get("sheet_name", "")
                or sm.get("source_file", "")
                or (meta.get("title") if isinstance(meta, dict) else "")
                or c.get("source_type", "")
                or str(cid or "")[:8]
            )
            short = (content[:60] + "…") if len(content) > 60 else content

            with st.expander(f"Chunk: {label} — {short}", expanded=False):
                st.text(content[:500] + ("…" if len(content) > 500 else ""))

                if can_write:
                    edit_key = f"chunk_edit_{cid}"
                    update_key = f"chunk_update_vec_{cid}"
                    new_content = st.text_area(
                        "Sửa nội dung (sau đó bấm Cập nhật & Vector lại)",
                        value=content,
                        height=120,
                        key=edit_key,
                    )
                    if st.button("🔄 Cập nhật & Vector lại", key=update_key, type="primary"):
                        if not (new_content and new_content.strip()):
                            st.warning("Nội dung không được để trống.")
                        else:
                            with st.spinner("Đang tạo embedding mới..."):
                                vec = AIService.get_embedding(new_content.strip())
                                if vec:
                                    try:
                                        supabase.table("chunks").update({
                                            "content": new_content.strip(),
                                            "raw_content": new_content.strip(),
                                            "embedding": vec,
                                        }).eq("id", cid).execute()
                                        st.success("Đã cập nhật nội dung và vector.")
                                        st.rerun()
                                    except Exception as e:
                                        if "embedding" in str(e).lower() or "vector" in str(e).lower():
                                            try:
                                                supabase.table("chunks").update({
                                                    "content": new_content.strip(),
                                                    "raw_content": new_content.strip(),
                                                }).eq("id", cid).execute()
                                                st.success("Đã cập nhật nội dung (embedding bỏ qua do lỗi DB).")
                                                st.rerun()
                                            except Exception as e2:
                                                st.error(str(e2))
                                        else:
                                            st.error(str(e))
                                else:
                                    st.warning("Không tạo được embedding.")

                if can_delete and st.button("🗑️ Xóa", key=f"chunk_del_{cid}"):
                    supabase.table("chunks").delete().eq("id", cid).execute()
                    st.success("Đã xóa.")
                    st.rerun()

        st.markdown("---")
        with st.expander("💀 Danger Zone", expanded=False):
            st.markdown('<div class="danger-zone">', unsafe_allow_html=True)
            if can_delete and chunks_list:
                confirm = st.checkbox("Xóa sạch TẤT CẢ chunks", key="chunk_confirm_clear")
                if confirm and st.button("🗑️ Xóa sạch Chunks"):
                    supabase.table("chunks").delete().eq("story_id", project_id).execute()
                    st.success("Đã xóa sạch.")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    _chunks_list_fresh()
