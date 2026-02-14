# views/timeline_view.py - Quản lý Timeline (bảng timeline_events)
"""Tab Timeline trong Knowledge: xem, thêm, sửa, xóa sự kiện timeline."""
import streamlit as st

from config import init_services
from ai_engine import get_timeline_events
from utils.auth_manager import check_permission


def render_timeline_tab(project_id):
    st.header("📅 Timeline")
    st.caption("Quản lý sự kiện theo thứ tự thời gian (timeline_events). Dùng cho intent manage_timeline trong Chat.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    try:
        supabase.table("timeline_events").select("id").limit(1).execute()
    except Exception as e:
        st.warning("Bảng timeline_events chưa tồn tại. Chạy migration schema_v7_migration.sql trên Supabase.")
        return

    user_id = getattr(st.session_state.get("user"), "id", None) or ""
    user_email = getattr(st.session_state.get("user"), "email", None) or ""
    can_write = check_permission(user_id, user_email, project_id, "write")

    # --- Danh sách sự kiện ---
    events = get_timeline_events(project_id, limit=200)
    events_sorted = sorted(events, key=lambda x: (x.get("event_order", 0), x.get("title", "")))

    st.subheader("Danh sách sự kiện")
    if not events_sorted:
        st.info("Chưa có sự kiện nào. Thêm mới bên dưới hoặc trích xuất từ chương trong Data Analyze → tab Timeline.")
    else:
        for i, ev in enumerate(events_sorted):
            eid = ev.get("id")
            with st.expander(f"#{ev.get('event_order', i+1)} [{ev.get('event_type', 'event')}] {ev.get('title', '')}", expanded=False):
                st.write("**Mô tả:**", ev.get("description") or "(trống)")
                st.write("**Thời điểm:**", ev.get("raw_date") or "(trống)")
                if can_write:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("✏️ Sửa", key=f"tl_edit_{eid}"):
                            st.session_state["tl_editing_id"] = eid
                            st.session_state["tl_edit_title"] = ev.get("title", "")
                            st.session_state["tl_edit_description"] = ev.get("description", "") or ""
                            st.session_state["tl_edit_raw_date"] = ev.get("raw_date", "") or ""
                            st.session_state["tl_edit_event_type"] = ev.get("event_type", "event")
                            st.session_state["tl_edit_event_order"] = ev.get("event_order", 0)
                            st.rerun()
                    with col_b:
                        if st.button("🗑️ Xóa", key=f"tl_del_{eid}"):
                            st.session_state["tl_confirm_delete_id"] = eid
                            st.rerun()

        if st.session_state.get("tl_confirm_delete_id"):
            del_id = st.session_state["tl_confirm_delete_id"]
            st.warning("Xác nhận xóa sự kiện này?")
            if st.button("✅ Xóa", key="tl_confirm_del_yes"):
                try:
                    supabase.table("timeline_events").delete().eq("id", del_id).execute()
                    st.session_state.pop("tl_confirm_delete_id", None)
                    st.toast("Đã xóa.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            if st.button("❌ Hủy", key="tl_confirm_del_no"):
                st.session_state.pop("tl_confirm_delete_id", None)
                st.rerun()

    # --- Form sửa (khi đang edit) ---
    if st.session_state.get("tl_editing_id"):
        st.markdown("---")
        st.subheader("✏️ Chỉnh sửa sự kiện")
        edit_id = st.session_state["tl_editing_id"]
        new_title = st.text_input("Tiêu đề", value=st.session_state.get("tl_edit_title", ""), key="tl_edit_title_inp")
        new_desc = st.text_area("Mô tả", value=st.session_state.get("tl_edit_description", ""), key="tl_edit_desc_inp")
        new_date = st.text_input("Thời điểm (raw_date)", value=st.session_state.get("tl_edit_raw_date", ""), key="tl_edit_date_inp")
        new_type = st.selectbox(
            "Loại",
            ["event", "flashback", "milestone", "timeskip", "other"],
            index=["event", "flashback", "milestone", "timeskip", "other"].index(st.session_state.get("tl_edit_event_type", "event")),
            key="tl_edit_type_inp",
        )
        new_order = st.number_input("Thứ tự (event_order)", min_value=0, value=int(st.session_state.get("tl_edit_event_order", 0)), key="tl_edit_order_inp")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Lưu thay đổi", key="tl_edit_save"):
                try:
                    supabase.table("timeline_events").update({
                        "title": new_title.strip() or "Sự kiện",
                        "description": new_desc.strip(),
                        "raw_date": new_date.strip(),
                        "event_type": new_type,
                        "event_order": new_order,
                    }).eq("id", edit_id).execute()
                    for k in ["tl_editing_id", "tl_edit_title", "tl_edit_description", "tl_edit_raw_date", "tl_edit_event_type", "tl_edit_event_order"]:
                        st.session_state.pop(k, None)
                    st.toast("Đã lưu.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with c2:
            if st.button("❌ Hủy sửa", key="tl_edit_cancel"):
                for k in ["tl_editing_id", "tl_edit_title", "tl_edit_description", "tl_edit_raw_date", "tl_edit_event_type", "tl_edit_event_order"]:
                    st.session_state.pop(k, None)
                st.rerun()

    # --- Thêm mới ---
    st.markdown("---")
    st.subheader("➕ Thêm sự kiện mới")
    if not can_write:
        st.caption("Chỉ thành viên có quyền ghi mới thêm/sửa/xóa.")
    else:
        with st.form("tl_new_form"):
            new_title = st.text_input("Tiêu đề", key="tl_new_title")
            new_desc = st.text_area("Mô tả", key="tl_new_desc")
            new_date = st.text_input("Thời điểm (raw_date)", placeholder="vd: đầu chương 3, năm 2020", key="tl_new_date")
            new_type = st.selectbox("Loại", ["event", "flashback", "milestone", "timeskip", "other"], key="tl_new_type")
            new_order = st.number_input("Thứ tự (event_order)", min_value=0, value=len(events_sorted) + 1, key="tl_new_order")
            if st.form_submit_button("Thêm"):
                if new_title and new_title.strip():
                    try:
                        supabase.table("timeline_events").insert({
                            "story_id": project_id,
                            "event_order": new_order,
                            "title": new_title.strip(),
                            "description": (new_desc or "").strip(),
                            "raw_date": (new_date or "").strip(),
                            "event_type": new_type,
                        }).execute()
                        st.toast("Đã thêm sự kiện.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
                else:
                    st.warning("Nhập tiêu đề.")
