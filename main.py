"""
V-Universe AI Hub Pro Ver 6.0 - Entry point.
Main tabs: Workspace | Knowledge | Chat | Admin. Sub-tabs trong từng nhóm.
"""
import streamlit as st
import time

from config import Config, init_services, SessionManager, CostManager
from views import (
    render_sidebar,
    render_dashboard_tab,
    render_chat_tab,
    render_workstation_tab,
    render_data_analyze_tab,
    render_review_tab,
    render_bible_tab,
    render_cost_tab,
    render_settings_tab,
    render_collaboration_tab,
    render_data_health_tab,
    render_rules_tab,
    render_chat_management_tab,
    render_relations_tab,
    render_chunking_tab,
    render_python_executor_tab,
    render_arc_tab,
    render_semantic_intent_tab,
)

# ==========================================
# PAGE CONFIG & CSS
# ==========================================
st.set_page_config(
    page_title="V-Universe AI Hub Pro Ver 6.0",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main .block-container { padding-top: 1.25rem; padding-bottom: 1.25rem; max-width: 1400px; }
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white; border: none; border-radius: 10px; transition: opacity 0.2s;
    }
    [data-testid="stSidebar"] .stButton > button:hover { opacity: 0.9; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: #f1f5f9; padding: 10px; border-radius: 12px; }
    .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 8px; }
    .danger-zone { border: 2px solid #ef4444; border-radius: 12px; padding: 16px; margin-top: 16px; background: #fef2f2; }
    .stExpander { border-radius: 10px; border: 1px solid #e2e8f0; }
    .stExpander summary { font-weight: 600; }
    div[data-testid="stHorizontalBlock"] > div { padding: 0 0.4rem; }
    .stSubheader, h3 { color: #334155; }
    .dashboard-widget { background: #f8fafc; border-radius: 12px; padding: 16px; border: 1px solid #e2e8f0; }
    .widget-value { font-size: 1.75rem; font-weight: 700; color: #334155; }
    .widget-title { font-size: 0.9rem; color: #64748b; }
</style>
""", unsafe_allow_html=True)

# Sub-tabs mapping: main_tab -> [(sub_id, label, render_fn, needs_persona)]
TAB_STRUCTURE = {
    "workspace": [
        ("dashboard", "📊 Dashboard", "render_dashboard_tab", False),
        ("workstation", "✍️ Workstation", "render_workstation_tab", True),
        ("data_analyze", "📊 Data Analyze", "render_data_analyze_tab", False),
        ("review", "🤖 Review", "render_review_tab", False),
        ("python_executor", "🧮 Python Executor", "render_python_executor_tab", False),
    ],
    "knowledge": [
        ("bible", "📖 Bible", "render_bible_tab", True),
        ("relations", "🔗 Relations", "render_relations_tab", True),
        ("chunking", "✂️ Chunking", "render_chunking_tab", False),
        ("rules", "📋 Rules", "render_rules_tab", True),
        ("chat_mgmt", "💬 Memory", "render_chat_management_tab", True),
        ("arc", "📐 Arc", "render_arc_tab", False),
        ("data_health", "🛡️ Data Health", "render_data_health_tab", False),
        ("semantic_intent", "🎯 Semantic Intent", "render_semantic_intent_tab", False),
    ],
    "chat": [
        ("chat", "💬 Smart Chat", "render_chat_tab", True),
    ],
    "admin": [
        ("collaboration", "👥 Collaboration", "render_collaboration_tab", False),
        ("cost", "💰 Cost", "render_cost_tab", False),
        ("settings", "⚙️ Settings", "render_settings_tab", False),
    ],
}

RENDER_MAP = {
    "render_dashboard_tab": render_dashboard_tab,
    "render_workstation_tab": render_workstation_tab,
    "render_data_analyze_tab": render_data_analyze_tab,
    "render_review_tab": render_review_tab,
    "render_python_executor_tab": render_python_executor_tab,
    "render_bible_tab": render_bible_tab,
    "render_rules_tab": render_rules_tab,
    "render_chat_management_tab": render_chat_management_tab,
    "render_relations_tab": render_relations_tab,
    "render_chunking_tab": render_chunking_tab,
    "render_arc_tab": render_arc_tab,
    "render_data_health_tab": render_data_health_tab,
    "render_semantic_intent_tab": render_semantic_intent_tab,
    "render_chat_tab": render_chat_tab,
    "render_collaboration_tab": render_collaboration_tab,
    "render_cost_tab": render_cost_tab,
    "render_settings_tab": render_settings_tab,
}


def main():
    session_manager = SessionManager()

    if st.session_state.get('logging_out'):
        del st.session_state['logging_out']
        session_manager.render_login_form()
        return

    if not session_manager.check_login():
        time.sleep(1)
        session_manager.render_login_form()
        return

    if not Config.validate():
        st.stop()

    services = init_services()
    if not services:
        st.error("Failed to initialize services.")
        st.stop()

    project_id, persona = render_sidebar(session_manager)

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.get('current_project'):
            st.title(f"🚀 {st.session_state.current_project.get('title', 'Untitled')}")
        else:
            st.title("🚀 V-Universe AI Hub Pro Ver 6.0")
            st.caption("Select or create a project")
    with col2:
        if 'user' in st.session_state:
            budget = CostManager.get_user_budget(st.session_state.user.id)
            st.metric("Credits", f"${budget.get('remaining_credits', 0):.2f}")

    # Main tabs
    main_tab = st.tabs(["📂 Workspace", "📚 Knowledge", "💬 Chat", "⚙️ Admin"])

    for idx, (tab_name, tab_container) in enumerate(zip(
        ["workspace", "knowledge", "chat", "admin"],
        main_tab
    )):
        with tab_container:
            subs = TAB_STRUCTURE.get(tab_name, [])
            if len(subs) == 1:
                sub_id, _, fn_name, needs_persona = subs[0]
                render_fn = RENDER_MAP.get(fn_name)
                if render_fn:
                    try:
                        if needs_persona:
                            render_fn(project_id, persona)
                        elif sub_id in ("cost", "settings"):
                            render_fn()
                        else:
                            render_fn(project_id)
                    except TypeError:
                        render_fn(project_id) if sub_id not in ("cost", "settings") else render_fn()
            else:
                sub_labels = [s[1] for s in subs]
                sub_tabs = st.tabs(sub_labels)
                for j, (sub_id, _, fn_name, needs_persona) in enumerate(subs):
                    with sub_tabs[j]:
                        render_fn = RENDER_MAP.get(fn_name)
                        if render_fn:
                            try:
                                if needs_persona:
                                    render_fn(project_id, persona)
                                elif sub_id in ("cost", "settings"):
                                    render_fn()
                                else:
                                    render_fn(project_id)
                            except TypeError:
                                render_fn(project_id) if sub_id not in ("cost", "settings") else render_fn()

    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666; padding: 20px;'>"
        "🚀 V-Universe AI Hub Pro • Ver 6.0 • Semantic Intent • Arc • Chunking • Auto Crystallize"
        "</div>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
