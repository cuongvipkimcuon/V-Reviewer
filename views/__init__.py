# views - UI render functions
from .sidebar import render_sidebar
from .dashboard import render_dashboard_tab

try:
    from .chat import render_chat_tab
except Exception as e:
    def render_chat_tab(project_id, persona):
        import streamlit as st
        st.error("Chat tab failed to load: %s" % (e,))
    render_chat_tab.__module__ = "views"

from .workstation import render_workstation_tab
from .bible import render_bible_tab
from .cost import render_cost_tab
from .settings import render_settings_tab
from .collaboration import render_collaboration_tab
from .setup_tabs import render_prefix_setup, render_persona_setup
from .data_health import render_data_health_tab
from .data_analyze import render_data_analyze_tab
from .background_tasks_tab import render_background_tasks_tab
from .review import render_review_tab

try:
    from .rules_view import render_rules_tab
except ImportError:
    def render_rules_tab(project_id, persona):
        import streamlit as st
        st.warning("Rules view failed to load. Check views/rules_view.py")
    render_rules_tab.__module__ = "views"

try:
    from .chat_management_view import render_chat_management_tab
except ImportError:
    def render_chat_management_tab(project_id, persona):
        import streamlit as st
        st.warning("Chat management view failed to load.")
    render_chat_management_tab.__module__ = "views"

try:
    from .relations_view import render_relations_tab
except ImportError:
    def render_relations_tab(project_id, persona):
        import streamlit as st
        st.warning("Relations view failed to load.")
    render_relations_tab.__module__ = "views"

try:
    from .chunking_view import render_chunking_tab
except ImportError:
    def render_chunking_tab(project_id):
        import streamlit as st
        st.warning("Chunking view failed to load.")
    render_chunking_tab.__module__ = "views"

try:
    from .python_executor_view import render_python_executor_tab
except ImportError:
    def render_python_executor_tab(project_id):
        import streamlit as st
        st.warning("Python Executor view failed to load.")
    render_python_executor_tab.__module__ = "views"

try:
    from .arc_view import render_arc_tab
except ImportError:
    def render_arc_tab(project_id):
        import streamlit as st
        st.warning("Arc view failed to load.")
    render_arc_tab.__module__ = "views"

try:
    from .semantic_intent_view import render_semantic_intent_tab
except ImportError:
    def render_semantic_intent_tab(project_id):
        import streamlit as st
        st.warning("Semantic Intent view failed to load.")
    render_semantic_intent_tab.__module__ = "views"

try:
    from .timeline_view import render_timeline_tab
except ImportError:
    def render_timeline_tab(project_id):
        import streamlit as st
        st.warning("Timeline view failed to load.")
    render_timeline_tab.__module__ = "views"

try:
    from .commands_tab import render_commands_tab
except ImportError:
    def render_commands_tab(project_id, persona=None):
        import streamlit as st
        st.warning("Commands tab failed to load.")
    render_commands_tab.__module__ = "views"

__all__ = [
    "render_sidebar",
    "render_dashboard_tab",
    "render_chat_tab",
    "render_workstation_tab",
    "render_bible_tab",
    "render_cost_tab",
    "render_settings_tab",
    "render_collaboration_tab",
    "render_prefix_setup",
    "render_persona_setup",
    "render_data_health_tab",
    "render_data_analyze_tab",
    "render_background_tasks_tab",
    "render_review_tab",
    "render_rules_tab",
    "render_chat_management_tab",
    "render_relations_tab",
    "render_chunking_tab",
    "render_python_executor_tab",
    "render_arc_tab",
    "render_semantic_intent_tab",
    "render_timeline_tab",
    "render_commands_tab",
]
