import streamlit as st
import json
import re
import pandas as pd
import time
from datetime import datetime, timedelta
import hashlib
import uuid
from typing import Dict, List, Optional, Tuple, Any
from supabase import create_client, Client
import extra_streamlit_components as stx
from openai import OpenAI

# ==========================================
# 🎨 1. CẤU HÌNH & CSS NÂNG CẤP
# ==========================================
st.set_page_config(
    page_title="V-Universe AI Hub Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS tùy chỉnh nâng cao với màu sắc hiện đại
st.markdown("""
<style>
    /* Sửa màu chữ Tab thành màu trắng và in đậm */
    button[data-baseweb="tab"] {
        color: white !important;
        font-weight: 600 !important;
        background-color: #262730 !important; /* Màu nền tối nhẹ cho tab chưa chọn */
        border: 1px solid #444 !important;
        margin-right: 4px !important;
    }

    /* Sửa màu Tab đang chọn (Active) cho nổi bật */
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #FF4B4B !important; /* Màu đỏ chủ đạo của Streamlit hoặc màu bạn thích */
        color: white !important;
        border-color: #FF4B4B !important;
    }
    
    /* Ẩn cái thanh trang trí nhỏ xíu mặc định của Streamlit đi cho đỡ rối */
    div[data-baseweb="tab-highlight"] {
        display: none !important;
    }
</style>
<style>
    /* Global Styles */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
        color: white;
    }
    
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 12px 20px;
        font-weight: 600;
        transition: all 0.3s ease;
        width: 100%;
        margin: 5px 0;
    }
    
    [data-testid="stSidebar"] .stButton > button:hover {
        background: linear-gradient(135deg, #5a6fd8 0%, #6a4490 100%);
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
    }
    
    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: #f8fafc;
        padding: 8px;
        border-radius: 12px;
        margin-bottom: 20px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        padding: 0 24px;
        background-color: #e2e8f0;
        border-radius: 8px;
        font-weight: 600;
        color: #4a5568;
        border: 2px solid transparent;
        transition: all 0.3s ease;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-color: #667eea;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
    }
    
    /* Chat Messages */
    .stChatMessage {
        padding: 20px;
        border-radius: 15px;
        margin: 12px 0;
        border-left: 5px solid;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .stChatMessage[data-testid="user"] {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border-left-color: #2196f3;
    }
    
    .stChatMessage[data-testid="assistant"] {
        background: linear-gradient(135deg, #f1f8e9 0%, #dcedc8 100%);
        border-left-color: #4caf50;
    }
    
    /* Cards & Containers */
    .card {
        background: white;
        border-radius: 15px;
        padding: 20px;
        margin: 10px 0;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        transition: all 0.3s ease;
    }
    
    .card:hover {
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
        transform: translateY(-3px);
    }
    
    /* Input Fields */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border-radius: 10px;
        border: 2px solid #e2e8f0;
        padding: 12px;
        font-size: 14px;
    }
    
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    
    /* Metrics & Stats */
    .metric-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin: 20px 0;
    }
    
    .metric-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 12px;
        text-align: center;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        margin: 10px 0;
    }
    
    .metric-label {
        font-size: 14px;
        opacity: 0.9;
    }
    
    /* Status Indicators */
    .status-badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        margin: 2px;
    }
    
    .status-active { background: #d4edda; color: #155724; }
    .status-warning { background: #fff3cd; color: #856404; }
    .status-error { background: #f8d7da; color: #721c24; }
    
    /* Animations */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .animate-fadeIn {
        animation: fadeIn 0.5s ease-out;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #5a6fd8 0%, #6a4490 100%);
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #2d3748;
        font-weight: 700;
    }
    
    h1 { font-size: 2.5rem; margin-bottom: 1rem; }
    h2 { font-size: 2rem; margin-bottom: 0.75rem; }
    h3 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    
    /* Dividers */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(to right, transparent, #667eea, transparent);
        margin: 30px 0;
    }
    
    /* Dashboard Specific */
    .dashboard-widget {
        background: white;
        border-radius: 15px;
        padding: 20px;
        margin: 10px 0;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }
    
    .widget-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 15px;
    }
    
    .widget-title {
        font-size: 18px;
        font-weight: 600;
        color: #2d3748;
    }
    
    .widget-value {
        font-size: 24px;
        font-weight: 700;
        color: #667eea;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔧 2. CẤU HÌNH HỆ THỐNG
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
        # OpenAI
        
        "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
        # Anthropic
        "anthropic/claude-opus-4.5": {"input": 5.00, "output": 25.00},
        "anthropic/claude-sonnet-4.5": {"input": 3.00, "output": 15.00},
        "anthropic/claude-haiku-4.5": {"input": 1.00, "output": 5.00},
        "anthropic/claude-3.5-haiku": {"input": 0.80, "output": 4.00},
        # Google
        "google/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
        "google/gemini-3-flash-preview": {"input": 0.5, "output": 3.00},
        "google/gemini-2.5-flash": {"input": 0.3, "output": 2.50},
        # Open Source
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
    
    # Bible prefixes (người dùng có thể tạo thêm)
    BIBLE_PREFIXES = [
        "[RULE]",  # Mặc định
        "[CHARACTER]",
        "[LOCATION]",
        "[CONCEPT]",
        "[ITEM]",
        "[EVENT]",
        "[SYSTEM]",
        "[LORE]",
        "[TECH]",
        "[META]",
        "[CHAT]"
    ]
    
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
# 🔗 3. KHỞI TẠO DỊCH VỤ
# ==========================================
@st.cache_resource
def init_services():
    """Khởi tạo kết nối đến các dịch vụ"""
    try:
        # Khởi tạo OpenAI client cho OpenRouter
        openai_client = OpenAI(
            base_url=Config.OPENROUTER_BASE_URL,
            api_key=Config.OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": "https://v-universe.streamlit.app",
                "X-Title": "V-Universe AI Hub"
            }
        )
        
        # Khởi tạo Supabase client
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        
        # Test connections
        supabase.table("stories").select("count", count="exact").limit(1).execute()
        
        return {
            "openai": openai_client,
            "supabase": supabase
        }
    except Exception as e:
        st.error(f"❌ Failed to initialize services: {str(e)}")
        return None

# ==========================================
# 🍪 4. QUẢN LÝ PHIÊN & AUTH
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
                'edit_rule_manual': None
            })
    
    def check_login(self):
        """Kiểm tra và quản lý đăng nhập"""
        self.initialize_session()

        # 1. FIX LOGOUT: Nếu đang trong trạng thái logout, return False ngay lập tức
        if st.session_state.get('logging_out'):
            return False

        # Kiểm tra session state (User đã login trong phiên này)
        if 'user' in st.session_state and st.session_state.user:
            return True

        # Lấy cookie
        access_token = self.cookie_manager.get("supabase_access_token")
        refresh_token = self.cookie_manager.get("supabase_refresh_token")

        # 2. FIX F5 NHÁY: Chỉ check login nếu có đủ token
        if access_token and refresh_token:
            try:
                # Thêm spinner để nếu đang load thì người dùng thấy "Checking..." thay vì Form đăng nhập
                # (Tùy chọn, nhưng giúp trải nghiệm mượt hơn)
                services = init_services()
                if services:
                    session = services['supabase'].auth.set_session(access_token, refresh_token)
                    if session and session.user:
                        st.session_state.user = session.user
                        st.rerun()
            except Exception as e:
                # Nếu token lỗi thì xóa đi
                self.cookie_manager.delete("supabase_access_token")
                self.cookie_manager.delete("supabase_refresh_token")
                return False
                
        return False
    
    def render_login_form(self):
        """Hiển thị form đăng nhập/đăng ký"""
        st.markdown("<div class='animate-fadeIn'>", unsafe_allow_html=True)
        
        # Header section
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("<h1 style='text-align: center;'>🚀 V-Universe AI Hub Pro</h1>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: #666;'>Your Intelligent Writing & Development Assistant</p>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Main login container
        col1, col2, col3 = st.columns([1, 3, 1])
        
        with col2:
            with st.container():
                st.markdown("<div class='card'>", unsafe_allow_html=True)
                
                # Tabs for login/register
                tab_login, tab_register = st.tabs(["🔐 Login", "📝 Register"])
                
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
                                    
                                    # Set cookies
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
                                except:
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
                
                # Features showcase
                st.markdown("""
                <div style='margin-top: 30px; text-align: center;'>
                    <h4>✨ Features</h4>
                    <div class='metric-container'>
                        <div class='card'><strong>🤖 Multi-AI</strong><br>20+ AI Models</div>
                        <div class='card'><strong>📝 Smart Writer</strong><br>AI Writing Assistant</div>
                        <div class='card'><strong>💻 Code Genius</strong><br>Programming Helper</div>
                        <div class='card'><strong>📚 Knowledge Base</strong><br>Smart Bible System</div>
                        <div class='card'><strong>🔍 Hybrid Search</strong><br>Vector + Keyword</div>
                        <div class='card'><strong>🧠 Rule Mining</strong><br>Learn from Chat</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        st.stop()

# ==========================================
# 🧠 5. PERSONA SYSTEM (IMPORT FROM PERSONA.PY)
# ==========================================
try:
    from persona import PERSONAS
    PersonaSystem = type('PersonaSystem', (), {'PERSONAS': PERSONAS})
except ImportError:
    # Fallback persona system
    class PersonaSystem:
        PERSONAS = {
            "Writer": {
                "icon": "✍️",
                "role": "Professional Editor & Writer",
                "core_instruction": """You are V - A seasoned literary editor with 10 years experience.
                Personality: Sharp, critical but caring, direct yet constructive.
                Communication: Use "I" when speaking to "You".
                Task: Provide insightful literary criticism, highlight strengths/weaknesses, suggest improvements.""",
                "prefix": "[WRITER]",
                "temperature": 0.8,
                "max_tokens": 2000,
                "review_prompt": "Review this text for literary quality, structure, and style.",
                "extractor_prompt": "Extract key entities, characters, locations, and concepts from this text as JSON objects."
            },
            "Coder": {
                "icon": "💻",
                "role": "Senior Tech Lead & Developer",
                "core_instruction": """You are V - A tech lead with 10 years coding experience.
                Personality: Pragmatic, loves clean code, hates overengineering.
                Communication: Use "I" when speaking to "You".
                Task: Code review, algorithm optimization, security warnings, best practices.""",
                "prefix": "[CODER]",
                "temperature": 0.3,
                "max_tokens": 1500,
                "review_prompt": "Review this code for bugs, optimization opportunities, and best practices.",
                "extractor_prompt": "Extract functions, classes, data structures, and algorithms from this code as JSON objects."
            },
            "Content Creator": {
                "icon": "🎬",
                "role": "Viral Content Strategist",
                "core_instruction": """You are V - Expert in Content Marketing & Social Media.
                Personality: Creative, trend-savvy, understands crowd psychology.
                Communication: Use "I" when speaking to "You".
                Task: Optimize hooks, increase engagement, create viral content strategies.""",
                "prefix": "[CONTENT]",
                "temperature": 0.9,
                "max_tokens": 1800,
                "review_prompt": "Review this content for engagement potential, virality, and audience appeal.",
                "extractor_prompt": "Extract key topics, audience segments, and content strategies from this text as JSON objects."
            },
            "Analyst": {
                "icon": "📊",
                "role": "Data & Business Analyst",
                "core_instruction": """You are V - Expert in data analysis and business intelligence.
                Personality: Analytical, detail-oriented, data-driven.
                Communication: Use data-backed arguments, be precise.
                Task: Analyze patterns, provide insights, make data-driven recommendations.""",
                "prefix": "[ANALYST]",
                "temperature": 0.4,
                "max_tokens": 1600,
                "review_prompt": "Analyze this data/report for insights, patterns, and recommendations.",
                "extractor_prompt": "Extract key metrics, insights, and data points from this analysis as JSON objects."
            }
        }
        
        @classmethod
        def get_persona(cls, persona_type: str) -> Dict:
            """Lấy cấu hình persona"""
            return cls.PERSONAS.get(persona_type, cls.PERSONAS["Writer"])
        
        @classmethod
        def get_available_personas(cls) -> List[str]:
            """Danh sách persona có sẵn"""
            return list(cls.PERSONAS.keys())

# ==========================================
# 🤖 6. AI SERVICE (SỬ DỤNG OPENAI CLIENT) với tính năng nâng cao
# ==========================================
class AIService:
    """Dịch vụ AI sử dụng OpenAI client cho OpenRouter với các tính năng nâng cao"""
    
    @staticmethod
    @st.cache_data(ttl=3600)
    def get_available_models():
        """Lấy danh sách model có sẵn từ OpenRouter"""
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY
            )
            
            # Note: OpenRouter doesn't have a models endpoint like OpenAI
            # We'll use our predefined list
            return Config.AVAILABLE_MODELS
        except:
            return Config.AVAILABLE_MODELS
    
    @staticmethod
    def call_openrouter(
        messages: List[Dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 8000,
        stream: bool = False,
        response_format: Optional[Dict] = None # <--- THÊM THAM SỐ NÀY
    ) -> Any:
        """Gọi OpenRouter API sử dụng OpenAI client"""
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": "https://v-universe.streamlit.app",
                    "X-Title": "V-Universe AI Hub"
                }
            )
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                response_format=response_format # <--- TRUYỀN VÀO ĐÂY
            )
            
            return response
        except Exception as e:
            raise Exception(f"OpenRouter API error: {str(e)}")
    
    @staticmethod
    def get_embedding(text: str) -> Optional[List[float]]:
        """Lấy embedding từ OpenRouter"""
        if not text or not isinstance(text, str) or not text.strip():
            return None
            
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY
            )
            
            response = client.embeddings.create(
                model=Config.EMBEDDING_MODEL,
                input=text
            )
            
            return response.data[0].embedding
        except Exception as e:
            print(f"Embedding error: {e}")
            return None
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Ước tính số token"""
        if not text:
            return 0
        return len(text) // 4  # Approximation
    
    @staticmethod
    def calculate_cost(
        input_tokens: int,
        output_tokens: int,
        model: str
    ) -> float:
        """Tính chi phí cho request"""
        model_costs = Config.MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
        
        input_cost = (input_tokens / 1_000_000) * model_costs["input"]
        output_cost = (output_tokens / 1_000_000) * model_costs["output"]
        
        return round(input_cost + output_cost, 6)
    
    @staticmethod
    def clean_json_text(text):
        """Làm sạch markdown (```json ... ```) trước khi parse"""
        if not text:
            return "{}"
        text = text.replace("```json", "").replace("```", "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != 0:
            return text[start:end]
        return text

# ==========================================
# 🔍 7. HYBRID SEARCH SYSTEM
# ==========================================
class HybridSearch:
    """Hệ thống tìm kiếm kết hợp vector và từ khóa"""
    
    @staticmethod
    def smart_search_hybrid_raw(query_text: str, project_id: str, top_k: int = 10) -> List[Dict]:
        """Tìm kiếm hybrid trả về raw data"""
        try:
            services = init_services()
            supabase = services['supabase']
            
            # Lấy embedding cho query
            query_vec = AIService.get_embedding(query_text)
            
            if query_vec:
                # Thử sử dụng RPC nếu có
                try:
                    response = supabase.rpc("hybrid_search", {
                        "query_text": query_text,
                        "query_embedding": query_vec,
                        "match_threshold": 0.3,
                        "match_count": top_k,
                        "story_id_input": project_id
                    }).execute()
                    return response.data if response.data else []
                except:
                    # Fallback: tìm kiếm từ khóa
                    response = supabase.table("story_bible") \
                        .select("*") \
                        .eq("story_id", project_id) \
                        .ilike("entity_name", f"%{query_text}%") \
                        .or_(f"description.ilike.%{query_text}%") \
                        .limit(top_k) \
                        .execute()
                    return response.data if response.data else []
            else:
                # Chỉ tìm kiếm từ khóa
                response = supabase.table("story_bible") \
                    .select("*") \
                    .eq("story_id", project_id) \
                    .ilike("entity_name", f"%{query_text}%") \
                    .or_(f"description.ilike.%{query_text}%") \
                    .limit(top_k) \
                    .execute()
                return response.data if response.data else []
                
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    @staticmethod
    def smart_search_hybrid(query_text: str, project_id: str, top_k: int = 10) -> str:
        """Wrapper trả về string context"""
        raw_data = HybridSearch.smart_search_hybrid_raw(query_text, project_id, top_k)
        results = []
        if raw_data:
            for item in raw_data:
                results.append(f"- [{item['entity_name']}]: {item['description']}")
        return "\n".join(results) if results else ""

# ==========================================
# 🧭 8. SMART AI ROUTER SYSTEM (NÂNG CẤP)
# ==========================================
class SmartAIRouter:
    """Bộ định tuyến AI thông minh với hybrid search"""
    
    @staticmethod
    def ai_router_pro_v2(user_prompt: str, chat_history_text: str, project_id: str = None) -> Dict:
        """Router V2: Phân tích Intent và Target Files"""
        # --- ĐOẠN CODE MỚI: LẤY LUẬT ---
        rules_context = ""
        if project_id:
        # Gọi hàm có sẵn trong ContextManager để lấy luật
            rules_context = ContextManager.get_mandatory_rules(project_id)
    # -------------------------------
        router_prompt = f"""
        Đóng vai Điều Phối Viên Dự Án (Project Coordinator).
        
        ⚠️ QUY TẮC BẮT BUỘC:
        {rules_context}

        LỊCH SỬ CHAT:
        {chat_history_text}
        
        INPUT CỦA USER: "{user_prompt}"
        
        NHIỆM VỤ: Phân tích intent và xác định dữ liệu cần thiết.

        PHÂN LOẠI INTENT:
        1. "read_full_content": User muốn Sửa, Review, Viết tiếp, Kiểm tra code/văn, hoặc nhắc đến tên file cụ thể -> Cần đọc NGUYÊN VĂN FILE.
        2. "search_bible": User hỏi thông tin chung, Lore, cốt truyện, quy định, khái niệm -> Tra cứu Bible (Vector DB).
        3. "chat_casual": Chào hỏi, khen chê, nói chuyện phiếm không cần dữ liệu dự án.
        4. "mixed_context": Cần cả nội dung file VÀ kiến thức Bible (Vd: "Sửa file A sao cho đúng với cốt truyện B").

        OUTPUT (JSON ONLY):
        {{
            "intent": "...",
            "target_files": ["tên file 1", "tên file 2"],
            "target_bible_entities": ["tên thực thể 1", "tên thực thể 2"],
            "reason": "Lý do ngắn gọn bằng tiếng Việt",
            "rewritten_query": "Viết lại câu hỏi của user cho rõ nghĩa hơn để search database"
        }}
        """

        messages = [
            {"role": "system", "content": "Bạn là AI Router thông minh. Chỉ trả về JSON."},
            {"role": "user", "content": router_prompt}
        ]
        
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"} # <--- THÊM DÒNG NÀY
            )
            
            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)
            
            # Parse JSON response
            result = json.loads(content)
            
            # Đảm bảo các trường luôn tồn tại
            result.setdefault("target_files", [])
            result.setdefault("target_bible_entities", [])
            result.setdefault("rewritten_query", user_prompt)
            
            return result
            
        except Exception as e:
            print(f"Router error: {e}")
            return {
                "intent": "chat_casual",
                "target_files": [],
                "target_bible_entities": [],
                "reason": f"Router error: {e}",
                "rewritten_query": user_prompt
            }

# ==========================================
# 📚 9. CONTEXT MANAGER (NÂNG CẤP)
# ==========================================
class ContextManager:
    """Quản lý context cho AI với khả năng kết hợp nhiều nguồn"""
    
    @staticmethod
    def load_full_content(file_names: List[str], project_id: str) -> Tuple[str, List[str]]:
        """Load toàn văn nội dung của nhiều file/chương"""
        if not file_names:
            return "", []
        
        services = init_services()
        supabase = services['supabase']
        
        full_text = ""
        loaded_sources = []
        
        for name in file_names:
            # 1. Tìm trong Chapters (Full)
            res = supabase.table("chapters") \
                .select("chapter_number, title, content") \
                .eq("story_id", project_id) \
                .ilike("title", f"%{name}%") \
                .execute()
            
            if res.data:
                item = res.data[0]
                full_text += f"\n\n=== 📄 SOURCE FILE/CHAP: {item['title']} ===\n{item['content']}\n"
                loaded_sources.append(f"📄 {item['title']}")
            else:
                # 2. Tìm trong Bible (Summary Fallback)
                res_bible = supabase.table("story_bible") \
                    .select("entity_name, description") \
                    .eq("story_id", project_id) \
                    .ilike("entity_name", f"%{name}%") \
                    .execute()
                if res_bible.data:
                    item = res_bible.data[0]
                    full_text += f"\n\n=== ⚠️ BIBLE SUMMARY: {item['entity_name']} ===\n{item['description']}\n"
                    loaded_sources.append(f"🗂️ {item['entity_name']} (Summary)")
        
        return full_text, loaded_sources
    
    @staticmethod
    def get_mandatory_rules(project_id: str) -> str:
        """Lấy tất cả các luật (RULE) bắt buộc"""
        try:
            services = init_services()
            supabase = services['supabase']
            
            # Tìm các entity bắt đầu bằng [RULE]
            res = supabase.table("story_bible") \
                .select("description") \
                .eq("story_id", project_id) \
                .ilike("entity_name", "%[RULE]%") \
                .execute()
            
            if res.data:
                rules_text = "\n".join([f"- {r['description']}" for r in res.data])
                return f"\n🔥 --- MANDATORY RULES ---\n{rules_text}\n"
            return ""
        except Exception as e:
            print(f"Error getting rules: {e}")
            return ""
    
    @staticmethod
    def build_context(
        router_result: Dict,
        project_id: str,
        persona: Dict,
        strict_mode: bool = False
    ) -> Tuple[str, List[str], int]:
        """Xây dựng context từ router result với khả năng kết hợp"""
        context_parts = []
        sources = []
        total_tokens = 0
        
        # 1. Persona Instruction
        persona_text = f"🎭 PERSONA: {persona['role']}\n{persona['core_instruction']}\n"
        context_parts.append(persona_text)
        total_tokens += AIService.estimate_tokens(persona_text)
        
        # 2. Strict Mode Instructions
        if strict_mode:
            strict_text = """
            \n\n‼️ CHẾ ĐỘ NGHIÊM NGẶT (STRICT MODE) ĐANG BẬT:
            1. CHỈ trả lời dựa trên thông tin có trong [CONTEXT].
            2. TUYỆT ĐỐI KHÔNG bịa đặt hoặc dùng kiến thức bên ngoài để điền vào chỗ trống.
            3. Nếu không tìm thấy thông tin trong Context, hãy trả lời: "Dữ liệu dự án chưa có thông tin này."
            4. Nếu User hỏi về "lịch sử", "cốt truyện", hãy ưu tiên trích xuất từ [KNOWLEDGE BASE].
            5. Không từ chối trả lời các dữ liệu thực tế (fact) chỉ vì tính cách Persona.
            """
            context_parts.append(strict_text)
            total_tokens += AIService.estimate_tokens(strict_text)
        
        # 3. Mandatory Rules
        rules_text = ContextManager.get_mandatory_rules(project_id)
        if rules_text:
            context_parts.append(rules_text)
            total_tokens += AIService.estimate_tokens(rules_text)
        
        # 4. Load content based on intent
        intent = router_result.get("intent", "chat_casual")
        target_files = router_result.get("target_files", [])
        target_bible_entities = router_result.get("target_bible_entities", [])
        
        if intent == "read_full_content" and target_files:
            full_text, source_names = ContextManager.load_full_content(target_files, project_id)
            context_parts.append(f"\n--- TARGET CONTENT ---\n{full_text}")
            sources.extend(source_names)
            total_tokens += AIService.estimate_tokens(full_text)
        
        elif intent == "search_bible" or intent == "mixed_context":
            # Tìm kiếm Bible entities cụ thể
            bible_context = ""
            for entity in target_bible_entities:
                search_result = HybridSearch.smart_search_hybrid(entity, project_id, top_k=2)
                if search_result:
                    bible_context += f"\n--- {entity.upper()} ---\n{search_result}\n"
            
            # Nếu không có entity cụ thể, search bằng toàn bộ query
            if not bible_context and router_result.get("rewritten_query"):
                search_result = HybridSearch.smart_search_hybrid(
                    router_result["rewritten_query"], 
                    project_id, 
                    top_k=5
                )
                if search_result:
                    bible_context = f"\n--- KNOWLEDGE BASE ---\n{search_result}\n"
            
            if bible_context:
                context_parts.append(bible_context)
                total_tokens += AIService.estimate_tokens(bible_context)
                sources.append("📚 Bible Search")
            # 2. LOGIC MỚI: SUY LUẬN NGƯỢC (REVERSE LOOKUP) [2, 3]
            # Tự động tìm chương truyện gốc chứa entity và nạp vào context
            try:
                services = init_services()
                supabase = services['supabase']
                related_chapter_nums = set()

                # Chỉ chạy nếu Router đã xác định được entity (vd: [ITEM] Kiếm Thần)
                if target_bible_entities:
                    for entity in target_bible_entities:
                        # Tra bảng story_bible để xem entity này xuất hiện ở chương nào (source_chapter)
                        res = supabase.table("story_bible") \
                            .select("source_chapter") \
                            .eq("story_id", project_id) \
                            .ilike("entity_name", f"%{entity}%") \
                            .execute()
                        
                        if res.data:
                            for row in res.data:
                                # Chỉ lấy nếu source_chapter hợp lệ (>0)
                                if row.get('source_chapter') and row['source_chapter'] > 0:
                                    related_chapter_nums.add(row['source_chapter'])

                # Nếu tìm thấy chương liên quan, lấy tên file và tải nội dung
                if related_chapter_nums:
                    # Lấy Title (tên file) từ bảng chapters
                    chap_res = supabase.table("chapters") \
                        .select("title") \
                        .eq("story_id", project_id) \
                        .in_("chapter_number", list(related_chapter_nums)) \
                        .execute()
                    
                    if chap_res.data:
                        # Tạo danh sách tên file
                        auto_files = [c['title'] for c in chap_res.data if c.get('title')]
                        
                        if auto_files:
                            # Tái sử dụng hàm load_full_content có sẵn
                            extra_text, extra_sources = ContextManager.load_full_content(auto_files, project_id)
                            
                            if extra_text:
                                context_parts.append(f"\n--- 🕵️ AUTO-DETECTED CONTEXT (REVERSE LOOKUP) ---\n{extra_text}")
                                # Thêm vào nguồn trích dẫn để user biết AI đang đọc file nào
                                sources.extend([f"{s} (Auto)" for s in extra_sources])
                                total_tokens += AIService.estimate_tokens(extra_text)

            except Exception as e:
                print(f"Reverse lookup error: {e}")
                # Không crash app nếu lỗi tính năng phụ này
                pass
        
        # 5. File content cho mixed_context
        if intent == "mixed_context" and target_files:
            full_text, source_names = ContextManager.load_full_content(target_files, project_id)
            context_parts.append(f"\n--- RELATED FILES ---\n{full_text}")
            sources.extend(source_names)
            total_tokens += AIService.estimate_tokens(full_text)
        
        return "\n".join(context_parts), sources, total_tokens

# ==========================================
# 🧬 10. RULE MINING SYSTEM (FIXED)
# ==========================================
class RuleMiningSystem:
    """Hệ thống khai thác và quản lý luật từ chat"""
    
    @staticmethod
    def extract_rule_raw(user_prompt: str, ai_response: str) -> Optional[str]:
        """Trích xuất luật thô từ hội thoại"""
        prompt = f"""
        Bạn là "Trinh Sát Luật" (Rule Scout). Nhiệm vụ: Phát hiện sở thích/yêu cầu của User.

        HỘI THOẠI:
        - User: "{user_prompt}"
        - AI: (Phản hồi trước đó...)

        MỤC TIÊU:
        Phát hiện xem User có đang ngầm chỉ định CÁCH LÀM VIỆC, CÁCH VIẾT, hoặc ĐỊNH DẠNG không.

        TIÊU CHÍ (Độ nhạy cao):
        1. Yêu cầu định dạng: "chỉ json", "dùng markdown", "đừng viết code", "viết ngắn thôi".
        2. Điều chỉnh văn phong: "nghiêm túc hơn", "bớt nói nhảm", "dùng tiếng Việt".
        3. Sửa lỗi: "sai rồi", "không phải thế", "làm thế này mới đúng".

        HƯỚNG DẪN:
        - Nếu User nói: "Viết cái này bằng Python nhé" -> Tạo luật: "Luôn ưu tiên dùng Python".
        - Thà bắt nhầm còn hơn bỏ sót.

        OUTPUT:
        - Nếu phát hiện luật: Trả về 1 câu mệnh lệnh ngắn gọn kèm ngữ cảnh (Tiếng Việt). Ví dụ: "Luôn trả về định dạng JSON khi được yêu cầu...", "Không giải thích dài dòng khi user đang khó chịu...".
        - Nếu chỉ là chào hỏi/cảm ơn: Trả về "NO_RULE".

        Chỉ trả về Text.
        """
        
        messages = [
            {"role": "system", "content": "You are Rule Extractor. Return text only."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.3,
                max_tokens=300
            )
            
            text = response.choices[0].message.content.strip()
            
            # Filter additional layer
            if "NO_RULE" in text or len(text) < 5:
                return None
            return text
        except Exception as e:
            print(f"Rule extraction error: {e}")
            return None
    
    @staticmethod
    def analyze_rule_conflict(new_rule_content: str, project_id: str) -> Dict:
        """Check rule conflict with DB - Safe Version"""
        similar_rules_str = HybridSearch.smart_search_hybrid(new_rule_content, project_id, top_k=3)
        
        if not similar_rules_str:
            return {
                "status": "NEW",
                "reason": "No conflicts found",
                "existing_rule_summary": "None",
                "merged_content": None,
                "suggested_content": new_rule_content
            }
        
        judge_prompt = f"""
        Luật Mới: "{new_rule_content}"
        Luật Cũ trong DB: "{similar_rules_str}"

        Nhiệm vụ: So sánh mối quan hệ.

        - CONFLICT (Xung đột): Mâu thuẫn trực tiếp (Vd: Cũ bảo A, Mới bảo không A).
        - MERGE (Gộp): Cùng chủ đề nhưng luật Mới chi tiết hơn hoặc bổ sung cho luật Cũ.
        - NEW (Mới): Chủ đề khác hẳn.

        OUTPUT JSON ONLY:
        {{
            "status": "CONFLICT" | "MERGE" | "NEW",
            "existing_rule_summary": "Tóm tắt luật cũ (Tiếng Việt)",
            "reason": "Lý do (Tiếng Việt)",
            "merged_content": "Nội dung luật đã gộp hoàn chỉnh (nếu MERGE). Nếu khác thì để null."
        }}
        """
        
        messages = [
            {"role": "system", "content": "You are Rule Judge. Return only JSON."},
            {"role": "user", "content": judge_prompt}
        ]
        
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.2,
                max_tokens=4000,
                response_format={"type": "json_object"} # <--- THÊM DÒNG NÀY
            )
            
            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)
            
            result = json.loads(content)
            
            # --- SAFE RETURN WITH DEFAULTS ---
            return {
                "status": result.get("status", "NEW"),
                "reason": result.get("reason", "No reason provided by AI"),
                "existing_rule_summary": result.get("existing_rule_summary", "N/A"),
                "merged_content": result.get("merged_content", None),
                "suggested_content": new_rule_content
            }
            
        except Exception as e:
            print(f"Rule analysis error: {e}")
            # Return safe fallback structure so UI doesn't crash
            return {
                "status": "NEW",
                "reason": f"AI Judge Error: {str(e)}",
                "existing_rule_summary": "Error analyzing",
                "merged_content": None,
                "suggested_content": new_rule_content
            }
    
    @staticmethod
    def crystallize_session(chat_history: List[Dict], persona_role: str) -> str:
        """Tóm tắt và lọc thông tin giá trị từ chat history"""
        chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history])
        
        crystallize_prompt = f"""
        Bạn là Thư Ký Cuộc Họp ({persona_role}).
        
        Nhiệm vụ: Đọc đoạn chat dưới đây và LỌC BỎ NHỮNG THỨ VÔ NGHĨA.
        Chỉ giữ lại và TÓM TẮT những thông tin giá trị (Sự kiện, Ý tưởng, Quyết định, Lore mới).

        CHAT LOG: {chat_text}

        OUTPUT: Trả về bản tóm tắt súc tích (50-100 từ) bằng Tiếng Việt. 
        Nếu toàn là chào hỏi vô nghĩa, trả về "NO_INFO".
        """
        
        messages = [
            {"role": "system", "content": "You are Conversation Summarizer. Return text only."},
            {"role": "user", "content": crystallize_prompt}
        ]
        
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.3,
                max_tokens=8000
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Crystallize error: {e}")
            return f"AI Error: {e}"
# ==========================================
# 💰 11. COST MANAGEMENT
# ==========================================
class CostManager:
    """Quản lý chi phí AI"""
    
    @staticmethod
    def get_user_budget(user_id: str) -> Dict:
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
                # Tạo mới nếu chưa có
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
            
            # Get current budget
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

# ==========================================
# 🎯 12. MAIN APPLICATION COMPONENTS
# ==========================================
def render_sidebar(session_manager):
    """Render sidebar với thông tin user và project"""
    with st.sidebar:
        # Header
        st.markdown("🚀 V-Universe AI Pro", unsafe_allow_html=True)
        if 'user' in st.session_state and st.session_state.user:
            user_email = st.session_state.user.email
            st.markdown(f"_{user_email.split('@')}_", unsafe_allow_html=True) # [1]
            
            # User stats
            budget = CostManager.get_user_budget(st.session_state.user.id)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("💰 Credits", f"${budget.get('remaining_credits', 0):.2f}")
            with col2:
                usage_percent = (budget.get('used_credits', 0) / budget.get('total_credits', 100)) * 100
                st.metric("Usage", f"{usage_percent:.1f}%")
            st.markdown("---")

        # Project selection
        st.subheader("📂 Projects")
        services = init_services()
        supabase = services['supabase']

        projects = supabase.table("stories") \
            .select("*") \
            .eq("user_id", st.session_state.user.id) \
            .execute() # [2]

        # 1. KHỞI TẠO GIÁ TRỊ MẶC ĐỊNH (Tránh lỗi UnboundLocalError)
        proj_id = None
        persona = PersonaSystem.PERSONAS["Writer"] 

        # 2. LOGIC CHỌN DỰ ÁN (Nếu có dự án)
        if projects.data:
            proj_map = {p['title']: p for p in projects.data}
            selected_proj_name = st.selectbox(
                "Select Project",
                list(proj_map.keys()),
                key="project_selector"
            )
            
            current_proj = proj_map[selected_proj_name]
            proj_id = current_proj['id']
            proj_type = current_proj.get('category', 'Writer')
            
            # Store in session state
            st.session_state['current_project'] = current_proj
            st.session_state['project_id'] = proj_id
            st.session_state['persona'] = proj_type
            
            # Persona info
            persona = PersonaSystem.PERSONAS.get(proj_type, PersonaSystem.PERSONAS["Writer"])
            st.info(f"{persona['icon']} **{proj_type} Mode**") # [3]

        # 3. NÚT TẠO DỰ ÁN (Đưa ra ngoài if/else để luôn hiển thị)
        st.markdown("---")
        if st.button("Create New Project", type="primary"):
            st.session_state['show_new_project'] = True

        if st.session_state.get('show_new_project'):
            with st.form("new_project_form"):
                title = st.text_input("Project Name")
                category = st.selectbox("Category", list(PersonaSystem.PERSONAS.keys()))
                
                if st.form_submit_button("Create"):
                    if title:
                        supabase.table("stories").insert({
                            "title": title,
                            "category": category,
                            "user_id": st.session_state.user.id
                        }).execute()
                        st.success("Project created!")
                        # Tắt form sau khi tạo
                        st.session_state['show_new_project'] = False 
                        st.rerun()

        # 4. AI Settings Section
        st.markdown("---")
        st.subheader("🤖 AI Settings")
        
        # Model selection
        model_category = st.selectbox(
            "Model Category",
            list(Config.AVAILABLE_MODELS.keys()),
            index=1,
            key="model_category"
        )
        
        available_models = Config.AVAILABLE_MODELS[model_category]
        selected_model = st.selectbox(
            "Select Model",
            available_models,
            index=0,
            key="model_selector"
        ) # [4]
        st.session_state['selected_model'] = selected_model

        # Advanced settings
        with st.expander("Advanced Settings"):
            st.session_state['temperature'] = st.slider(
                "Temperature",
                min_value=0.0, max_value=1.0,
                value=persona.get('temperature', 0.7),
                step=0.1
            )
            st.session_state['context_size'] = st.select_slider(
                "Context Size",
                options=["low", "medium", "high", "max"],
                value="medium"
            ) # [4], [5]

        st.markdown("---")

        # Quick Actions
        st.subheader("⚡ Quick Actions")
        if st.button("🔄 Refresh Session", use_container_width=True):
            st.rerun()
        
        # Logout logic
        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            st.session_state['logging_out'] = True
            try:
                session_manager.cookie_manager.delete("supabase_access_token")
                session_manager.cookie_manager.delete("supabase_refresh_token")
            except:
                pass
            
            for key in list(st.session_state.keys()):
                if key != 'logging_out':
                    del st.session_state[key]
            
            st.success("Logged out successfully!")
            time.sleep(1)
            st.rerun()

        return proj_id, persona


def render_dashboard_tab(project_id):
    """Tab Dashboard - Quản lý project tổng quan"""
    st.header("📊 Project Dashboard")
    
    if not project_id:
        st.info("📁 Please select or create a project first")
        return
    
    services = init_services()
    supabase = services['supabase']
    
    # Project Overview
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        # File count
        files = supabase.table("chapters") \
            .select("count", count="exact") \
            .eq("story_id", project_id) \
            .execute()
        file_count = files.count if hasattr(files, 'count') else len(files.data) if files.data else 0
        st.markdown("""
        <div class='dashboard-widget'>
            <div class='widget-header'>
                <div class='widget-title'>📄 Files</div>
            </div>
            <div class='widget-value'>{}</div>
        </div>
        """.format(file_count), unsafe_allow_html=True)
    
    with col2:
        # Bible entries count
        bible = supabase.table("story_bible") \
            .select("count", count="exact") \
            .eq("story_id", project_id) \
            .execute()
        bible_count = bible.count if hasattr(bible, 'count') else len(bible.data) if bible.data else 0
        st.markdown("""
        <div class='dashboard-widget'>
            <div class='widget-header'>
                <div class='widget-title'>📚 Bible Entries</div>
            </div>
            <div class='widget-value'>{}</div>
        </div>
        """.format(bible_count), unsafe_allow_html=True)
    
    with col3:
        # Rule count
        rules = supabase.table("story_bible") \
            .select("count", count="exact") \
            .eq("story_id", project_id) \
            .ilike("entity_name", "%[RULE]%") \
            .execute()
        rule_count = rules.count if hasattr(rules, 'count') else len(rules.data) if rules.data else 0
        st.markdown("""
        <div class='dashboard-widget'>
            <div class='widget-header'>
                <div class='widget-title'>📏 Rules</div>
            </div>
            <div class='widget-value'>{}</div>
        </div>
        """.format(rule_count), unsafe_allow_html=True)
    
    with col4:
        # Chat messages count
        chat = supabase.table("chat_history") \
            .select("count", count="exact") \
            .eq("story_id", project_id) \
            .execute()
        chat_count = chat.count if hasattr(chat, 'count') else len(chat.data) if chat.data else 0
        st.markdown("""
        <div class='dashboard-widget'>
            <div class='widget-header'>
                <div class='widget-title'>💬 Chat Messages</div>
            </div>
            <div class='widget-value'>{}</div>
        </div>
        """.format(chat_count), unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Recent Activity
    col_left, col_right = st.columns([2, 1])
    
    with col_left:
        st.subheader("📈 Recent Activity")
        
        # Recent files
        recent_files = supabase.table("chapters") \
            .select("title, updated_at") \
            .eq("story_id", project_id) \
            .order("updated_at", desc=True) \
            .limit(5) \
            .execute()
        
        if recent_files.data:
            df_files = pd.DataFrame(recent_files.data)
            df_files['updated_at'] = pd.to_datetime(df_files['updated_at']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(
                df_files.rename(columns={'title': 'File', 'updated_at': 'Last Updated'}),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No files yet")
    
    with col_right:
        st.subheader("🚀 Quick Actions")
        
        if st.button("📥 Import Bible from Files", use_container_width=True):
            st.session_state['import_bible_mode'] = True
        
        if st.button("🧹 Clean Old Chats", use_container_width=True):
            # Delete chats older than 30 days
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            supabase.table("chat_history") \
                .delete() \
                .eq("story_id", project_id) \
                .lt("created_at", cutoff) \
                .execute()
            st.success("Cleaned old chats!")
            st.rerun()
        
        if st.button("🔄 Re-index Bible", use_container_width=True):
            st.info("Re-indexing would update all embeddings")
        
        if st.button("📤 Export Project", use_container_width=True):
            st.info("Export functionality would be implemented here")
    
    # Bible Statistics
    st.markdown("---")
    st.subheader("📊 Bible Statistics")
    
    bible_data = supabase.table("story_bible") \
        .select("entity_name") \
        .eq("story_id", project_id) \
        .execute()
    
    if bible_data.data:
        # Analyze prefixes
        prefixes = {}
        for entry in bible_data.data:
            entity_name = entry['entity_name']
            # Find prefix in brackets
            match = re.match(r'^(\[[^\]]+\])', entity_name)
            if match:
                prefix = match.group(1)
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
            else:
                prefixes['[OTHER]'] = prefixes.get('[OTHER]', 0) + 1
        
        # Display as bar chart
        if prefixes:
            df_prefix = pd.DataFrame({
                'Prefix': list(prefixes.keys()),
                'Count': list(prefixes.values())
            }).sort_values('Count', ascending=False)
            
            st.bar_chart(df_prefix.set_index('Prefix'))
        else:
            st.info("No prefix data available")
    else:
        st.info("No bible entries yet")

def render_chat_tab(project_id, persona):
    """Tab Chat - AI Conversation với tính năng nâng cao"""
    st.header("💬 Smart AI Chat")
    
    col_chat, col_memory = st.columns([3, 1])
    
    with col_memory:
        st.write("### 🧠 Memory & Settings")
        
        # Clear chat button
        if st.button("🧹 Clear Screen", use_container_width=True):
            st.session_state['chat_cutoff'] = datetime.utcnow().isoformat()
            st.rerun()
        
        if st.button("🔄 Show All", use_container_width=True):
            st.session_state['chat_cutoff'] = "1970-01-01"
            st.rerun()
        
        # Toggles
        st.session_state['enable_history'] = st.toggle(
            "💾 Save Chat History",
            value=True,
            help="Turn off for anonymous chat (Not saved to DB, AI doesn't learn)"
        )
        
        st.session_state['strict_mode'] = st.toggle(
            "🚫 Strict Mode",
            value=False,
            help="ON: AI only answers based on found data. No fabrication. (Temp = 0)"
        )
        
        st.divider()
        
        # Crystallize logic
        with st.expander("💎 Crystallize Chat"):
            st.caption("Save key points to Bible.")
            crys_option = st.radio("Scope:", ["Last 20 messages", "Entire session"])
            memory_topic = st.text_input("Topic:", placeholder="e.g., Magic System")
            
            if st.button("✨ Crystallize"):
                services = init_services()
                supabase = services['supabase']
                
                limit = 20 if crys_option == "Last 20 messages" else 100
                chat_data = supabase.table("chat_history") \
                    .select("*") \
                    .eq("story_id", project_id) \
                    .order("created_at", desc=True) \
                    .limit(limit) \
                    .execute()
                
                if chat_data.data:
                    chat_data.data.reverse()
                    with st.spinner("Summarizing..."):
                        summary = RuleMiningSystem.crystallize_session(chat_data.data, persona['role'])
                        if summary != "NO_INFO":
                            st.session_state['chat_crystallized_summary'] = summary
                            st.session_state['chat_crystallized_topic'] = memory_topic if memory_topic else f"Chat {datetime.now().strftime('%d/%m')}"
                            st.success("Summary ready!")
                        else:
                            st.warning("No valuable information found.")
        
        # Save crystallized summary
        if 'chat_crystallized_summary' in st.session_state:
            final_sum = st.text_area("Edit summary:", value=st.session_state['chat_crystallized_summary'])
            if st.button("💾 Save to Memory"):
                vec = AIService.get_embedding(final_sum)
                if vec:
                    services = init_services()
                    supabase = services['supabase']
                    
                    supabase.table("story_bible").insert({
                        "story_id": project_id,
                        "entity_name": f"[CHAT] {st.session_state['chat_crystallized_topic']}",
                        "description": final_sum,
                        "embedding": vec,
                        "source_chapter": 0
                    }).execute()
                    
                    st.toast("Saved to memory!")
                    del st.session_state['chat_crystallized_summary']
                    st.rerun()
    
    with col_chat:
        # Load chat history
        try:
            services = init_services()
            supabase = services['supabase']
            
            msgs_data = supabase.table("chat_history") \
                .select("*") \
                .eq("story_id", project_id) \
                .order("created_at", desc=True) \
                .limit(50) \
                .execute()
            
            msgs = msgs_data.data[::-1] if msgs_data.data else []
            visible_msgs = [m for m in msgs if m['created_at'] > st.session_state.get('chat_cutoff', "1970-01-01")]
            
            for m in visible_msgs:
                role_icon = persona['icon'] if m['role'] == 'model' else None
                
                with st.chat_message(m['role'], avatar=role_icon):
                    st.markdown(m['content'])
                    
                    # Show metadata if available
                    if m.get('metadata'):
                        with st.expander("📊 Details"):
                            st.json(m['metadata'], expanded=False)
        except Exception as e:
            st.error(f"Error loading history: {e}")
        
        # Chat input
        if prompt := st.chat_input(f"Ask {persona['icon']} AI Assistant..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.spinner("Thinking..."):
                now_timestamp = datetime.utcnow().isoformat()
                
                # A. ROUTING
                recent_history_text = "\n".join([
                    f"{m['role']}: {m['content']}" 
                    for m in visible_msgs[-5:]
                ])
                
                router_out = SmartAIRouter.ai_router_pro_v2(prompt, recent_history_text, project_id)
                intent = router_out.get('intent', 'chat_casual')
                targets = router_out.get('target_files', [])
                rewritten_query = router_out.get('rewritten_query', prompt)
                
                ctx = ""
                debug_notes = [f"Intent: {intent}"]
                
                # B. CONTEXT BUILDER
                context_text, sources, context_tokens = ContextManager.build_context(
                    router_out,
                    project_id,
                    persona,
                    st.session_state.get('strict_mode', False)
                )
                
                debug_notes.extend(sources)
                
                # C. GENERATION
                final_prompt = f"CONTEXT:\n{context_text}\n\nUSER QUERY: {prompt}"
                
                run_instruction = persona['core_instruction']
                run_temperature = st.session_state.get('temperature', 0.7)
                
                if st.session_state.get('strict_mode'):
                    run_temperature = 0.0
                
                messages = []
                system_message = f"""{run_instruction}

            THÔNG TIN NGỮ CẢNH (CONTEXT):
            {context_text}

            HƯỚNG DẪN:
            - Trả lời dựa trên Context nếu có.
            - Hữu ích, súc tích, đi thẳng vào vấn đề.
            - Chế độ hiện tại: {persona['role']}
            - Ngôn ngữ: Ưu tiên Tiếng Việt (trừ khi User yêu cầu khác hoặc code).
            """
                
                messages.append({"role": "system", "content": system_message})
                
                # Add recent chat history
                for msg in visible_msgs[-6:-1]:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                
                # Add current message
                messages.append({"role": "user", "content": prompt})
                
                try:
                    model = st.session_state.get('selected_model', Config.DEFAULT_MODEL)
                    
                    response = AIService.call_openrouter(
                        messages=messages,
                        model=model,
                        temperature=run_temperature,
                        max_tokens=persona.get('max_tokens', 4000),
                        stream=True
                    )
                    
                    with st.chat_message("assistant", avatar=persona['icon']):
                        if debug_notes:
                            st.caption(f"🧠 {', '.join(debug_notes)}")
                        if st.session_state.get('strict_mode'):
                            st.caption("🔒 Strict Mode: ON")
                        
                        full_response_text = ""
                        placeholder = st.empty()
                        
                        for chunk in response:
                            if chunk.choices[0].delta.content is not None:
                                content = chunk.choices[0].delta.content
                                full_response_text += content
                                placeholder.markdown(full_response_text + "▌")
                        
                        placeholder.markdown(full_response_text)
                    
                    # Calculate costs
                    input_tokens = AIService.estimate_tokens(system_message + prompt)
                    output_tokens = AIService.estimate_tokens(full_response_text)
                    cost = AIService.calculate_cost(input_tokens, output_tokens, model)
                    
                    # Update budget
                    if 'user' in st.session_state:
                        remaining = CostManager.update_budget(st.session_state.user.id, cost)
                    
                    # Save to history
                    if full_response_text and st.session_state.get('enable_history', True):
                        services = init_services()
                        supabase = services['supabase']
                        
                        supabase.table("chat_history").insert([
                            {
                                "story_id": project_id,
                                "role": "user",
                                "content": prompt,
                                "created_at": now_timestamp,
                                "metadata": {
                                    "intent": intent,
                                    "router_output": router_out,
                                    "model": model,
                                    "temperature": run_temperature
                                }
                            },
                            {
                                "story_id": project_id,
                                "role": "model",
                                "content": full_response_text,
                                "created_at": now_timestamp,
                                "metadata": {
                                    "model": model,
                                    "cost": f"${cost:.6f}",
                                    "tokens": input_tokens + output_tokens
                                }
                            }
                        ]).execute()
                        
                        # Rule Mining
                        new_rule = RuleMiningSystem.extract_rule_raw(prompt, full_response_text)
                        if new_rule:
                            st.session_state['pending_new_rule'] = new_rule
                            st.rerun()
                    
                    elif not st.session_state.get('enable_history', True):
                        st.caption("👻 Anonymous mode: History not saved & Rule mining disabled.")
                
                except Exception as e:
                    st.error(f"Generation error: {str(e)}")
    
    # Rule Mining UI
    if 'pending_new_rule' in st.session_state:
        rule_content = st.session_state['pending_new_rule']
        
        with st.expander("🧐 AI discovered a new Rule!", expanded=True):
            st.write(f"**Content:** {rule_content}")
            
            # Analyze Conflict
            if st.session_state.get('rule_analysis') is None:
                with st.spinner("Checking for conflicts..."):
                    st.session_state['rule_analysis'] = RuleMiningSystem.analyze_rule_conflict(rule_content, project_id)
            
            analysis = st.session_state['rule_analysis']
            if analysis:
                st.info(f"AI Assessment: **{analysis.get('status', 'UNKNOWN')}** - {analysis.get('reason', 'N/A')}")
            else:
                st.error("Could not analyze rule conflict.")
            st.info(f"AI Assessment: **{analysis['status']}** - {analysis['reason']}")
            
            if analysis['status'] == "CONFLICT":
                st.warning(f"⚠️ Conflict with: {analysis['existing_rule_summary']}")
            elif analysis['status'] == "MERGE":
                st.info(f"💡 Merge suggestion: {analysis['merged_content']}")
            
            c1, c2, c3 = st.columns(3)
            
            if c1.button("✅ Save/Merge Rule"):
                final_content = analysis.get('merged_content') if analysis['status'] == "MERGE" else rule_content
                vec = AIService.get_embedding(final_content)
                
                services = init_services()
                supabase = services['supabase']
                
                supabase.table("story_bible").insert({
                    "story_id": project_id,
                    "entity_name": f"[RULE] {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "description": final_content,
                    "embedding": vec,
                    "source_chapter": 0
                }).execute()
                
                st.toast("Learned new rule!")
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()
            
            if c2.button("✏️ Edit then Save"):
                st.session_state['edit_rule_manual'] = rule_content
            
            if c3.button("❌ Ignore"):
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()
        
        if 'edit_rule_manual' in st.session_state:
            edited = st.text_input("Edit rule:", value=st.session_state['edit_rule_manual'])
            if st.button("Save edited version"):
                vec = AIService.get_embedding(edited)
                
                services = init_services()
                supabase = services['supabase']
                
                supabase.table("story_bible").insert({
                    "story_id": project_id,
                    "entity_name": f"[RULE] Manual",
                    "description": edited,
                    "embedding": vec,
                    "source_chapter": 0
                }).execute()
                
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                del st.session_state['edit_rule_manual']
                st.rerun()

import streamlit as st
import time
import json
import re
import pandas as pd

def render_workstation_tab(project_id, persona):
    """
    Tab Workstation - Phiên bản 'Bulletproof': Fix UI Extract Bible (Có nút Start)
    """
    st.subheader("✍️ Writing Workstation")
    
    if not project_id:
        st.info("📁 Vui lòng chọn Project ở thanh bên trái.")
        return

    # Giả định init_services() đã có ở context ngoài
    services = init_services()
    supabase = services['supabase']

    # --- 1. TOOLBAR ---
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1]) 
    
    with c1:
        files = supabase.table("chapters") \
            .select("chapter_number, title") \
            .eq("story_id", project_id) \
            .order("chapter_number") \
            .execute()

        file_options = {}
        file_list = files.data if files.data else []
        
        for f in file_list:
            display_name = f"📄 #{f['chapter_number']}: {f['title']}" if f['title'] else f"📄 #{f['chapter_number']}"
            file_options[display_name] = f['chapter_number']

        selected_file = st.selectbox(
            "Select File",
            ["+ New File"] + list(file_options.keys()),
            label_visibility="collapsed"
        )

    # Logic Load Data
    chap_num = 0 
    if selected_file == "+ New File":
        chap_num = len(file_list) + 1
        db_content = ""
        db_review = ""
        db_title = f"Chapter {chap_num}"
    else:
        chap_num = file_options[selected_file]
        try:
            res = supabase.table("chapters") \
                .select("content, title, review_content") \
                .eq("story_id", project_id) \
                .eq("chapter_number", chap_num) \
                .execute()
            
            if res.data and len(res.data) > 0:
                row = res.data[0]
                db_content = row.get('content') or ""
                db_title = row.get('title') or f"Chapter {chap_num}"
                db_review = row.get('review_content') or ""
            else:
                db_content = ""
                db_title = f"Chapter {chap_num}"
                db_review = ""
        except Exception as e:
            st.error(f"Lỗi load: {e}")
            db_content = ""
            db_title = f"Chapter {chap_num}"
            db_review = ""

    # Nút Save
    with c2:
        if st.button("💾 Save", use_container_width=True):
            current_content = st.session_state.get(f"file_content_{chap_num}", "")
            current_title = st.session_state.get(f"file_title_{chap_num}", db_title)
            
            if current_content:
                try:
                    supabase.table("chapters").upsert({
                        "story_id": project_id,
                        "chapter_number": chap_num,
                        "title": current_title,
                        "content": current_content,
                    }, on_conflict="story_id, chapter_number").execute()
                    
                    st.toast("✅ Đã lưu thành công!", icon="💾")
                    st.session_state.current_file_content = current_content
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu: {e}")

    # Nút Review
    with c3:
        if st.button("🚀 Review", use_container_width=True, type="primary"):
            st.session_state['trigger_ai_review'] = True
            st.rerun()

    # Nút Extract (Kích hoạt chế độ)
    with c4:
        if st.button("📥 Extract", use_container_width=True):
            st.session_state['extract_bible_mode'] = True
            # Reset dữ liệu tạm khi mở mới
            st.session_state['temp_extracted_data'] = None 
            st.rerun()

    # --- 2. EDITOR ---
    st.markdown("---")
    file_title = st.text_input(
        "Tiêu đề chương:",
        value=db_title,
        key=f"file_title_{chap_num}",
        label_visibility="collapsed",
        placeholder="Nhập tên chương..."
    )

    has_review = bool(db_review) or st.session_state.get('trigger_ai_review')
    
    if has_review:
        col_editor, col_review = st.columns([3, 2])
    else:
        col_editor = st.container()
    
    with col_editor:
        content = st.text_area(
            "Nội dung chính",
            value=db_content,
            height=650,
            key=f"file_content_{chap_num}",
            label_visibility="collapsed",
            placeholder="Viết nội dung của bạn tại đây..."
        )
        if content:
            st.caption(f"📝 {len(content.split())} từ | {len(content)} ký tự")

    # --- 3. REVIEW ---
    if has_review:
        with col_review:
            if st.session_state.get('trigger_ai_review'):
                with st.spinner("AI đang đọc & đối chiếu Bible..."):
                    try:
                        # Giả định các class Helper
                        context = HybridSearch.smart_search_hybrid(content[:1000], project_id)
                        rules = ContextManager.get_mandatory_rules(project_id)
                        
                        review_prompt = f"""
                    LUẬT DỰ ÁN: {rules}
                    
                    THÔNG TIN TỪ BIBLE (Context): {context}
                    
                    NỘI DUNG CẦN REVIEW: 
                    {content}

                    NHIỆM VỤ: {persona.get('review_prompt', 'Review nội dung này')}
                    
                    YÊU CẦU:
                    1. Chỉ ra điểm mạnh/yếu.
                    2. Phát hiện lỗi logic (plot hole) hoặc lỗi code so với Context.
                    3. Đề xuất cải thiện cụ thể.
                    4. Trả về định dạng Markdown đẹp mắt (Bullet points).
                    5. Ngôn ngữ: TIẾNG VIỆT.
                    """
                        
                        response = AIService.call_openrouter(
                            messages=[{"role": "user", "content": review_prompt}],
                            model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                            temperature=0.5
                        )
                        
                        if response and response.choices:
                            new_review = response.choices[0].message.content
                            supabase.table("chapters").update({
                                "review_content": new_review
                            }).eq("story_id", project_id).eq("chapter_number", chap_num).execute()
                            
                            db_review = new_review
                            st.session_state['trigger_ai_review'] = False
                            st.toast("Review hoàn tất!", icon="🤖")
                            st.rerun() 
                    except Exception as e:
                        st.error(f"Lỗi Review: {e}")
                        st.session_state['trigger_ai_review'] = False

            with st.expander("🤖 AI Editor Notes", expanded=True):
                if db_review:
                    st.markdown(db_review)
                    if st.button("🗑️ Xóa Review", key="del_rev", use_container_width=True):
                         supabase.table("chapters").update({"review_content": ""}).eq("story_id", project_id).eq("chapter_number", chap_num).execute()
                         st.rerun()
                else:
                    st.info("Chưa có nhận xét nào.")

    # --- 4. EXTRACT BIBLE (UI 2 BƯỚC: START -> SAVE) ---
    # --- XỬ LÝ EXTRACT BIBLE (SMART MODE + CHUNKING) ---
    if st.session_state.get('extract_bible_mode') and content:
        st.markdown("---")
        with st.container():
            st.subheader("📚 Trích xuất Bible (Smart Mode - Tự do)")
            
            # Kiểm tra xem đã có dữ liệu tạm (đã chạy xong bước 1) chưa
            has_data = st.session_state.get('temp_extracted_data') is not None
            
            # --- TRẠNG THÁI 1: CHƯA CHẠY -> HIỆN NÚT START ---
            if not has_data:
                st.info("💡 Hệ thống sẽ đọc hiểu văn bản, tự động phát hiện Nhân vật, Chiêu thức, Địa danh... và đặt loại (Type) theo ngữ cảnh.")
                
                # Nút kích hoạt chạy
                if st.button("▶️ Bắt đầu phân tích", type="primary"):
                    
                    # === BẮT ĐẦU LOGIC AI ===
                    progress_text = "Đang khởi động bộ não..."
                    my_bar = st.progress(0, text=progress_text)
    
                    # Hàm cắt nhỏ văn bản để tránh quá tải token
                    def chunk_text(text, chunk_size=8000): # Giảm size chút cho an toàn
                        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
                    chunks = chunk_text(content)
                    total_chunks = len(chunks)
                    all_extracted_items = []
    
                    try:
                        for i, chunk_content in enumerate(chunks):
                            my_bar.progress(int((i / total_chunks) * 90), text=f"Đang đọc hiểu phần {i+1}/{total_chunks}...")
    
                            # --- PROMPT TIẾNG VIỆT (TỪ CODE MỚI) ---
                            ext_prompt = f"""
                            NỘI DUNG (Phần {i+1}/{total_chunks}): 
                            {chunk_content}
                            
                            NHIỆM VỤ: Trích xuất các thực thể quan trọng (Nhân vật, Địa danh, Vật phẩm, Chiêu thức, Khái niệm, Sự kiện...) từ nội dung trên.
                            
                            ⛔️ YÊU CẦU ĐỊNH DẠNG (JSON BẮT BUỘC):
                            1. Trả về một JSON Object duy nhất chứa key "items".
                            2. KHÔNG viết lời dẫn, KHÔNG dùng markdown code block.
                            3. Trường "type": Hãy tự đặt tên loại thực thể bằng TIẾNG VIỆT dựa trên ngữ cảnh. 
                               (Ví dụ: "Thần Khí", "Môn Phái", "Huyết Kế", "Nhân vật phụ", "Quái thú"...) -> Đừng gò bó!
                            4. "description": Tóm tắt ngắn gọn vai trò/đặc điểm (dưới 50 từ).
                            
                            VÍ DỤ MẪU:
                            {{
                                "items": [
                                    {{ "entity_name": "Lâm Phong", "type": "Nhân vật chính", "description": "Thiếu niên xuyên không..." }},
                                    {{ "entity_name": "Hỏa Long Đao", "type": "Thần binh", "description": "Thanh đao rèn từ lửa rồng..." }}
                                ]
                            }}
                            """
                            
                            # Gọi AI với response_format json_object (An toàn hơn)
                            response = AIService.call_openrouter(
                                messages=[{"role": "user", "content": ext_prompt}],
                                model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                                temperature=0.3, # Tăng nhẹ để AI sáng tạo Type
                                max_tokens=16000,
                                response_format={"type": "json_object"} 
                            )
    
                            if response and response.choices:
                                raw_text = response.choices[0].message.content.strip()
                                
                                # Xử lý JSON
                                try:
                                    json_obj = json.loads(raw_text)
                                    chunk_items = []
                                    if "items" in json_obj:
                                        chunk_items = json_obj["items"]
                                    elif isinstance(json_obj, list):
                                        chunk_items = json_obj
                                    
                                    if chunk_items:
                                        all_extracted_items.extend(chunk_items)
                                except:
                                    # Fallback Regex nếu JSON vẫn lỗi
                                    clean_json = AIService.clean_json_text(raw_text)
                                    try:
                                        parsed = json.loads(clean_json)
                                        if isinstance(parsed, dict): all_extracted_items.extend(parsed.get('items', []))
                                        elif isinstance(parsed, list): all_extracted_items.extend(parsed)
                                    except:
                                        pass # Skip chunk này nếu lỗi quá nặng
    
                        my_bar.progress(100, text="Hoàn tất! Đang tổng hợp...")
                        time.sleep(0.5)
                        my_bar.empty()
                        
                        # LƯU VÀO SESSION STATE ĐỂ HIỂN THỊ BƯỚC 2
                        st.session_state['temp_extracted_data'] = all_extracted_items
                        st.rerun()
    
                    except Exception as e:
                        st.error(f"Lỗi hệ thống: {e}")
                
                # Nút hủy ngay từ đầu
                if st.button("Hủy bỏ"):
                    st.session_state['extract_bible_mode'] = False
                    st.rerun()
    
            # --- TRẠNG THÁI 2: ĐÃ CÓ DATA -> HIỆN BẢNG PREVIEW VÀ NÚT LƯU ---
            else:
                items = st.session_state['temp_extracted_data']
                
                if not items:
                    st.warning("⚠️ Không tìm thấy thực thể nào trong nội dung này.")
                    if st.button("Thử lại / Quét lại"):
                        st.session_state['temp_extracted_data'] = None
                        st.rerun()
                    if st.button("Đóng"):
                        st.session_state['extract_bible_mode'] = False
                        st.session_state['temp_extracted_data'] = None
                        st.rerun()
                else:
                    # Deduplicate (Loại bỏ trùng lặp dựa trên tên)
                    unique_items_dict = {}
                    for item in items:
                        name = item.get('entity_name', '').strip()
                        if name:
                            # Ưu tiên mô tả dài hơn nếu trùng tên
                            if name not in unique_items_dict:
                                unique_items_dict[name] = item
                            else:
                                if len(item.get('description', '')) > len(unique_items_dict[name].get('description', '')):
                                    unique_items_dict[name] = item
                    
                    unique_items = list(unique_items_dict.values())
                    df_preview = pd.DataFrame(unique_items)
    
                    st.success(f"✅ Tìm thấy {len(unique_items)} thực thể độc nhất!")
                    
                    with st.expander("👀 Xem trước & Kiểm tra dữ liệu", expanded=True):
                        if 'entity_name' in df_preview.columns:
                            st.dataframe(df_preview[['entity_name', 'type', 'description']], use_container_width=True)
                        else:
                            st.dataframe(df_preview, use_container_width=True)
    
                    c_save, c_cancel = st.columns([1, 1])
                    
                    with c_save:
                        # --- NÚT LƯU VỚI LOGIC FORMATTING MỚI ---
                        if st.button("💾 Lưu tất cả vào Bible", type="primary", use_container_width=True):
                            count = 0
                            prog = st.progress(0)
                            total = len(unique_items)
                            
                            for idx, item in enumerate(unique_items):
                                desc = item.get('description', '')
                                raw_name = item.get('entity_name', 'Unknown')
                                
                                # 1. Lấy Type tiếng Việt AI tạo ra (Vd: "Thần binh")
                                raw_type_str = item.get('type', 'Khác').strip()
                                
                                # 2. Format Type: Viết hoa + Nối gạch dưới (Vd: "THẦN_BINH")
                                formatted_type = raw_type_str.upper().replace(" ", "_")
                                
                                # 3. Gắn Tag: Tự động thêm [TYPE] vào trước tên
                                if not raw_name.startswith("["):
                                    final_name = f"[{formatted_type}] {raw_name}"
                                else:
                                    final_name = raw_name # Nếu đã có tag thì giữ nguyên
    
                                if desc:
                                    vec = AIService.get_embedding(desc)
                                    if vec:
                                        # Insert vào DB
                                        supabase.table("story_bible").insert({
                                            "story_id": project_id,
                                            "entity_name": final_name,
                                            "description": desc,
                                            "embedding": vec,
                                            # Lấy chapter hiện tại từ session hoặc biến toàn cục
                                            "source_chapter": st.session_state.get('current_file_num', 0) 
                                        }).execute()
                                        count += 1
                                
                                # Update thanh progress
                                prog.progress(int((idx + 1) / total * 100))
                            
                            st.balloons()
                            st.success(f"Đã lưu thành công {count} mục!")
                            
                            # Reset trạng thái về ban đầu
                            st.session_state['extract_bible_mode'] = False
                            st.session_state['temp_extracted_data'] = None
                            time.sleep(1.5)
                            st.rerun()
    
                    with c_cancel:
                        if st.button("Hủy bỏ / Làm lại", use_container_width=True):
                            st.session_state['extract_bible_mode'] = False
                            st.session_state['temp_extracted_data'] = None
                            st.rerun()
def render_bible_tab(project_id, persona):
    """Tab Bible - Knowledge base với prefix mở rộng"""
    st.header("📚 Project Bible")
    
    if not project_id:
        st.info("📁 Please select or create a project first")
        return
    
    services = init_services()
    supabase = services['supabase']
    
    # Search and filters
    col_search, col_filter, col_action = st.columns([3, 2, 1])
    
    with col_search:
        search_term = st.text_input("🔍 Search bible entries", placeholder="Search...")
    
    with col_filter:
        # Dynamic prefix filter
        bible_data_all = supabase.table("story_bible") \
            .select("entity_name") \
            .eq("story_id", project_id) \
            .execute()
        
        # Extract all unique prefixes
        all_prefixes = set()
        if bible_data_all.data:
            for entry in bible_data_all.data:
                match = re.match(r'^(\[[^\]]+\])', entry['entity_name'])
                if match:
                    all_prefixes.add(match.group(1))
        
        # Combine with default prefixes
        available_prefixes = sorted(list(set(Config.BIBLE_PREFIXES + list(all_prefixes))))
        filter_prefix = st.selectbox("Prefix", ["All"] + available_prefixes)
    
    with col_action:
        st.markdown("###")
        if st.button("➕ Add Entry", type="primary"):
            st.session_state['adding_bible_entry'] = True
    
    # Load bible data
    try:
        query = supabase.table("story_bible") \
            .select("*") \
            .eq("story_id", project_id) \
            .order("created_at", desc=True)
        
        if search_term:
            query = query.or_(f"entity_name.ilike.%{search_term}%,description.ilike.%{search_term}%")
        
        if filter_prefix != "All":
            query = query.ilike("entity_name", f"{filter_prefix}%")
        
        bible_data = query.execute().data
        
    except Exception as e:
        st.error(f"Error: {e}")
        bible_data = []
    
    # Stats
    if bible_data:
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total", len(bible_data))
        
        with col2:
            # Count by prefix
            prefix_counts = {}
            for entry in bible_data:
                match = re.match(r'^(\[[^\]]+\])', entry['entity_name'])
                prefix = match.group(1) if match else "[OTHER]"
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
            
            if prefix_counts:
                most_common = max(prefix_counts.items(), key=lambda x: x[1])
                st.metric("Most Common", most_common[0])
        
        with col3:
            chars = sum(1 for b in bible_data if '[CHARACTER]' in b.get('entity_name', ''))
            st.metric("Characters", chars)
        
        with col4:
            rules = sum(1 for b in bible_data if '[RULE]' in b.get('entity_name', ''))
            st.metric("Rules", rules)
    
    # Add entry form với prefix tùy chỉnh
    if st.session_state.get('adding_bible_entry'):
        st.markdown("---")
        st.subheader("Add New Bible Entry")
        
        with st.form("add_bible_form"):
            col_type, col_custom = st.columns([1, 2])
            
            with col_type:
                entry_type = st.selectbox(
                    "Entry Type",
                    Config.BIBLE_PREFIXES,
                    format_func=lambda x: x.replace("[", "").replace("]", "")
                )
                custom_prefix = st.checkbox("Custom Prefix")
            
            with col_custom:
                if custom_prefix:
                    custom_prefix_input = st.text_input("Custom Prefix (with brackets)", value="[CUSTOM]")
                    entry_type = custom_prefix_input
            
            name = st.text_input("Name/Title")
            description = st.text_area("Description", height=150)
            
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.form_submit_button("💾 Save Entry", type="primary"):
                    if name and description and entry_type:
                        entity_name = f"{entry_type} {name}"
                        
                        # Get embedding
                        vec = AIService.get_embedding(f"{entity_name}: {description}")
                        
                        if vec:
                            supabase.table("story_bible").insert({
                                "story_id": project_id,
                                "entity_name": entity_name,
                                "description": description,
                                "embedding": vec
                            }).execute()
                            
                            st.success("Entry added!")
                            st.session_state['adding_bible_entry'] = False
                            st.rerun()
                        else:
                            st.error("Failed to create embedding")
            
            with col_cancel:
                if st.form_submit_button("❌ Cancel"):
                    st.session_state['adding_bible_entry'] = False
                    st.rerun()
    
    # Display entries với tính năng nâng cao
    st.markdown("---")
    
    if bible_data:
        # Multi-select for batch operations
        selections = st.multiselect(
            f"Select entries for batch operations ({len(bible_data)} total):",
            [f"{b['entity_name']} (ID: {b['id']})" for b in bible_data],
            key="bible_selections"
        )
        
        if selections:
            selected_ids = []
            selected_entries = []
            
            for sel in selections:
                # Extract ID from selection string
                match = re.search(r'ID: (\d+)', sel)
                if match:
                    entry_id = int(match.group(1))
                    selected_ids.append(entry_id)
                    # Find the entry
                    for entry in bible_data:
                        if entry['id'] == entry_id:
                            selected_entries.append(entry)
                            break
            
            col_del, col_merge, col_export = st.columns(3)
            
            with col_del:
                if st.button("🗑️ Delete Selected", use_container_width=True):
                    supabase.table("story_bible") \
                        .delete() \
                        .in_("id", selected_ids) \
                        .execute()
                    st.success(f"Deleted {len(selected_ids)} entries")
                    time.sleep(1)
                    st.rerun()
            
            with col_merge:
                if st.button("🧬 AI Merge Selected", use_container_width=True):
                    if len(selected_entries) >= 2:
                        items_text = "\n".join([f"- {e['description']}" for e in selected_entries])
                       prompt_merge = f"""
                            Hãy hợp nhất các mục thông tin dưới đây thành một mục duy nhất, mạch lạc, đầy đủ chi tiết:
                            
                            {items_text}
                            
                            Yêu cầu: Viết lại bằng Tiếng Việt, giữ nguyên các thuật ngữ quan trọng.
                            """
                        
                        try:
                            response = AIService.call_openrouter(
                                messages=[{"role": "user", "content": prompt_merge}],
                                model=Config.ROUTER_MODEL,
                                temperature=0.3,
                                max_tokens=4000
                            )
                            
                            merged_text = response.choices[0].message.content
                            
                            # Create new merged entry
                            vec = AIService.get_embedding(merged_text)
                            if vec:
                                supabase.table("story_bible").insert({
                                    "story_id": project_id,
                                    "entity_name": f"[MERGED] {datetime.now().strftime('%Y%m%d')}",
                                    "description": merged_text,
                                    "embedding": vec
                                }).execute()
                                
                                # Delete old entries
                                supabase.table("story_bible") \
                                    .delete() \
                                    .in_("id", selected_ids) \
                                    .execute()
                                
                                st.success("Merged successfully!")
                                time.sleep(1)
                                st.rerun()
                        
                        except Exception as e:
                            st.error(f"Merge error: {e}")
            
            with col_export:
                if st.button("📤 Export Selected", use_container_width=True):
                    export_data = []
                    for entry in selected_entries:
                        export_data.append({
                            "entity_name": entry['entity_name'],
                            "description": entry['description'],
                            "created_at": entry['created_at']
                        })
                    
                    df_export = pd.DataFrame(export_data)
                    st.download_button(
                        label="📥 Download as CSV",
                        data=df_export.to_csv(index=False).encode('utf-8'),
                        file_name=f"bible_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
        
        # Display individual entries
        for entry in bible_data:
            with st.expander(f"**{entry['entity_name']}**", expanded=False):
                st.markdown(entry.get('description', ''))
                
                col_edit, col_delete, col_vector = st.columns(3)
                
                with col_edit:
                    if st.button("✏️ Edit", key=f"edit_{entry['id']}"):
                        st.session_state['editing_bible_entry'] = entry
                
                with col_delete:
                    if st.button("🗑️ Delete", key=f"delete_{entry['id']}"):
                        supabase.table("story_bible").delete().eq("id", entry['id']).execute()
                        st.rerun()
                
                with col_vector:
                    if st.button("🔍 Similar", key=f"similar_{entry['id']}"):
                        st.session_state['find_similar_to'] = entry['id']
        
        # Edit entry form
        if st.session_state.get('editing_bible_entry'):
            entry = st.session_state['editing_bible_entry']
            
            st.markdown("---")
            st.subheader(f"Edit: {entry['entity_name']}")
            
            with st.form("edit_bible_form"):
                new_name = st.text_input("Entity Name", value=entry['entity_name'])
                new_desc = st.text_area("Description", value=entry['description'], height=150)
                
                if st.form_submit_button("💾 Update"):
                    vec = AIService.get_embedding(f"{new_name}: {new_desc}")
                    if vec:
                        supabase.table("story_bible").update({
                            "entity_name": new_name,
                            "description": new_desc,
                            "embedding": vec
                        }).eq("id", entry['id']).execute()
                        
                        st.success("Updated!")
                        del st.session_state['editing_bible_entry']
                        st.rerun()
                
                if st.form_submit_button("❌ Cancel"):
                    del st.session_state['editing_bible_entry']
                    st.rerun()
        
        # Find similar entries
        if st.session_state.get('find_similar_to'):
            entry_id = st.session_state['find_similar_to']
            
            # Find the entry
            target_entry = None
            for entry in bible_data:
                if entry['id'] == entry_id:
                    target_entry = entry
                    break
            
            if target_entry:
                st.markdown("---")
                st.subheader(f"Similar to: {target_entry['entity_name']}")
                
                # Search for similar entries
                search_text = f"{target_entry['entity_name']} {target_entry['description'][:100]}"
                similar_results = HybridSearch.smart_search_hybrid_raw(search_text, project_id, top_k=5)
                
                # Filter out the target itself
                similar_results = [r for r in similar_results if r['id'] != entry_id]
                
                if similar_results:
                    for result in similar_results:
                        with st.expander(f"**{result['entity_name']}** (Similarity)", expanded=False):
                            st.markdown(result['description'][:200] + "...")
                
                if st.button("Close Similar Search"):
                    del st.session_state['find_similar_to']
                    st.rerun()
    
    else:
        st.info("No bible entries found. Add some to build your project's knowledge base!")
    
    # Danger Zone
    st.markdown("---")
    with st.expander("💀 Danger Zone", expanded=False):
        # 1. Nếu chưa bấm nút xóa lần đầu -> Hiện nút xóa
        if not st.session_state.get('confirm_delete_all_bible'):
            if st.button("💣 Clear All Bible Entries", type="secondary", use_container_width=True):
                st.session_state['confirm_delete_all_bible'] = True
                st.rerun()
        
        # 2. Nếu đã bấm -> Hiện cảnh báo và 2 nút Yes/No
        else:
            st.warning("⚠️ CẢNH BÁO: Hành động này sẽ xóa sạch toàn bộ dữ liệu Bible và không thể khôi phục. Bạn chắc chứ?")
            
            col_yes, col_no = st.columns(2)
            
            # Nút Hủy
            with col_no:
                if st.button("❌ Thôi, giữ lại", use_container_width=True):
                    st.session_state['confirm_delete_all_bible'] = False
                    st.rerun()
            
            # Nút Xác nhận xóa thật
            with col_yes:
                if st.button("✅ Tôi chắc chắn. Xóa!", type="primary", use_container_width=True):
                    # Thực hiện lệnh xóa
                    supabase.table("story_bible") \
                        .delete() \
                        .eq("story_id", project_id) \
                        .execute()
                    
                    st.success("Đã xóa sạch Bible!")
                    # Reset trạng thái
                    st.session_state['confirm_delete_all_bible'] = False
                    time.sleep(1)
                    st.rerun()

def render_cost_tab():
    """Tab Cost Management"""
    st.header("💰 Cost Management")
    
    if 'user' not in st.session_state:
        st.warning("Please login")
        return
    
    user_id = st.session_state.user.id
    budget = CostManager.get_user_budget(user_id)
    
    # Budget overview
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Total Credits",
            f"${budget.get('total_credits', 0):.2f}"
        )
    
    with col2:
        st.metric(
            "Used Credits",
            f"${budget.get('used_credits', 0):.2f}",
            delta=f"-${budget.get('used_credits', 0):.2f}"
        )
    
    with col3:
        remaining = budget.get('remaining_credits', 0)
        st.metric(
            "Remaining",
            f"${remaining:.2f}"
        )
    
    # Progress bar
    usage_percent = (budget.get('used_credits', 0) / budget.get('total_credits', 100)) * 100
    st.progress(min(usage_percent / 100, 1.0))
    
    # Model cost comparison
    st.markdown("---")
    st.subheader("📊 Model Cost Comparison")
    
    # Show top 10 models by cost
    model_costs = []
    for model, costs in Config.MODEL_COSTS.items():
        if model in [m for models in Config.AVAILABLE_MODELS.values() for m in models]:
            avg_cost = (costs['input'] + costs['output']) / 2
            model_costs.append({
                "Model": model.split('/')[-1],
                "Input Cost": f"${costs['input']}/M",
                "Output Cost": f"${costs['output']}/M",
                "Avg Cost": f"${avg_cost:.2f}/M"
            })
    
    model_costs.sort(key=lambda x: float(x['Avg Cost'].replace('$', '').replace('/M', '')))
    
    df = pd.DataFrame(model_costs)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Usage history
    st.markdown("---")
    st.subheader("📈 Usage History")
    
    try:
        services = init_services()
        supabase = services['supabase']
        
        # Get chat history with metadata
        chat_history = supabase.table("chat_history") \
            .select("created_at, metadata") \
            .eq("story_id", st.session_state.get('project_id', '')) \
            .order("created_at", desc=True) \
            .limit(100) \
            .execute()
        
        if chat_history.data:
            costs = []
            for chat in chat_history.data:
                if chat.get('metadata') and 'cost' in chat['metadata']:
                    try:
                        cost_str = chat['metadata']['cost']
                        if cost_str.startswith('$'):
                            cost = float(cost_str[1:])
                            costs.append({
                                'date': chat['created_at'][:10],
                                'cost': cost
                            })
                    except:
                        pass
            
            if costs:
                df_costs = pd.DataFrame(costs)
                df_grouped = df_costs.groupby('date').sum().reset_index()
                st.line_chart(df_grouped.set_index('date'))
            else:
                st.info("No cost data available in recent history")
        else:
            st.info("No chat history available")
    
    except Exception as e:
        st.error(f"Error loading usage history: {e}")
    
    # Add credits section
    st.markdown("---")
    st.subheader("💳 Add Credits")
    
    with st.form("add_credits"):
        amount = st.select_slider(
            "Amount to add",
            options=[10, 25, 50, 100, 200, 500],
            value=50
        )
        
        if st.form_submit_button("Add Credits", type="primary"):
            # In real app, integrate with payment provider
            st.info(f"💳 Payment integration would add ${amount} to your account")
            st.info("For now, credits are simulated")

def render_settings_tab():
    """Tab Settings"""
    st.header("⚙️ Settings")
    
    tab1, tab2, tab3 = st.tabs(["Account", "AI", "Appearance"])
    
    with tab1:
        st.subheader("Account Settings")
        
        if 'user' in st.session_state:
            user_email = st.session_state.user.email
            st.info(f"Logged in as: **{user_email}**")
        
        # Change password
        with st.form("change_password"):
            st.subheader("Change Password")
            
            current_pass = st.text_input("Current Password", type="password")
            new_pass = st.text_input("New Password", type="password")
            confirm_pass = st.text_input("Confirm New Password", type="password")
            
            if st.form_submit_button("Change Password", type="primary"):
                if new_pass == confirm_pass:
                    st.success("Password change would be implemented here")
                else:
                    st.error("Passwords don't match")
    
    with tab2:
        st.subheader("AI Settings")
        
        # Default model preferences
        st.selectbox(
            "Default Model Category",
            list(Config.AVAILABLE_MODELS.keys()),
            index=1,
            key="default_category"
        )
        
        # Model blacklist
        st.multiselect(
            "Exclude Models",
            [model for models in Config.AVAILABLE_MODELS.values() for model in models],
            key="model_blacklist"
        )
        
        # AI Behavior
        st.subheader("AI Behavior")
        
        col_behavior1, col_behavior2 = st.columns(2)
        
        with col_behavior1:
            st.checkbox("Auto-switch to cheaper model when low on credits", value=True, key="auto_switch")
            st.checkbox("Enable rule mining from chat", value=True, key="enable_rule_mining")
        
        with col_behavior2:
            st.checkbox("Prefer faster models for short responses", value=True, key="prefer_fast")
            st.checkbox("Always include mandatory rules in context", value=True, key="include_rules")
        
        # Custom prefixes
        st.subheader("Bible Prefixes")
        st.caption("Custom prefixes for bible entries (one per line)")
        
        custom_prefixes = st.text_area(
            "Custom Prefixes",
            value="\n".join(Config.BIBLE_PREFIXES),
            height=150,
            help="Add custom prefixes in format [PREFIX]. One per line."
        )
        
        if st.button("Save AI Preferences", type="primary"):
            # Update prefixes
            if custom_prefixes:
                prefixes = [p.strip() for p in custom_prefixes.split('\n') if p.strip()]
                # Ensure [RULE] is always included
                if "[RULE]" not in prefixes:
                    prefixes.append("[RULE]")
                Config.BIBLE_PREFIXES = list(set(prefixes))
            
            st.success("Preferences saved!")
    
    with tab3:
        st.subheader("Appearance")
        
        # Theme selection
        theme = st.selectbox(
            "Theme",
            ["Light", "Dark", "Auto"],
            index=2
        )
        
        # Font size
        font_size = st.select_slider(
            "Font Size",
            options=["Small", "Medium", "Large"],
            value="Medium"
        )
        
        # Chat density
        chat_density = st.select_slider(
            "Chat Density",
            options=["Compact", "Comfortable", "Spacious"],
            value="Comfortable"
        )
        
        if st.button("Apply Appearance Settings", type="primary"):
            st.success("Settings applied! (Refresh to see changes)")

# ==========================================
# 🚀 13. MAIN APP
# ==========================================
def main():
    """Hàm chính của ứng dụng"""
    
    session_manager = SessionManager()
    
    # --- LOGIC MỚI ĐỂ XỬ LÝ F5 VÀ LOGOUT ---
    
    # Nếu đang logout, xóa cờ và hiện form đăng nhập luôn
    if st.session_state.get('logging_out'):
        # Xóa cờ để lần sau đăng nhập lại bình thường
        if 'logging_out' in st.session_state:
            del st.session_state['logging_out']
        session_manager.render_login_form()
        return

    # Check login
    is_logged_in = session_manager.check_login()
    
    # Nếu chưa login, hiển thị form
    if not is_logged_in:
        # Mẹo: CookieManager mất khoảng 0.5s để load sau khi F5. 
        # Nếu muốn chặn nháy form hoàn toàn, bạn có thể uncomment dòng dưới, 
        # nhưng nó sẽ làm app chậm hơn xíu.
        time.sleep(1) 
        
        # Check lại lần nữa cho chắc sau khi chờ
        # if session_manager.cookie_manager.get("supabase_access_token"):
        #     st.rerun()
            
        session_manager.render_login_form()
        return
    
    # Validate config
    if not Config.validate():
        st.stop()
    
    # Initialize services
    services = init_services()
    if not services:
        st.error("Failed to initialize services. Please check your configuration.")
        st.stop()
    
    # Render sidebar
    project_id, persona = render_sidebar(session_manager)
    
    # Main content header
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.get('current_project'):
            project_name = st.session_state.current_project.get('title', 'Untitled')
            st.title(f"{persona['icon']} {project_name}")
            st.caption(f"{persona['role']} • Project Management")
        else:
            st.title("🚀 V-Universe AI Hub Pro")
            st.caption("Select or create a project to get started")
    
    with col2:
        # Quick stats
        if 'user' in st.session_state:
            budget = CostManager.get_user_budget(st.session_state.user.id)
            st.metric("Available Credits", f"${budget.get('remaining_credits', 0):.2f}")
    
    # Main tabs
    tabs = st.tabs([
        "📊 Dashboard",
        "💬 Smart Chat",
        "✍️ Workstation", 
        "📚 Project Bible",
        "💰 Cost Management",
        "⚙️ Settings"
    ])
    
    # Tab routing
    with tabs[0]:
        render_dashboard_tab(project_id)
    
    with tabs[1]:
        render_chat_tab(project_id, persona)
    
    with tabs[2]:
        render_workstation_tab(project_id, persona)
    
    with tabs[3]:
        render_bible_tab(project_id, persona)
    
    with tabs[4]:
        render_cost_tab()
    
    with tabs[5]:
        render_settings_tab()
    
    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666; padding: 20px;'>
            <p>🚀 V-Universe AI Hub Pro • Powered by OpenRouter AI & Supabase • v3.0</p>
            <p style='font-size: 12px;'>Hybrid Search • Rule Mining • Strict Mode • 20+ AI models • Intelligent context management</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()




































