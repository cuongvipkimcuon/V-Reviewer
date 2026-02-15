# views/background_tasks_tab.py - Background Jobs tab: list jobs, nút Refresh để tải lại
import streamlit as st

from config import init_services
from core.background_jobs import list_jobs


def render_background_tasks_tab(project_id):
    if not project_id:
        st.info("Please select a project in the sidebar.")
        return

    st.subheader("Background Jobs")
    st.caption("Data Analyze and batch operations. Bấm **Refresh** để tải lại danh sách.")

    try:
        services = init_services()
        if not services:
            st.warning("Could not connect to services.")
            return
    except Exception:
        st.warning("Could not connect to services.")
        return

    if st.button("🔄 Refresh", key="bg_tasks_refresh_btn"):
        st.rerun()

    status_filter = st.selectbox(
        "Status",
        ["All", "pending", "running", "completed", "failed"],
        key="bg_tasks_filter",
    )
    status_key = None if status_filter == "All" else status_filter
    jobs = list_jobs(project_id, status_filter=status_key, limit=80)
    if not jobs:
        st.info("No background jobs yet.")
        return

    for j in jobs:
        status = j.get("status", "pending")
        label = j.get("label", "Job")
        job_type = j.get("job_type", "")
        created = j.get("created_at") or ""
        started = j.get("started_at") or ""
        completed = j.get("completed_at") or ""
        result_summary = j.get("result_summary") or ""
        error_message = j.get("error_message") or ""

        if isinstance(created, str) and len(created) > 19:
            created = created[:19].replace("T", " ")
        if isinstance(started, str) and len(started) > 19:
            started = started[:19].replace("T", " ")
        if isinstance(completed, str) and len(completed) > 19:
            completed = completed[:19].replace("T", " ")

        if status == "running":
            icon = "🔄"
        elif status == "completed":
            icon = "✅"
        elif status == "failed":
            icon = "❌"
        else:
            icon = "⏸️"

        with st.expander(f"{icon} **{label}** — {status}", expanded=(status in ("running", "failed"))):
            st.caption(f"Type: {job_type} | Created: {created}")
            if started:
                st.caption(f"Started: {started}")
            if completed:
                st.caption(f"Completed: {completed}")
            if result_summary:
                st.success(result_summary)
            if error_message:
                st.error(error_message)
