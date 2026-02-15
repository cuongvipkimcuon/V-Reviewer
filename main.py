"""
V-Universe AI Hub Pro Ver 7.0 - Entry point.
Tối ưu: lazy import view, chỉ render 1 tab đang chọn, cache sidebar/cost.
"""
import importlib
import streamlit as st
import time

from config import Config, init_services, SessionManager
from utils.cache_helpers import get_user_budget_cached
from views.sidebar import render_sidebar

# ==========================================
# PAGE CONFIG & CSS
# ==========================================
st.set_page_config(
    page_title="V-Universe AI Hub Pro Ver 7.0",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main .block-container { padding-top: 1.25rem; padding-bottom: 1.25rem; max-width: 1400px; }
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #6d28d9 0%, #7c3aed 100%);
        color: white; border: none; border-radius: 8px; font-weight: 500; transition: opacity 0.2s, transform 0.05s;
    }
    [data-testid="stSidebar"] .stButton > button:hover { opacity: 0.92; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; background: #f8fafc; padding: 8px; border-radius: 10px; }
    .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #6d28d9 0%, #7c3aed 100%); color: white; border-radius: 8px; }
    .danger-zone { border: 1px solid #fecaca; border-radius: 10px; padding: 16px; margin-top: 16px; background: #fef2f2; }
    .stExpander { border-radius: 8px; border: 1px solid #e2e8f0; }
    .stExpander summary { font-weight: 600; }
    div[data-testid="stHorizontalBlock"] > div { padding: 0 0.4rem; }
    .stSubheader, h3 { color: #334155; }
    .dashboard-widget { background: #fff; border-radius: 10px; padding: 16px; border: 1px solid #e2e8f0; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
    .widget-value { font-size: 1.75rem; font-weight: 700; color: #334155; }
    .widget-title { font-size: 0.9rem; color: #64748b; }
    [data-testid="stTextInput"] input, [data-testid="stTextInput"] input:focus { border-radius: 8px; border-color: #e2e8f0; }
    [data-testid="stTextInput"] input:focus { box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.2); border-color: #7c3aed; }
    .stButton > button { border-radius: 8px; font-weight: 500; transition: opacity 0.2s; }
    .stButton > button:hover { opacity: 0.9; }
    /* Khung tab chính: ô trên = ghi chú, ô dưới = nút (nối liền) */
    .tab-main-frame { border: 2px solid #5b21b6; border-bottom: none; border-radius: 14px 14px 0 0; padding: 10px 16px 8px; background: linear-gradient(135deg, #3b0764 0%, #4c1d95 50%, #6d28d9 100%); box-shadow: 0 4px 14px rgba(91,33,182,0.25); }
    .tab-main-frame .tab-label { color: rgba(255,255,255,0.92); font-size: 0.8rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
    #main-tab-row + div { gap: 12px !important; padding: 12px 16px 14px !important; flex-wrap: wrap !important; border: 2px solid #5b21b6; border-top: none !important; border-radius: 0 0 14px 14px; background: linear-gradient(180deg, rgba(109,40,217,0.12) 0%, rgba(91,33,182,0.08) 100%); margin-bottom: 22px !important; }
    #main-tab-row + div .stButton > button { border-radius: 12px !important; font-weight: 700 !important; font-size: 1.12rem !important; transition: all 0.2s !important; padding: 0.7rem 1.4rem !important; min-height: 48px !important; }
    #main-tab-row + div .stButton > button[kind="primary"] { background: white !important; color: #5b21b6 !important; border: none !important; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }
    #main-tab-row + div .stButton > button[kind="secondary"] { background: rgba(255,255,255,0.18) !important; color: rgba(255,255,255,0.98) !important; border: 2px solid rgba(255,255,255,0.5) !important; }
    #main-tab-row + div .stButton > button[kind="secondary"]:hover { background: rgba(255,255,255,0.3) !important; color: white !important; border-color: rgba(255,255,255,0.7) !important; }
    /* Khung tab phụ: ô ghi chú riêng */
    .tab-sub-frame { border: 1px solid #cbd5e1; border-radius: 12px; padding: 8px 14px; margin-bottom: 8px; background: #f1f5f9; }
    .tab-sub-frame .tab-label { color: #64748b; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em; }
    /* Tab phụ: nhỏ hơn, màu xanh slate, tối đa 4/hàng */
    .sub-tab-row-marker + div { gap: 8px !important; padding: 10px 14px !important; margin-bottom: 8px !important; flex-wrap: wrap !important; background: #f8fafc !important; border-radius: 10px !important; border: 1px solid #e2e8f0 !important; }
    .sub-tab-row-marker + div .stButton > button { border-radius: 8px !important; font-weight: 500 !important; font-size: 0.875rem !important; transition: all 0.2s !important; }
    .sub-tab-row-marker + div .stButton > button[kind="primary"] { background: linear-gradient(135deg, #0f766e 0%, #0d9488 100%) !important; color: white !important; border: none !important; box-shadow: 0 1px 3px rgba(13,148,136,0.35); }
    .sub-tab-row-marker + div .stButton > button[kind="secondary"] { background: white !important; color: #475569 !important; border: 1px solid #e2e8f0 !important; }
    .sub-tab-row-marker + div .stButton > button[kind="secondary"]:hover { background: #f1f5f9 !important; border-color: #0d9488 !important; color: #0f766e !important; }
</style>
""", unsafe_allow_html=True)

# Sub-tabs mapping: main_tab -> [(sub_id, label, render_fn, needs_persona)]
TAB_STRUCTURE = {
    "workspace": [
        ("dashboard", "📊 Dashboard", "render_dashboard_tab", False),
        ("workstation", "✍️ Workstation", "render_workstation_tab", True),
        ("data_analyze", "📊 Data Analyze", "render_data_analyze_tab", False),
        ("background_tasks", "🔄 Background Jobs", "render_background_tasks_tab", False),
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
        ("timeline", "📅 Timeline", "render_timeline_tab", False),
        ("commands", "📌 Chỉ lệnh", "render_commands_tab", True),
        ("data_health", "🛡️ Data Health", "render_data_health_tab", False),
        ("semantic_intent", "🎯 Semantic Intent", "render_semantic_intent_tab", False),
    ],
    "chat": [
        ("v_work", "🔧 V Work", "render_chat_tab", True),
        ("v_home", "🏠 V Home", "render_chat_tab", False),
    ],
    "admin": [
        ("collaboration", "👥 Collaboration", "render_collaboration_tab", False),
        ("cost", "💰 Cost", "render_cost_tab", False),
        ("settings", "⚙️ Settings", "render_settings_tab", False),
    ],
}

# Lazy load: chỉ import view khi cần (giảm lag mỗi run)
VIEW_MODULES = {
    "render_dashboard_tab": "views.dashboard",
    "render_workstation_tab": "views.workstation",
    "render_data_analyze_tab": "views.data_analyze",
    "render_background_tasks_tab": "views.background_tasks_tab",
    "render_review_tab": "views.review",
    "render_python_executor_tab": "views.python_executor_view",
    "render_bible_tab": "views.bible",
    "render_rules_tab": "views.rules_view",
    "render_chat_management_tab": "views.chat_management_view",
    "render_relations_tab": "views.relations_view",
    "render_chunking_tab": "views.chunking_view",
    "render_arc_tab": "views.arc_view",
    "render_timeline_tab": "views.timeline_view",
    "render_commands_tab": "views.commands_tab",
    "render_data_health_tab": "views.data_health",
    "render_semantic_intent_tab": "views.semantic_intent_view",
    "render_chat_tab": "views.chat",
    "render_collaboration_tab": "views.collaboration",
    "render_cost_tab": "views.cost",
    "render_settings_tab": "views.settings",
}


def _get_render_fn(fn_name):
    """Import view module khi cần, trả về hàm render."""
    if fn_name not in VIEW_MODULES:
        return None
    mod = importlib.import_module(VIEW_MODULES[fn_name])
    return getattr(mod, fn_name, None)


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

    # Header (tiêu đề căn giữa)
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.get('current_project'):
            st.markdown(
                f"<h1 style='text-align: center; margin: 0; font-size: 1.75rem; font-weight: 600; color: #334155;'>{st.session_state.current_project.get('title', 'Untitled')}</h1>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                "<h1 style='text-align: center; margin: 0; font-size: 1.75rem; font-weight: 600; background: linear-gradient(135deg, #5b21b6 0%, #7c3aed 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;'>V-Universe AI Hub Pro Ver 7.0</h1>",
                unsafe_allow_html=True
            )
            st.markdown("<p style='text-align: center; color: #64748b; margin-top: 0.25rem; font-size: 0.95rem;'>Select or create a project</p>", unsafe_allow_html=True)
    with col2:
        if 'user' in st.session_state:
            _trigger = st.session_state.get("update_trigger", 0)
            budget = get_user_budget_cached(st.session_state.user.id, _trigger)
            st.metric("Credits", f"${budget.get('remaining_credits', 0):.2f}")

    # Tab đẹp: 2 hàng nút (main + sub), chỉ render 1 tab đang chọn
    main_labels = ["📂 Workspace", "📚 Knowledge", "💬 Chat", "⚙️ Admin"]
    main_keys = ["workspace", "knowledge", "chat", "admin"]
    st.session_state.setdefault("main_tab_idx", 0)
    main_idx = max(0, min(st.session_state["main_tab_idx"], len(main_keys) - 1))

    st.markdown(
        '<div class="tab-main-frame"><span class="tab-label">Tab chính — Chọn nhóm</span></div><div id="main-tab-row"></div>',
        unsafe_allow_html=True
    )
    cols_main = st.columns(len(main_labels))
    for i, (col, label) in enumerate(zip(cols_main, main_labels)):
        with col:
            if st.button(label, key="main_tab_%d" % i, type="primary" if main_idx == i else "secondary", use_container_width=True):
                st.session_state["main_tab_idx"] = i
                if "sub_tab_idx_%s" % main_keys[i] not in st.session_state:
                    st.session_state["sub_tab_idx_%s" % main_keys[i]] = 0
                st.rerun()

    main_tab_key = main_keys[main_idx]
    subs = TAB_STRUCTURE.get(main_tab_key, [])
    if not subs:
        st.info("Chọn tab ở trên.")
    else:
        sub_labels = [s[1] for s in subs]
        sub_key = "sub_tab_idx_%s" % main_tab_key
        st.session_state.setdefault(sub_key, 0)
        sub_idx = max(0, min(st.session_state[sub_key], len(subs) - 1))

        st.markdown(
            '<div class="tab-sub-frame"><span class="tab-label">Tab phụ — Chọn tính năng</span></div><div id="sub-tab-row"></div>',
            unsafe_allow_html=True
        )
        TABS_PER_ROW = 4
        for row_start in range(0, len(sub_labels), TABS_PER_ROW):
            st.markdown('<div class="sub-tab-row-marker"></div>', unsafe_allow_html=True)
            cols_sub = st.columns(TABS_PER_ROW)
            for j in range(TABS_PER_ROW):
                i = row_start + j
                if i >= len(sub_labels):
                    with cols_sub[j]:
                        st.write("")
                    continue
                with cols_sub[j]:
                    label = sub_labels[i]
                    if st.button(label, key="sub_%s_%d" % (main_tab_key, i), type="primary" if sub_idx == i else "secondary", use_container_width=True):
                        st.session_state[sub_key] = i
                        st.rerun()

        sub_id, _, fn_name, needs_persona = subs[sub_idx]
        render_fn = _get_render_fn(fn_name)
        if render_fn:
            try:
                if sub_id in ("v_work", "v_home"):
                    render_fn(project_id, persona, sub_id)
                elif needs_persona:
                    render_fn(project_id, persona)
                elif sub_id in ("cost", "settings"):
                    render_fn()
                else:
                    render_fn(project_id)
            except TypeError:
                try:
                    if sub_id in ("v_work", "v_home"):
                        render_fn(project_id, persona, sub_id)
                    elif sub_id in ("cost", "settings"):
                        render_fn()
                    else:
                        render_fn(project_id)
                except TypeError:
                    render_fn(project_id)

    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #64748b; padding: 16px; font-size: 0.85rem;'>"
        "V-Universe AI Hub Pro • Ver 7.0 • Semantic Intent • Arc • Chunking • Chỉ lệnh @@ • Auto Crystallize"
        "</div>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
