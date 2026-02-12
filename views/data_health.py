# views/data_health.py - V6 MODULE 5: Data Health UI (Active Sentry)
"""
Display list of validation conflicts. User actions: Force Sync with Bible | Keep Exception.
"""
import streamlit as st

from utils.active_sentry import get_pending_conflicts, resolve_conflict


def render_data_health_tab(project_id):
    """Tab Data Health: list conflicts from validation_logs, resolve with Force Sync or Keep Exception."""
    st.subheader("🛡️ Data Health (Active Sentry)")

    if not project_id:
        st.info("📁 Chọn Project ở thanh bên trái.")
        return

    conflicts = get_pending_conflicts(project_id)
    if not conflicts:
        st.success("✅ Không có xung đột đang chờ. Dữ liệu đã đồng bộ với Bible và cross-sheet.")
        return

    st.markdown("#### Conflicts (Pending)")
    for c in conflicts:
        log_id = c.get("id")
        msg = c.get("message", "")
        log_type = c.get("log_type", "other")
        details = c.get("details") or {}
        with st.expander("⚠️ %s — %s" % (log_type, msg[:80])):
            st.write("**Message:** %s" % msg)
            if details:
                st.json(details)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Force Sync with Bible", key="force_%s" % log_id):
                    if resolve_conflict(log_id, "resolved_force_sync", resolved_by=getattr(st.session_state.get("user"), "email", "")):
                        st.toast("Đã đánh dấu: Force Sync with Bible.")
                        st.rerun()
            with col2:
                if st.button("📌 Keep Exception", key="keep_%s" % log_id):
                    if resolve_conflict(log_id, "resolved_keep_exception", resolved_by=getattr(st.session_state.get("user"), "email", "")):
                        st.toast("Đã đánh dấu: Keep Exception.")
                        st.rerun()
