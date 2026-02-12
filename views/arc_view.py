# views/arc_view.py - UI Arc (V6)
"""Arc Management. Hiển thị chương thuộc mỗi arc. Xóa, Danger Zone."""
import streamlit as st
from datetime import datetime

from config import init_services
from utils.auth_manager import check_permission
from ai_engine import generate_arc_summary_from_chapters

try:
    from core.arc_service import ArcService
except ImportError:
    ArcService = None


def render_arc_tab(project_id):
    st.subheader("📐 Arc Management")
    st.caption("Ver 6.0: Phân vùng ngữ cảnh. Mỗi Arc gồm các chương từ Workstation.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    if not ArcService:
        st.warning("ArcService chưa load.")
        return

    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    user = st.session_state.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_email = getattr(user, "email", None) if user else None
    can_write = check_permission(str(user_id or ""), user_email or "", project_id, "write")
    can_delete = check_permission(str(user_id or ""), user_email or "", project_id, "delete")

    arcs = ArcService.list_arcs(project_id, status=None)
    arcs_active = [a for a in arcs if a.get("status") == "active"]
    arcs_archived = [a for a in arcs if a.get("status") == "archived"]

    current_arc_id = st.session_state.get("current_arc_id")
    if current_arc_id:
        scope_desc = ArcService.get_scope_description(project_id, current_arc_id)
        st.info(f"📌 Scope: {scope_desc}")

    st.markdown("#### Danh sách Arc")
    if not arcs:
        st.info("Chưa có Arc. Tạo mới bên dưới.")
    else:
        for a in arcs_active:
            arc_id = a.get("id")
            chaps_r = supabase.table("chapters").select("id, chapter_number, title").eq("story_id", project_id).eq("arc_id", arc_id).order("chapter_number").execute()
            chaps = chaps_r.data or []
            chap_labels = [f"Ch. {c['chapter_number']}: {c.get('title','')[:30]}" for c in chaps]
            with st.expander(f"🟢 {a.get('name','Unnamed')} ({a.get('type','')}) — {len(chaps)} chương", expanded=True):
                st.write("**Tóm tắt:**", (a.get("summary") or "—"))
                if chap_labels:
                    st.caption("**Chương thuộc arc:** " + ", ".join(chap_labels[:10]) + ("..." if len(chap_labels) > 10 else ""))
                else:
                    st.caption("_Chưa có chương nào gán arc này_")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if can_write and st.button("🔄 Cập nhật tóm tắt", key=f"arc_update_{arc_id}", help="Lấy tóm tắt từng chương → tạo tóm tắt Arc"):
                        st.session_state["arc_updating"] = arc_id
                        st.rerun()
                    if can_write and st.button("✏️ Sửa tóm tắt", key=f"arc_edit_{arc_id}"):
                        st.session_state["arc_editing"] = arc_id
                with col2:
                    if a.get("status") == "active" and st.button("📦 Archive", key=f"arc_archive_{arc_id}"):
                        supabase.table("arcs").update({"status": "archived", "updated_at": datetime.utcnow().isoformat()}).eq("id", arc_id).execute()
                        st.toast("Đã archive.")
                        st.rerun()
                with col3:
                    if can_delete and st.button("🗑️ Xóa Arc", key=f"arc_del_{arc_id}"):
                        supabase.table("arcs").update({"status": "archived"}).eq("id", arc_id).execute()
                        st.toast("Đã archive (xóa mềm).")
                        st.rerun()

        for a in arcs_archived:
            arc_id = a.get("id")
            chaps_r = supabase.table("chapters").select("id, chapter_number, title").eq("story_id", project_id).eq("arc_id", arc_id).order("chapter_number").execute()
            chaps_arch = chaps_r.data or []
            with st.expander(f"📦 {a.get('name','Unnamed')} (archived) — {len(chaps_arch)} chương", expanded=False):
                st.write("**Tóm tắt:**", (a.get("summary") or "—"))
                st.caption("Arc đã archive: không xóa chương thuộc arc này. Dùng Un-archive để chỉnh sửa.")
                if can_write and st.button("↩️ Un-archive", key=f"arc_unarchive_{arc_id}"):
                    supabase.table("arcs").update({"status": "active", "updated_at": datetime.utcnow().isoformat()}).eq("id", arc_id).execute()
                    st.toast("Đã bỏ archive.")
                    st.rerun()

    if st.session_state.get("arc_updating") and can_write:
        update_id = st.session_state["arc_updating"]
        arc = next((x for x in arcs if str(x.get("id")) == str(update_id)), None)
        if arc:
            st.markdown("---")
            with st.spinner("Đang lấy tóm tắt chương và tạo tóm tắt Arc..."):
                chaps_r = supabase.table("chapters").select("id, chapter_number, title, summary").eq("story_id", project_id).eq("arc_id", update_id).order("chapter_number").execute()
                chaps_data = chaps_r.data or []
                chapter_summaries = [{"chapter_number": c.get("chapter_number"), "summary": c.get("summary") or ""} for c in chaps_data if c.get("summary")]
                if not chapter_summaries:
                    st.warning("Không có chương nào có tóm tắt. Thêm tóm tắt chương trước khi cập nhật Arc.")
                    if st.button("Đóng", key="arc_update_close"):
                        del st.session_state["arc_updating"]
                        st.rerun()
                else:
                    new_summary = generate_arc_summary_from_chapters(chapter_summaries, arc.get("name", ""))
                    if new_summary:
                        supabase.table("arcs").update({"summary": new_summary, "updated_at": datetime.utcnow().isoformat()}).eq("id", update_id).execute()
                        del st.session_state["arc_updating"]
                        st.success("Đã cập nhật tóm tắt Arc từ tóm tắt chương!")
                        st.rerun()
                    else:
                        st.error("Không thể tạo tóm tắt. Thử lại sau.")
                        if st.button("Đóng", key="arc_update_close2"):
                            del st.session_state["arc_updating"]
                            st.rerun()

    if st.session_state.get("arc_editing") and can_write:
        edit_id = st.session_state["arc_editing"]
        arc = next((x for x in arcs if str(x.get("id")) == str(edit_id)), None)
        if arc:
            st.markdown("---")
            with st.form("arc_edit_form"):
                new_summary = st.text_area("Tóm tắt", value=arc.get("summary") or "", key="arc_new_summary")
                if st.form_submit_button("💾 Lưu"):
                    supabase.table("arcs").update({"summary": new_summary, "updated_at": datetime.utcnow().isoformat()}).eq("id", edit_id).execute()
                    del st.session_state["arc_editing"]
                    st.success("Đã cập nhật.")
                    st.rerun()
                if st.form_submit_button("Hủy"):
                    del st.session_state["arc_editing"]
                    st.rerun()

    st.markdown("---")
    st.subheader("Tạo Arc mới")
    if can_write:
        with st.form("new_arc_form"):
            arc_name = st.text_input("Tên Arc", placeholder="VD: Arc 1 - Khởi đầu")
            arc_type = st.selectbox("Loại", ["SEQUENTIAL", "STANDALONE"], format_func=lambda x: "Kế thừa" if x == "SEQUENTIAL" else "Độc lập")
            arc_summary = st.text_area("Tóm tắt", placeholder="Mô tả ngắn...")
            if st.form_submit_button("➕ Tạo"):
                if arc_name:
                    supabase.table("arcs").insert({
                        "story_id": project_id,
                        "name": arc_name.strip(),
                        "type": arc_type,
                        "status": "active",
                        "summary": arc_summary or "",
                        "sort_order": len(arcs) + 1,
                    }).execute()
                    st.success("Đã tạo Arc.")
                    st.rerun()

    st.markdown("---")
    with st.expander("💀 Danger Zone", expanded=False):
        st.markdown('<div class="danger-zone">', unsafe_allow_html=True)
        if can_delete and arcs:
            confirm = st.checkbox("Archive tất cả Arc (không xóa vĩnh viễn)", key="arc_confirm_clear")
            if confirm and st.button("📦 Archive tất cả Arc"):
                for a in arcs_active:
                    supabase.table("arcs").update({"status": "archived"}).eq("id", a["id"]).execute()
                st.success("Đã archive tất cả.")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
