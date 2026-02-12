# config.py - Cấu hình hệ thống, session, và cost
import streamlit as st
import time
from datetime import datetime
from openai import OpenAI
from supabase import create_client
import extra_streamlit_components as stx


# ==========================================
# 🔧 CẤU HÌNH HỆ THỐNG
# ==========================================
class Config:
    """Lớp quản lý cấu hình hệ thống"""

    # OpenRouter API Configuration
    OPENROUTER_API_KEY = st.secrets.get("openrouter", {}).get("API_KEY", "")
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # Supabase Configuration
    SUPABASE_URL = st.secrets.get("supabase", {}).get("SUPABASE_URL", "")
    SUPABASE_KEY = st.secrets.get("supabase", {}).get("SUPABASE_KEY", "")

    # Available Models (Đầy đủ các model phổ biến)
    AVAILABLE_MODELS = {
        "🚀 High Performance": [
            "anthropic/claude-opus-4.5",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-3-pro-preview"
        ],
        "⚡ Fast & Balanced": [
            "anthropic/claude-haiku-4.5",
            "google/gemini-3-flash-preview",
            "mistralai/devstral-2512"
        ],
        "💰 Cost Effective": [
            "deepseek/deepseek-v3.2",
            "qwen/qwen3-vl-32b-instruct",
            "meta-llama/llama-4-maverick",
            "google/gemini-2.5-flash",
            "anthropic/claude-3.5-haiku"
        ],
        "🔬 Specialized": [
            "cohere/command-a",
            "perplexity/sonar",
            "nousresearch/hermes-4-405b",
            "meta-llama/llama-3.2-11b-vision-instruct"
        ]
    }

    # Model Costs (USD per 1M tokens)
    MODEL_COSTS = {
        "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
        "anthropic/claude-opus-4.5": {"input": 5.00, "output": 25.00},
        "anthropic/claude-sonnet-4.5": {"input": 3.00, "output": 15.00},
        "anthropic/claude-haiku-4.5": {"input": 1.00, "output": 5.00},
        "anthropic/claude-3.5-haiku": {"input": 0.80, "output": 4.00},
        "google/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
        "google/gemini-3-flash-preview": {"input": 0.5, "output": 3.00},
        "google/gemini-2.5-flash": {"input": 0.3, "output": 2.50},
        "deepseek/deepseek-v3.2": {"input": 0.25, "output": 0.38},
        "qwen/qwen3-vl-32b-instruct": {"input": 0.50, "output": 1.50},
        "mistralai/devstral-2512": {"input": 0.05, "output": 0.22},
        "meta-llama/llama-4-maverick": {"input": 0.15, "output": 0.60},
        "cohere/command-a": {"input": 2.50, "output": 10.00},
        "perplexity/sonar": {"input": 1.00, "output": 1.00},
        "nousresearch/hermes-4-405b": {"input": 1.00, "output": 3.00},
        "meta-llama/llama-3.2-11b-vision-instruct": {"input": 0.049, "output": 0.049},
    }

    # Default settings
    DEFAULT_MODEL = "anthropic/claude-3.5-haiku"
    EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"
    ROUTER_MODEL = "deepseek/deepseek-v3.2"
    # Model rẻ cho auto-summary / metadata (Workstation)
    METADATA_MODEL = "google/gemini-2.5-flash"

    # Bible prefixes mặc định (fallback khi không lấy được từ DB)
    BIBLE_PREFIXES = [
        "[RULE]",
        "[CHARACTER]",
        "[LOCATION]",
        "[CONCEPT]",
        "[ITEM]",
        "[EVENT]",
        "[SYSTEM]",
        "[LORE]",
        "[TECH]",
        "[META]",
        "[CHAT]",
    ]

    @classmethod
    def get_prefixes(cls) -> list:
        """Lấy danh sách prefix dạng [X]: ưu tiên bảng bible_prefix_config, fallback settings, rồi BIBLE_PREFIXES."""
        try:
            setup = cls.get_prefix_setup()
            if setup:
                return [f"[{p.get('prefix_key', '')}]" for p in setup if p.get('prefix_key')]
        except Exception:
            pass
        try:
            services = init_services()
            if services:
                res = services["supabase"].table("settings").select("value").eq("key", "bible_prefixes").execute()
                if res.data and len(res.data) > 0:
                    val = res.data[0].get("value")
                    if isinstance(val, list) and len(val) > 0:
                        return [str(p) for p in val]
        except Exception:
            pass
        return list(cls.BIBLE_PREFIXES)

    @classmethod
    def get_prefix_setup(cls) -> list:
        """Lấy bảng Setup Tiền tố: list of {prefix_key, description, sort_order}. Dùng cho Router và Extract. Defensive: lỗi trả về [] hoặc fallback 2 dòng rule/chat."""
        try:
            services = init_services()
            if not services:
                return [{"prefix_key": "RULE", "description": "Quy tắc, luật lệ.", "sort_order": 1}, {"prefix_key": "CHAT", "description": "Điểm nhớ từ hội thoại.", "sort_order": 2}]
            try:
                r = services["supabase"].table("entity_setup").select("prefix_key, description, sort_order").order("sort_order").execute()
            except Exception:
                r = services["supabase"].table("bible_prefix_config").select("prefix_key, description, sort_order").order("sort_order").execute()
            if r.data and len(r.data) > 0:
                return [{"prefix_key": x.get("prefix_key", ""), "description": x.get("description", ""), "sort_order": x.get("sort_order", 0)} for x in r.data]
        except Exception:
            pass
        return [{"prefix_key": "RULE", "description": "Quy tắc, luật lệ.", "sort_order": 1}, {"prefix_key": "CHAT", "description": "Điểm nhớ từ hội thoại.", "sort_order": 2}]

    @classmethod
    def map_extract_type_to_prefix(cls, item_type: str, item_description: str = "") -> str:
        """Ánh xạ type/description từ Extract sang prefix trong bảng; loại trừ RULE, CHAT; không khớp trả về OTHER."""
        try:
            setup = cls.get_prefix_setup()
            allowed = [p for p in setup if p.get("prefix_key") and str(p.get("prefix_key", "")).upper() not in ("RULE", "CHAT")]
            if not allowed:
                return "OTHER"
            key_candidate = (item_type or "").strip().upper().replace(" ", "_")
            combined = f"{(item_type or '')} {(item_description or '')}".strip().lower()
            for p in allowed:
                pk = (p.get("prefix_key") or "").strip().upper()
                if key_candidate == pk:
                    return pk
            for p in allowed:
                pk = (p.get("prefix_key") or "").strip().upper()
                desc_lower = (p.get("description") or "").lower()
                if key_candidate and key_candidate in desc_lower:
                    return pk
                if desc_lower and desc_lower in combined:
                    return pk
                if key_candidate and pk in key_candidate:
                    return pk
            return "OTHER"
        except Exception:
            return "OTHER"

    # Cache settings
    CACHE_TTL_HOURS = 24
    MAX_CONTEXT_TOKENS = {
        "low": 15000,
        "medium": 30000,
        "high": 60000,
        "max": 120000
    }

    @classmethod
    def validate(cls):
        """Validate configuration"""
        errors = []
        if not cls.OPENROUTER_API_KEY:
            errors.append("❌ OpenRouter API key not found in secrets")
        if not cls.SUPABASE_URL or not cls.SUPABASE_KEY:
            errors.append("❌ Supabase credentials not found in secrets")

        if errors:
            for error in errors:
                st.error(error)
            return False
        return True


# ==========================================
# 🔗 KHỞI TẠO DỊCH VỤ
# ==========================================
@st.cache_resource
def init_services():
    """Khởi tạo kết nối đến các dịch vụ"""
    try:
        openai_client = OpenAI(
            base_url=Config.OPENROUTER_BASE_URL,
            api_key=Config.OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": "https://v-universe.streamlit.app",
                "X-Title": "V-Universe AI Hub"
            }
        )
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        supabase.table("stories").select("count", count="exact").limit(1).execute()
        return {
            "openai": openai_client,
            "supabase": supabase
        }
    except Exception as e:
        st.error(f"❌ Failed to initialize services: {str(e)}")
        return None


# ==========================================
# 🍪 QUẢN LÝ PHIÊN & AUTH
# ==========================================
class SessionManager:
    """Quản lý session và authentication"""

    def __init__(self):
        self.cookie_manager = stx.CookieManager(key="v_universe_cookies")

    def initialize_session(self):
        """Khởi tạo session state"""
        if 'initialized' not in st.session_state:
            st.session_state.update({
                'initialized': True,
                'user': None,
                'current_project': None,
                'project_id': None,
                'chat_messages': [],
                'selected_model': Config.DEFAULT_MODEL,
                'temperature': 0.7,
                'context_size': 'medium',
                'persona': 'Writer',
                'current_file_content': '',
                'current_file_review': '',
                'current_file_num': 1,
                'chat_cutoff': "1970-01-01",
                'strict_mode': False,
                'enable_history': True,
                'chat_crystallized_summary': None,
                'chat_crystallized_topic': None,
                'pending_new_rule': None,
                'rule_analysis': None,
                'edit_rule_manual': None,
                'current_arc_id': None,
            })

    def check_login(self):
        """Kiểm tra và quản lý đăng nhập"""
        self.initialize_session()

        if st.session_state.get('logging_out'):
            return False

        if 'user' in st.session_state and st.session_state.user:
            return True

        access_token = self.cookie_manager.get("supabase_access_token")
        refresh_token = self.cookie_manager.get("supabase_refresh_token")

        if access_token and refresh_token:
            try:
                services = init_services()
                if services:
                    session = services['supabase'].auth.set_session(access_token, refresh_token)
                    if session and session.user:
                        st.session_state.user = session.user
                        st.rerun()
            except Exception:
                self.cookie_manager.delete("supabase_access_token", key="del_access_check_login")
                self.cookie_manager.delete("supabase_refresh_token", key="del_refresh_check_login")
                return False

        return False

    def render_login_form(self):
        """Hiển thị form đăng nhập/đăng ký - Ver 6.0"""
        st.markdown("""
        <style>
        .login-hero { text-align: center; padding: 2rem 0; }
        .login-hero h1 { font-size: 2.8rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .feature-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 2rem 0; }
        .feature-card { background: linear-gradient(145deg, #f8fafc 0%, #e2e8f0 100%); border-radius: 16px; padding: 24px; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.08); transition: transform 0.2s; }
        .feature-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(102,126,234,0.2); }
        .feature-card .icon { font-size: 2.5rem; margin-bottom: 12px; }
        .feature-card h4 { color: #2d3748; font-size: 1rem; margin: 0 0 8px 0; }
        .feature-card p { color: #64748b; font-size: 0.85rem; margin: 0; }
        </style>
        """, unsafe_allow_html=True)

        st.markdown('<div class="login-hero">', unsafe_allow_html=True)
        st.markdown("<h1>🚀 V-Universe AI Hub Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b; font-size: 1.1rem;'>Ver 6.0 — Your Intelligent Writing & Development Assistant</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 3, 1])

        with col2:
            with st.container():
                st.markdown("<div class='card'>", unsafe_allow_html=True)

                tab_login, tab_register = st.tabs(["🔐 Đăng nhập", "📝 Đăng ký"])

                with tab_login:
                    st.subheader("Welcome Back")

                    email = st.text_input("📧 Email", key="login_email")
                    password = st.text_input("🔑 Password", type="password", key="login_pass")

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button("Login", type="primary", use_container_width=True):
                            if email and password:
                                try:
                                    services = init_services()
                                    res = services['supabase'].auth.sign_in_with_password({
                                        "email": email,
                                        "password": password
                                    })

                                    st.session_state.user = res.user

                                    self.cookie_manager.set(
                                        "supabase_access_token",
                                        res.session.access_token,
                                        key="login_access"
                                    )
                                    self.cookie_manager.set(
                                        "supabase_refresh_token",
                                        res.session.refresh_token,
                                        key="login_refresh"
                                    )

                                    st.success("✅ Login successful!")
                                    time.sleep(1.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Login failed: {str(e)}")

                    with col_btn2:
                        if st.button("Forgot Password?", use_container_width=True):
                            if email:
                                try:
                                    services = init_services()
                                    services['supabase'].auth.reset_password_email(email)
                                    st.success("📧 Password reset email sent!")
                                except Exception:
                                    st.error("Failed to send reset email")

                with tab_register:
                    st.subheader("Create Account")

                    reg_email = st.text_input("📧 Email", key="reg_email")
                    reg_pass = st.text_input("🔑 Password", type="password", key="reg_pass")
                    reg_pass_confirm = st.text_input("🔑 Confirm Password", type="password", key="reg_pass_confirm")

                    if st.button("Register", type="secondary", use_container_width=True):
                        if reg_email and reg_pass and reg_pass == reg_pass_confirm:
                            try:
                                services = init_services()
                                res = services['supabase'].auth.sign_up({
                                    "email": reg_email,
                                    "password": reg_pass
                                })
                                if res.user:
                                    st.success("✅ Registration successful! Please check your email.")
                                else:
                                    st.warning("⚠️ Please check your confirmation email.")
                            except Exception as e:
                                st.error(f"Registration failed: {str(e)}")
                        else:
                            st.error("Please fill all fields correctly")

                st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("""
                <div style='margin-top: 40px;'>
                    <h4 style='text-align: center; color: #2d3748; margin-bottom: 24px;'>✨ Ver 6.0 — Tính năng nổi bật</h4>
                    <div class='feature-grid'>
                        <div class='feature-card'><div class='icon'>🤖</div><h4>Multi-AI</h4><p>20+ models OpenRouter</p></div>
                        <div class='feature-card'><div class='icon'>🎯</div><h4>Semantic Intent</h4><p>Khớp câu hỏi, bỏ Router</p></div>
                        <div class='feature-card'><div class='icon'>📚</div><h4>Knowledge</h4><p>Bible, Rules, Chunking</p></div>
                        <div class='feature-card'><div class='icon'>📐</div><h4>Arc</h4><p>Phân vùng timeline</p></div>
                        <div class='feature-card'><div class='icon'>🧮</div><h4>Python Executor</h4><p>Tính toán số liệu</p></div>
                        <div class='feature-card'><div class='icon'>🧠</div><h4>Rule Mining</h4><p>Học từ chat</p></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.stop()


# ==========================================
# 💰 COST MANAGEMENT
# ==========================================
class CostManager:
    """Quản lý chi phí AI"""

    @staticmethod
    def get_user_budget(user_id: str) -> dict:
        """Lấy thông tin budget của user"""
        try:
            services = init_services()
            supabase = services['supabase']

            res = supabase.table("user_budgets") \
                .select("*") \
                .eq("user_id", user_id) \
                .execute()

            if res.data:
                return res.data[0]
            else:
                default_budget = {
                    "user_id": user_id,
                    "total_credits": 100.0,
                    "used_credits": 0.0,
                    "remaining_credits": 100.0,
                    "last_reset_date": datetime.utcnow().date().isoformat()
                }

                supabase.table("user_budgets").insert(default_budget).execute()
                return default_budget
        except Exception as e:
            print(f"Error getting budget: {e}")
            return {
                "total_credits": 100.0,
                "used_credits": 0.0,
                "remaining_credits": 100.0
            }

    @staticmethod
    def update_budget(user_id: str, cost: float):
        """Cập nhật budget sau khi sử dụng"""
        try:
            services = init_services()
            supabase = services['supabase']

            budget = CostManager.get_user_budget(user_id)

            new_used = budget.get("used_credits", 0.0) + cost
            remaining = budget.get("total_credits", 100.0) - new_used

            supabase.table("user_budgets") \
                .update({
                    "used_credits": new_used,
                    "remaining_credits": remaining,
                    "updated_at": datetime.utcnow().isoformat()
                }) \
                .eq("user_id", user_id) \
                .execute()

            return remaining
        except Exception as e:
            print(f"Error updating budget: {e}")
            return None
