import time
import streamlit as st

from config import Config, init_services, CostManager
from persona import PersonaSystem
from utils.auth_manager import get_user_projects


def render_sidebar(session_manager):
    """Sidebar: Project, Arc, Quick Actions. Không còn navigation - chuyển sang main tabs."""
    with st.sidebar:
        st.markdown("🚀 **V-Universe Ver 6.0**", unsafe_allow_html=True)
        if 'user' in st.session_state and st.session_state.user:
            user_email = st.session_state.user.email
            st.markdown(f"_{user_email.split('@')[0]}_", unsafe_allow_html=True)

            budget = CostManager.get_user_budget(st.session_state.user.id)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("💰 Credits", f"${budget.get('remaining_credits', 0):.2f}")
            with col2:
                usage_percent = (budget.get('used_credits', 0) / max(budget.get('total_credits', 100), 1)) * 100
                st.metric("Usage", f"{usage_percent:.1f}%")
            st.markdown("---")

        st.subheader("📂 Projects")
        services = init_services()
        supabase = services['supabase']

        if 'user' in st.session_state and st.session_state.user:
            projects = get_user_projects(st.session_state.user.id, st.session_state.user.email)
        else:
            projects = []

        proj_id = None
        persona = PersonaSystem.PERSONAS["Writer"]

        if projects:
            labels = []
            for p in projects:
                title = p.get("title") or "Untitled"
                role = p.get("role") or "owner"
                if role == "owner":
                    labels.append(title)
                else:
                    labels.append(f"{title} (Shared)")
            idx = st.selectbox(
                "Select Project",
                range(len(projects)),
                format_func=lambda i: labels[i] if i < len(labels) else "",
                key="project_selector"
            )
            current_proj = projects[idx]
            proj_id = current_proj["id"]
            proj_type = current_proj.get("category", "Writer")

            st.session_state["current_project"] = current_proj
            st.session_state["project_id"] = proj_id
            st.session_state["persona"] = proj_type

            persona = PersonaSystem.get_persona(proj_type)
            st.info(f"{persona['icon']} **{proj_type}**")

            try:
                from core.arc_service import ArcService
                arcs = ArcService.list_arcs(proj_id, status="active")
                if arcs:
                    arc_options = ["(Không)"] + [a.get("name") or str(a.get("id", ""))[:8] for a in arcs]
                    arc_idx = st.selectbox(
                        "📐 Arc",
                        range(len(arc_options)),
                        format_func=lambda i: arc_options[i] if i < len(arc_options) else "",
                        key="arc_selector",
                        help="Thu hẹp context Chat theo Arc (timeline). Chunking import gán arc mặc định."
                    )
                    if arc_idx and arc_idx > 0 and arc_idx <= len(arcs):
                        st.session_state["current_arc_id"] = arcs[arc_idx - 1].get("id")
                    else:
                        st.session_state["current_arc_id"] = None
                else:
                    st.session_state["current_arc_id"] = None
            except Exception:
                st.session_state["current_arc_id"] = None

        st.markdown("---")
        if st.button("Create New Project", type="primary"):
            st.session_state['show_new_project'] = True

        if st.session_state.get('show_new_project'):
            with st.form("new_project_form"):
                title = st.text_input("Project Name")
                if st.form_submit_button("Create"):
                    if title:
                        supabase.table("stories").insert({
                            "title": title,
                            "category": "Writer",
                            "user_id": st.session_state.user.id
                        }).execute()
                        st.success("Project created!")
                        st.session_state['show_new_project'] = False
                        st.rerun()

        st.markdown("---")
        st.subheader("⚡ Quick Actions")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            st.session_state['logging_out'] = True
            try:
                session_manager.cookie_manager.delete("supabase_access_token", key="del_access_logout")
                session_manager.cookie_manager.delete("supabase_refresh_token", key="del_refresh_logout")
            except Exception:
                pass
            for key in list(st.session_state.keys()):
                if key != 'logging_out':
                    del st.session_state[key]
            st.success("Logged out!")
            time.sleep(1)
            st.rerun()

        return proj_id, persona
