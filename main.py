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
            "openai/gpt-4-turbo-preview",
            "openai/gpt-4",
            "anthropic/claude-3-opus",
            "anthropic/claude-3-sonnet",
            "google/gemini-pro-1.5"
        ],
        "⚡ Fast & Balanced": [
            "openai/gpt-3.5-turbo",
            "openai/gpt-3.5-turbo-16k",
            "anthropic/claude-3-haiku",
            "google/gemini-flash-1.5",
            "mistralai/mixtral-8x7b-instruct"
        ],
        "💰 Cost Effective": [
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.1-8b-instruct",
            "qwen/qwen-2.5-7b-instruct",
            "microsoft/phi-3-medium-128k-instruct",
            "google/gemini-flash-1.5-8b"
        ],
        "🔬 Specialized": [
            "cohere/command-r-plus",
            "perplexity/llama-3-sonar-small-128k-chat",
            "nousresearch/nous-hermes-2-mixtral-8x7b-dpo",
            "cognitivecomputations/dolphin-mixtral-8x7b"
        ]
    }
    
    # Model Costs (USD per 1M tokens)
    MODEL_COSTS = {
        # OpenAI
        "openai/gpt-4-turbo-preview": {"input": 10.00, "output": 30.00},
        "openai/gpt-4": {"input": 30.00, "output": 60.00},
        "openai/gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        "openai/gpt-3.5-turbo-16k": {"input": 1.50, "output": 2.00},
        
        # Anthropic
        "anthropic/claude-3-opus": {"input": 15.00, "output": 75.00},
        "anthropic/claude-3-sonnet": {"input": 3.00, "output": 15.00},
        "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
        
        # Google
        "google/gemini-pro-1.5": {"input": 1.25, "output": 2.50},
        "google/gemini-flash-1.5": {"input": 0.075, "output": 0.30},
        "google/gemini-flash-1.5-8b": {"input": 0.045, "output": 0.18},
        
        # Open Source
        "deepseek/deepseek-chat": {"input": 0.14, "output": 0.28},
        "meta-llama/llama-3.1-8b-instruct": {"input": 0.18, "output": 0.18},
        "mistralai/mixtral-8x7b-instruct": {"input": 0.24, "output": 0.24},
        "qwen/qwen-2.5-7b-instruct": {"input": 0.12, "output": 0.12},
        "microsoft/phi-3-medium-128k-instruct": {"input": 0.10, "output": 0.10},
        
        # Others
        "cohere/command-r-plus": {"input": 3.00, "output": 15.00},
        "perplexity/llama-3-sonar-small-128k-chat": {"input": 0.20, "output": 0.20},
        "nousresearch/nous-hermes-2-mixtral-8x7b-dpo": {"input": 0.30, "output": 0.30},
        "cognitivecomputations/dolphin-mixtral-8x7b": {"input": 0.25, "output": 0.25}
    }
    
    # Default settings
    DEFAULT_MODEL = "anthropic/claude-3.5-haiku"
    EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"
    ROUTER_MODEL = "deepseek/deepseek-chat"
    
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
        "low": 4000,
        "medium": 8000,
        "high": 16000,
        "max": 32000
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
        max_tokens: int = 1000,
        stream: bool = False
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
                stream=stream
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
    def ai_router_pro_v2(user_prompt: str, chat_history_text: str) -> Dict:
        """Router V2: Phân tích Intent và Target Files"""
        router_prompt = f"""
        Đóng vai Project Coordinator. Phân tích User Input và Lịch sử Chat.
        
        LỊCH SỬ CHAT:
        {chat_history_text}
        
        USER INPUT: "{user_prompt}"
        
        PHÂN LOẠI INTENT:
        1. "read_full_content": Khi user muốn "Sửa", "Refactor", "Review", "So sánh", "Viết tiếp", "Kiểm tra code/văn" -> Cần đọc NGUYÊN VĂN FILE.
        2. "search_bible": Khi user hỏi thông tin chung, quy định, tóm tắt, tra cứu khái niệm, hay dùng từ khóa "Bible" -> Tra cứu Bible (Vector).
        3. "chat_casual": Chào hỏi, chém gió không cần context.
        4. "mixed_context": Cần cả file content và bible context.
        
        OUTPUT JSON ONLY:
        {{
            "intent": "read_full_content" | "search_bible" | "chat_casual" | "mixed_context",
            "target_files": ["tên file 1", "tên file 2", "tên chương..."], 
            "target_bible_entities": ["entity1", "entity2"],
            "reason": "Lý do ngắn gọn",
            "rewritten_query": "Viết lại câu hỏi cho rõ nghĩa (thay thế 'nó', 'file này' bằng tên thực thể)"
        }}
        """
        
        messages = [
            {"role": "system", "content": "You are Router AI. Return only JSON."},
            {"role": "user", "content": router_prompt}
        ]
        
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.1,
                max_tokens=500
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
            \n\n‼️ STRICT MODE ACTIVATED:
            1. ONLY answer based on information in CONTEXT.
            2. Absolutely DO NOT use external knowledge (training data) to fabricate.
            3. If no information is available, respond: "Project data does not contain this information."
            4. You MUST read the [CONTEXT] or [KNOWLEDGE BASE] section if available.
            5. If User asks about "history", "what was said", "check bible", prioritize extracting information from [CONTEXT] and answer accurately.
            6. DO NOT refuse to answer factual data just because of character personality.
            7. "Bible" mentioned by User is the project Database, not metaphorical.
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
        You are "Rule Extractor". Task: Detect User Preferences through conversation.
        
        CONVERSATION:
        - User: "{user_prompt}"
        - AI: (Previous response...)
        
        ANALYZE IF USER IS:
        1. Complaining about length/style (e.g., "too long", "just code", "don't explain").
        2. Giving mandatory format (e.g., "code only", "use JSON").
        3. Correcting AI (e.g., "wrong", "should do this").
        
        IF YES, extract into 1 CONCISE RULE (imperative mood).
        Example:
        - Input: "Too long, just code" -> Rule: "When user asks for code -> Provide only Code Block, no lengthy explanations."
        
        IF NOT (just continuation, additional questions, thanks), return "NO_RULE".
        
        Output Text Only.
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
        New Rule: "{new_rule_content}"
        Existing Rules in DB: "{similar_rules_str}"
        
        Compare relationships:
        - CONFLICT: Direct contradiction (e.g., Old says A, New says not A).
        - MERGE: Same topic but New is more detailed/supplementary.
        - NEW: Different topic.
        
        OUTPUT JSON:
        {{
            "status": "CONFLICT" | "MERGE" | "NEW",
            "existing_rule_summary": "Brief summary of existing rules",
            "reason": "Reason",
            "merged_content": "Complete merged content (if MERGE). If CONFLICT/NEW leave null."
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
                max_tokens=500
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
        You are Meeting Secretary ({persona_role}).
        Task: Read conversation below and FILTER OUT NOISE.
        Only retain and SUMMARIZE valuable information (Fact, Idea, Decision).
        CHAT LOG: {chat_text}
        OUTPUT: Return concise summary (50-100 words). If noise, return "NO_INFO".
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
                max_tokens=200
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
        st.markdown("<h3 style='text-align: center;'>🚀 V-Universe AI Pro</h3>", unsafe_allow_html=True)
        
        if 'user' in st.session_state and st.session_state.user:
            user_email = st.session_state.user.email
            st.markdown(f"<p style='text-align: center;'><strong>👤 {user_email.split('@')[0]}</strong></p>", unsafe_allow_html=True)
            
            # User stats
            budget = CostManager.get_user_budget(st.session_state.user.id)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "💰 Credits",
                    f"${budget.get('remaining_credits', 0):.2f}",
                    delta=f"-${budget.get('used_credits', 0):.2f}"
                )
            with col2:
                usage_percent = (budget.get('used_credits', 0) / budget.get('total_credits', 100)) * 100
                st.metric(
                    "Usage",
                    f"{usage_percent:.1f}%"
                )
            
            st.markdown("---")
            
            # Project selection
            st.subheader("📂 Projects")
            
            services = init_services()
            supabase = services['supabase']
            
            projects = supabase.table("stories") \
                .select("*") \
                .eq("user_id", st.session_state.user.id) \
                .execute()
            
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
                st.info(f"{persona['icon']} **{proj_type} Mode**")
                
            else:
                # Create new project
                if st.button("Create New Project", type="primary"):
                    st.session_state['show_new_project'] = True
                
                if st.session_state.get('show_new_project'):
                    with st.form("new_project_form"):
                        title = st.text_input("Project Name")
                        category = st.selectbox(
                            "Category",
                            list(PersonaSystem.PERSONAS.keys())
                        )
                        
                        if st.form_submit_button("Create"):
                            if title:
                                supabase.table("stories").insert({
                                    "title": title,
                                    "category": category,
                                    "user_id": st.session_state.user.id
                                }).execute()
                                st.success("Project created!")
                                st.rerun()
                    st.stop()
                
                proj_id = None
                persona = PersonaSystem.PERSONAS["Writer"]
            
            # AI Settings Section
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
            )
            
            st.session_state['selected_model'] = selected_model
            
            # Advanced settings
            with st.expander("Advanced Settings"):
                st.session_state['temperature'] = st.slider(
                    "Temperature",
                    min_value=0.0,
                    max_value=1.0,
                    value=persona.get('temperature', 0.7),
                    step=0.1
                )
                
                st.session_state['context_size'] = st.select_slider(
                    "Context Size",
                    options=["low", "medium", "high", "max"],
                    value="medium"
                )
            
            st.markdown("---")
            
            # Quick Actions
            st.subheader("⚡ Quick Actions")
            
            if st.button("🔄 Refresh Session", use_container_width=True):
                st.rerun()
            
            if st.button("📊 Dashboard", use_container_width=True):
                st.session_state['active_tab'] = "Dashboard"
                st.rerun()
            
            if st.button("⚙️ Settings", use_container_width=True):
                st.session_state['active_tab'] = "Settings"
                st.rerun()
            
            # Logout button
            st.markdown("---")
            if st.button("🚪 Logout", use_container_width=True, type="secondary"):
                # 1. Bật cờ logout
                st.session_state['logging_out'] = True
        
                # 2. Xóa Cookie (Giữ nguyên)
                try:
                    session_manager.cookie_manager.delete("supabase_access_token")
                    session_manager.cookie_manager.delete("supabase_refresh_token")
                except:
                    pass

                # 3. SỬA ĐOẠN NÀY: Thay vì st.session_state.clear(), hãy dùng vòng lặp
                # Xóa tất cả session state TRỪ biến 'logging_out'
                for key in list(st.session_state.keys()):
                    if key != 'logging_out':  # <--- GIỮ LẠI CÁI NÀY
                        del st.session_state[key]
        
                st.success("Logged out successfully!")
                time.sleep(1)
                st.rerun()
            
            return proj_id, persona
        
        else:
            st.warning("Please login")
            st.stop()

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
                
                router_out = SmartAIRouter.ai_router_pro_v2(prompt, recent_history_text)
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

CONTEXT INFORMATION:
{context_text}

INSTRUCTIONS:
- Answer based on context when available
- Be helpful and concise
- Current mode: {persona['role']}
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
                        max_tokens=persona.get('max_tokens', 1500),
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

def render_workstation_tab(project_id, persona):
    """Tab Workstation - Quản lý files với tính năng extract Bible"""
    st.header("✍️ Writing Workstation")
    
    if not project_id:
        st.info("📁 Please select or create a project first")
        return
    
    services = init_services()
    supabase = services['supabase']
    
    # File management
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Load files
        files = supabase.table("chapters") \
            .select("chapter_number, title") \
            .eq("story_id", project_id) \
            .order("chapter_number") \
            .execute()
        
        file_options = {}
        for f in files.data:
            display_name = f"📄 #{f['chapter_number']}"
            if f['title']:
                display_name += f": {f['title']}"
            file_options[display_name] = f['chapter_number']
        
        selected_file = st.selectbox(
            "Select File",
            ["+ New File"] + list(file_options.keys())
        )
        
        if selected_file == "+ New File":
            chap_num = len(files.data) + 1
            db_content = ""
            db_title = f"Chapter {chap_num}"
        else:
            chap_num = file_options[selected_file]
            
            # Load file content
            try:
                res = supabase.table("chapters") \
                    .select("content, title, review_content") \
                    .eq("story_id", project_id) \
                    .eq("chapter_number", chap_num) \
                    .execute()
                
                if res.data:
                    db_content = res.data[0].get('content', '')
                    db_title = res.data[0].get('title', f'Chapter {chap_num}')
                    db_review = res.data[0].get('review_content', '')
                else:
                    db_content = ""
                    db_title = f"Chapter {chap_num}"
                    db_review = ""
            except:
                db_content = ""
                db_title = f"Chapter {chap_num}"
                db_review = ""
    
    with col2:
        st.markdown("### 🔧 Tools")
        
        # Quick actions
        if st.button("🚀 AI Review", use_container_width=True, type="primary"):
            if st.session_state.get('current_file_content'):
                st.session_state['ai_review_mode'] = True
        
        if st.button("💾 Save", use_container_width=True):
            if st.session_state.get('current_file_content') is not None:
                supabase.table("chapters").upsert({
                    "story_id": project_id,
                    "chapter_number": chap_num,
                    "title": st.session_state.get('current_file_title', db_title),
                    "content": st.session_state.current_file_content
                }).execute()
                st.success("✅ Saved successfully!")
        
        if st.button("📥 Extract to Bible", use_container_width=True):
            if st.session_state.get('current_file_content'):
                st.session_state['extract_bible_mode'] = True
    
    # Main editor
    st.markdown("---")
    
    col_editor, col_stats = st.columns([3, 1])
    
    with col_editor:
        st.subheader("📝 Editor")
        
        # File title
        file_title = st.text_input(
            "File Title",
            value=db_title,
            key=f"file_title_{chap_num}",
            placeholder="Enter file title..."
        )
        
        st.session_state['current_file_title'] = file_title
        
        # Content editor
        content = st.text_area(
            "Content",
            value=db_content,
            height=400,
            key=f"file_content_{chap_num}",
            placeholder="Start writing here..."
        )
        
        st.session_state['current_file_content'] = content
        st.session_state['current_file_num'] = chap_num
    
    with col_stats:
        st.subheader("📊 Statistics")
        
        if content:
            words = len(content.split())
            chars = len(content)
            paragraphs = len([p for p in content.split('\n') if p.strip()])
            
            st.metric("Words", words)
            st.metric("Characters", chars)
            st.metric("Paragraphs", paragraphs)
            
            # Read time estimation
            read_time = words / 200  # Average reading speed
            st.metric("Read Time", f"{read_time:.1f} min")
    
    # AI Review Section
    if st.session_state.get('ai_review_mode') and content:
        st.markdown("---")
        st.subheader("🤖 AI Review")
        
        with st.spinner("Analyzing..."):
            context = HybridSearch.smart_search_hybrid(content[:500], project_id)
            rules = ContextManager.get_mandatory_rules(project_id)
            
            review_prompt = f"""
            RULES: {rules}
            TITLE: {file_title}
            CONTEXT: {context}
            CONTENT: {content}
            TASK: {persona.get('review_prompt', 'Review this content')}
            """
            
            try:
                response = AIService.call_openrouter(
                    messages=[{"role": "user", "content": review_prompt}],
                    model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                    temperature=0.5,
                    max_tokens=1000
                )
                
                review_text = response.choices[0].message.content
                
                with st.expander("📝 Review Results", expanded=True):
                    st.markdown(review_text)
                    
                    if st.button("💾 Save Review to DB"):
                        supabase.table("chapters") \
                            .update({"review_content": review_text}) \
                            .eq("story_id", project_id) \
                            .eq("chapter_number", chap_num) \
                            .execute()
                        st.success("Review saved!")
                        st.session_state['ai_review_mode'] = False
                        st.rerun()
                
            except Exception as e:
                st.error(f"Review failed: {e}")
    
    # Bible Extraction Section
    if st.session_state.get('extract_bible_mode') and content:
        st.markdown("---")
        st.subheader("📚 Extract to Bible")
        
        with st.spinner("Extracting entities..."):
            meta_desc = "Brief description of PURPOSE, MAIN EVENTS and OUTCOME of this File."
            if st.session_state.get('persona') == "Coder":
                meta_desc = "Describe PURPOSE, MAIN COMPONENTS (Functions/Classes) and INPUT/OUTPUT."
            
            extra_req = f"""
            MANDATORY REQUIREMENT: Add to beginning of JSON a summary item:
            - entity_name: "[META] {file_title if file_title else f'File {chap_num}'}"
            - type: "Overview"
            - description: "{meta_desc}"
            """
            
            ext_prompt = f"""
            TITLE: {file_title}
            CONTENT: {content}
            TASK: {persona.get('extractor_prompt', 'Extract key entities as JSON')}
            {extra_req}
            
            Return JSON array of objects with fields: entity_name, type, description
            """
            
            try:
                response = AIService.call_openrouter(
                    messages=[{"role": "user", "content": ext_prompt}],
                    model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                    temperature=0.3,
                    max_tokens=1500
                )
                
                extract_text = response.choices[0].message.content
                clean_json = AIService.clean_json_text(extract_text)
                
                try:
                    data = json.loads(clean_json)
                    
                    with st.expander("Preview Extraction", expanded=True):
                        st.dataframe(
                            pd.DataFrame(data)[['entity_name', 'type', 'description']],
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        if st.button("💾 Save to Bible"):
                            for item in data:
                                vec = AIService.get_embedding(f"{item.get('description')}")
                                if vec:
                                    supabase.table("story_bible").insert({
                                        "story_id": project_id,
                                        "entity_name": item['entity_name'],
                                        "description": item['description'],
                                        "embedding": vec,
                                        "source_chapter": chap_num
                                    }).execute()
                            
                            st.success("Saved to Bible!")
                            st.session_state['extract_bible_mode'] = False
                            st.rerun()
                
                except Exception as e:
                    st.error(f"JSON parse error: {e}")
                    st.code(extract_text, language="json")
            
            except Exception as e:
                st.error(f"Extraction failed: {e}")

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
                        prompt_merge = f"Merge these items into one coherent entry:\n{items_text}"
                        
                        try:
                            response = AIService.call_openrouter(
                                messages=[{"role": "user", "content": prompt_merge}],
                                model=Config.ROUTER_MODEL,
                                temperature=0.3,
                                max_tokens=500
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
        if st.button("💣 Clear All Bible Entries", type="secondary", use_container_width=True):
            if st.checkbox("I understand this will delete ALL bible entries for this project"):
                supabase.table("story_bible") \
                    .delete() \
                    .eq("story_id", project_id) \
                    .execute()
                st.success("All bible entries cleared!")
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
    
    df = pd.DataFrame(model_costs[:10])
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









