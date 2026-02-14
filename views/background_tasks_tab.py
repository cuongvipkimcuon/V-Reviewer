# views/background_tasks_tab.py - Background Jobs tab: list jobs, auto-refresh 30s, embedding backfill every 5 min
import threading
import time
from datetime import datetime, timedelta

import streamlit as st

from config import init_services
from core.background_jobs import list_jobs, run_embedding_backfill


def render_background_tasks_tab(project_id):
    if not project_id:
        st.info("Please select a project in the sidebar.")
        return

    st.subheader("Background Jobs")
    st.caption("Data Analyze and batch operations. Status updates below; no completion messages in chat.")

    try:
        services = init_services()
        if not services:
            st.warning("Could not connect to services.")
            return
    except Exception:
        st.warning("Could not connect to services.")
        return

    # Trigger embedding backfill every 5 min (run in thread so tab stays responsive)
    BACKFILL_INTERVAL_SEC = 300
    key_last_backfill = "bg_tasks_last_embedding_backfill"
    if key_last_backfill not in st.session_state:
        st.session_state[key_last_backfill] = time.time()
    if time.time() - st.session_state[key_last_backfill] >= BACKFILL_INTERVAL_SEC:
        st.session_state[key_last_backfill] = time.time()
        pid = project_id

        def _do_backfill():
            try:
                run_embedding_backfill(pid, bible_limit=200, chunks_limit=200)
            except Exception:
                pass

        t = threading.Thread(target=_do_backfill, daemon=True)
        t.start()

    @st.fragment(run_every=timedelta(seconds=30))
    def _jobs_list():
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

    _jobs_list()
