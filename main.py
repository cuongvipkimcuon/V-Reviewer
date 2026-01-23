import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import json
import re
import pandas as pd
import time
from datetime import datetime
import extra_streamlit_components as stx
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded, ServiceUnavailable
from persona import PERSONAS

# ==========================================
# 🎨 1. CẤU HÌNH & CSS
# ==========================================
st.set_page_config(page_title="V-Universe Hub", page_icon="🌌", layout="wide")

st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: #f0f2f6; border-radius: 5px; }
    .stTabs [aria-selected="true"] { background-color: #ff4b4b; color: white; }
    div[data-testid="stExpander"] { background-color: #f8f9fa; border-radius: 10px; border: 1px solid #ddd; }
    .stToast { background-color: #333; color: white; }
</style>
""", unsafe_allow_html=True)

# THÁO XÍCH AN TOÀN
SAFE_CONFIG = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
MODEL_PRIORITY = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.0-flash"]

# --- 2. KHỞI TẠO KẾT NỐI ---
def init_services():
    try:
        SUPABASE_URL = st.secrets["supabase"]["SUPABASE_URL"]
        SUPABASE_KEY = st.secrets["supabase"]["SUPABASE_KEY"]
        GEMINI_KEY = st.secrets["gemini"]["API_KEY"]
        
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        genai.configure(api_key=GEMINI_KEY)
        return client
    except Exception as e:
        return None

supabase = init_services()

if not supabase:
    st.error("❌ Lỗi kết nối! Kiểm tra lại file secrets.toml")
    st.stop()

# --- 3. COOKIE MANAGER (ĐẶT Ở ĐẦU) ---
# Chỉ khởi tạo 1 lần duy nhất với key cố định
cookie_manager = stx.CookieManager(key="v_brainer_cookies")

def check_login_status():
    # 1. Nếu đã có User -> Bỏ qua
    if 'user' in st.session_state:
        return

    # 2. Kiểm tra Cookie
    if 'cookie_check_done' not in st.session_state:
        # Không dùng st.spinner ở đây để tránh xung đột UI khi component render
        time.sleep(0.5) 
        try:
            access_token = cookie_manager.get("supabase_access_token")
            refresh_token = cookie_manager.get("supabase_refresh_token")
            
            if access_token and refresh_token:
                session = supabase.auth.set_session(access_token, refresh_token)
                if session:
                    st.session_state.user = session.user
                    st.toast("👋 Mừng ông giáo trở lại!", icon="🍪")
                    time.sleep(0.5)
                    st.rerun()
        except Exception:
            # Xóa cookie lỗi nhẹ nhàng
            try:
                cookie_manager.delete("supabase_access_token")
                cookie_manager.delete("supabase_refresh_token")
            except:
                pass
        
        st.session_state['cookie_check_done'] = True

    # 3. Form Đăng Nhập
    if 'user' not in st.session_state:
        st.title("🔐 Đăng nhập V-Brainer")
        col_main, _ = st.columns([1, 1])
        with col_main:
            email = st.text_input("Email")
            password = st.text_input("Mật khẩu", type="password")
            
            c1, c2 = st.columns(2)
            
            if c1.button("Đăng Nhập", type="primary", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    
                    # [FIX LỖI HERE] Thêm key riêng biệt cho mỗi lần set cookie
                    cookie_manager.set("supabase_access_token", res.session.access_token, key="set_access_token")
                    cookie_manager.set("supabase_refresh_token", res.session.refresh_token, key="set_refresh_token")
                    
                    st.success("Thành công! Đang chuyển hướng...")
                    time.sleep(1.5) 
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")

            if c2.button("Đăng Ký", use_container_width=True):
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    if res.user:
                        st.success("Đăng ký thành công! Hãy kiểm tra Email.")
                    else:
                        st.warning("Vui lòng kiểm tra email xác nhận.")
                except Exception as e:
                    st.error(f"Lỗi: {e}")
        st.stop()

check_login_status()

# --- SIDEBAR (PHIÊN BẢN AN TOÀN TUYỆT ĐỐI) ---
with st.sidebar:
    if 'user' in st.session_state:
        st.info(f"👤 {st.session_state.user.email}")
        
        if st.button("🚪 Đăng xuất", use_container_width=True):
            # 1. Xóa Cookie (Bọc trong try-except để không crash nếu cookie không tồn tại)
            try:
                cookie_manager.delete("supabase_access_token", key="logout_access_token")
            except (KeyError, Exception):
                pass # Không có cookie thì thôi, càng tốt
            
            try:
                cookie_manager.delete("supabase_refresh_token", key="logout_refresh_token")
            except (KeyError, Exception):
                pass 
            
            # 2. Sign out Supabase
            try: supabase.auth.sign_out()
            except: pass
            
            # 3. Xóa Session State
            keys_to_remove = ['user', 'cookie_check_done']
            for key in keys_to_remove:
                if key in st.session_state:
                    del st.session_state[key]
            
            # 4. Thông báo & Rerun
            st.warning("Đang đăng xuất...")
            time.sleep(1)
            st.rerun()

# ==========================================
# 🧠 4. CORE AI LOGIC (NÂNG CẤP AGENTIC)
# ==========================================

# --- A. HELPER FUNCTIONS ---

def clean_json_text(text):
    """Làm sạch markdown (```json ... ```) trước khi parse"""
    if not text: return "{}"
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end != 0:
        return text[start:end]
    return text
    
def get_embedding(text):
    if not text or not isinstance(text, str) or not text.strip():
        return None 
    try:
        return genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")['embedding']
    except: return None

# --- SỬA LẠI HÀM NÀY Ở ĐẦU FILE ---
def generate_content_with_fallback(prompt, system_instruction, stream=True, temperature=1.0):
    for model_name in MODEL_PRIORITY:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            response = model.generate_content(
                prompt, safety_settings=SAFE_CONFIG, stream=stream, 
                generation_config=genai.types.GenerationConfig(temperature=temperature), # <--- Thêm dòng này
                request_options={'timeout': 60}
            )
            return response
        except Exception as e: continue
    raise Exception("All models failed")

def crystallize_session(chat_history, persona_role):
    chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history])
    crystallize_prompt = f"""
    Bạn là Thư Ký Ghi Chép ({persona_role}).
    Nhiệm vụ: Đọc đoạn hội thoại sau và LỌC BỎ RÁC.
    Chỉ giữ lại và TÓM TẮT các thông tin giá trị (Fact, Idea, Decision).
    CHAT LOG: {chat_text}
    OUTPUT: Trả về tóm tắt súc tích (50-100 từ). Nếu rác, trả về "NO_INFO".
    """
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        res = model.generate_content(crystallize_prompt)
        return res.text.strip()
    except: return "Lỗi AI Filter."

# --- B. SEARCH LOGIC (HYBRID) ---
def smart_search_hybrid_raw(query_text, project_id, top_k=10):
    """Hàm gốc trả về List Object (Có ID, dùng cho Rule Check)"""
    try:
        query_vec = get_embedding(query_text)
        if not query_vec: return []
        
        response = supabase.rpc("hybrid_search", {
            "query_text": query_text, 
            "query_embedding": query_vec,
            "match_threshold": 0.3, 
            "match_count": top_k, 
            "story_id_input": project_id
        }).execute()
        return response.data if response.data else []
    except: return []

def smart_search_hybrid(query_text, project_id, top_k=10):
    """Wrapper trả về String Context"""
    raw_data = smart_search_hybrid_raw(query_text, project_id, top_k)
    results = []
    if raw_data:
        for item in raw_data:
            results.append(f"- [{item['entity_name']}]: {item['description']}")
    return "\n".join(results) if results else ""

# --- C. [AGENT MODULE] ROUTER & LOADER (NEW) ---
def ai_router_pro_v2(user_prompt, chat_history_text):
    """Router V2: Phân tích Intent và Target Files"""
    router_prompt = f"""
    Đóng vai Project Coordinator. Phân tích User Input và Lịch sử Chat.
    
    LỊCH SỬ CHAT:
    {chat_history_text}
    
    USER INPUT: "{user_prompt}"
    
    PHÂN LOẠI INTENT:
    1. "read_full_content": Khi user muốn "Sửa", "Refactor", "Review", "So sánh", "Viết tiếp", "Kiểm tra code/văn" -> Cần đọc NGUYÊN VĂN FILE.
    2. "search_bible": Khi user hỏi thông tin chung, quy định, cốt truyện tóm tắt, tra cứu khái niệm -> Tra cứu Bible (Vector).
    3. "chat_casual": Chào hỏi, chém gió không cần context.
    
    OUTPUT JSON ONLY:
    {{
        "intent": "read_full_content" | "search_bible" | "chat_casual",
        "target_files": ["tên file 1", "tên file 2", "tên chương..."], 
        "reason": "Lý do ngắn gọn",
        "rewritten_query": "Viết lại câu hỏi cho rõ nghĩa (thay thế 'nó', 'file này' bằng tên thực thể)"
    }}
    """
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        res = model.generate_content(router_prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(clean_json_text(res.text))
    except Exception: 
        return {"intent": "chat_casual", "target_files": [], "rewritten_query": user_prompt}

def load_full_content(file_names, project_id):
    """Load toàn văn nội dung của nhiều file/chương"""
    if not file_names: return "", []
    
    full_text = ""
    loaded_sources = []
    
    for name in file_names:
        # 1. Tìm trong Chapters (Full)
        res = supabase.table("chapters").select("chapter_number, title, content").eq("story_id", project_id).ilike("title", f"%{name}%").execute()
        
        if res.data:
            item = res.data[0]
            full_text += f"\n\n=== 📄 SOURCE FILE/CHAP: {item['title']} ===\n{item['content']}\n"
            loaded_sources.append(f"📄 {item['title']}")
        else:
            # 2. Tìm trong Bible (Summary Fallback)
            res_bible = supabase.table("story_bible").select("entity_name, description").eq("story_id", project_id).ilike("entity_name", f"%{name}%").execute()
            if res_bible.data:
                item = res_bible.data[0]
                full_text += f"\n\n=== ⚠️ BIBLE SUMMARY (Chỉ là tóm tắt): {item['entity_name']} ===\n{item['description']}\n"
                loaded_sources.append(f"🗂️ {item['entity_name']} (Summary)")

    return full_text, loaded_sources

# --- D. [AGENT MODULE] RULE MINING (NEW) ---
def get_mandatory_rules(project_id):
    """Lấy tất cả các luật (RULE) bắt buộc"""
    try:
        # Tìm các entity bắt đầu bằng [RULE]
        res = supabase.table("story_bible").select("description").eq("story_id", project_id).ilike("entity_name", "%[RULE]%").execute()
        if res.data:
            rules_text = "\n".join([f"- {r['description']}" for r in res.data])
            return f"\n🔥 --- QUY TẮC BẮT BUỘC (MANDATORY RULES) ---\n{rules_text}\n"
        return ""
    except: return ""

def extract_rule_raw(user_prompt, ai_response):
    """Trích xuất luật thô từ hội thoại (Đã nâng cấp độ nhạy)"""
    prompt = f"""
    Bạn là "Rule Extractor". Nhiệm vụ: Phát hiện User Preference qua hội thoại.
    
    HỘI THOẠI:
    - User: "{user_prompt}"
    - AI: (Phản hồi trước đó...)
    
    HÃY PHÂN TÍCH XEM USER CÓ ĐANG:
    1. Phàn nàn về độ dài/phong cách (VD: "dài quá", "nói ít thôi", "đừng giải thích").
    2. Đưa ra format bắt buộc (VD: "chỉ code thôi", "dùng JSON").
    3. Sửa lưng AI (VD: "sai rồi", "phải làm thế này").
    
    NẾU CÓ, hãy trích xuất thành 1 QUY TẮC NGẮN GỌN (Mệnh lệnh thức).
    Ví dụ: 
    - Input: "Nói nhiều quá, code thôi" -> Rule: "Khi user hỏi code -> Chỉ đưa Code Block, không giải thích dài dòng."
    
    NẾU KHÔNG (chỉ là chat tiếp, hỏi thêm, cảm ơn), trả về "NO_RULE".
    
    Output Text Only.
    """
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(prompt)
        text = res.text.strip()
        # Lọc thêm 1 lớp cho chắc
        if "NO_RULE" in text or len(text) < 5: 
            return None
        return text
    except: return None

def analyze_rule_conflict(new_rule_content, project_id):
    """Check xung đột luật với DB"""
    similar_rules_str = smart_search_hybrid(new_rule_content, project_id, top_k=3)
    
    if not similar_rules_str:
        return {"status": "NEW", "reason": "Không trùng ai cả", "suggested_content": new_rule_content}

    judge_prompt = f"""
    Luật Mới: "{new_rule_content}"
    Luật Cũ trong DB: "{similar_rules_str}"
    
    Hãy so sánh mối quan hệ:
    - CONFLICT: Mâu thuẫn trực tiếp (VD: Cũ bảo A, Mới bảo không A).
    - MERGE: Cùng chủ đề nhưng Mới chi tiết hơn/bổ sung.
    - NEW: Khác chủ đề.
    
    OUTPUT JSON:
    {{
        "status": "CONFLICT" | "MERGE" | "NEW",
        "existing_rule_summary": "Tóm tắt luật cũ ngắn gọn",
        "reason": "Lý do",
        "merged_content": "Nội dung gộp hoàn chỉnh (nếu MERGE). Nếu CONFLICT/NEW để null."
    }}
    """
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        res = model.generate_content(judge_prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(clean_json_text(res.text))
    except:
        return {"status": "NEW", "reason": "AI Judge Error", "suggested_content": new_rule_content}

# ==========================================
# 📱 5. GIAO DIỆN CHÍNH
# ==========================================
with st.sidebar:
    st.caption(f"👤 {st.session_state.user.email}")
    projects = supabase.table("stories").select("*").eq("user_id", st.session_state.user.id).execute()
    proj_map = {p['title']: p for p in projects.data}
    
    st.divider()
    selected_proj_name = st.selectbox("📂 Chọn Dự Án", ["+ Tạo Dự Án Mới"] + list(proj_map.keys()))
    
    if selected_proj_name == "+ Tạo Dự Án Mới":
        with st.form("new_proj"):
            title = st.text_input("Tên Dự Án")
            cat = st.selectbox("Loại", ["Writer", "Coder", "Content Creator"])
            if st.form_submit_button("Tạo"):
                supabase.table("stories").insert({"title": title, "category": cat, "user_id": st.session_state.user.id}).execute()
                st.rerun()
        st.stop()
    
    current_proj = proj_map[selected_proj_name]
    proj_id = current_proj['id']
    proj_type = current_proj.get('category', 'Writer')
    
    # Load Persona
    persona = PERSONAS.get(proj_type, PERSONAS['Writer'])
    st.info(f"{persona['icon']} Mode: **{proj_type}**")
    
    if st.button("🚪 Đăng xuất (Sidebar)"):
        cookie_manager.delete("supabase_access_token")
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

st.title(f"{persona['icon']} {selected_proj_name}")

tab1, tab2, tab3 = st.tabs(["✍️ Workstation  ", "💬 V Chat  ", "📚 Project Bible  "])

# === TAB 1: WORKSTATION (GIỮ NGUYÊN) ===
with tab1:
    files = supabase.table("chapters").select("chapter_number, title").eq("story_id", proj_id).order("chapter_number").execute()
    f_opts = {}
    for f in files.data:
        display_name = f"File {f['chapter_number']}"
        if f['title']: display_name += f": {f['title']}"
        f_opts[display_name] = f['chapter_number']

    sel_file = st.selectbox("📂 Chọn File:", ["-- New --"] + list(f_opts.keys()))
    chap_num = f_opts[sel_file] if sel_file != "-- New --" else len(files.data) + 1
    
    db_content, db_review, db_title = "", "", ""
    if sel_file != "-- New --":
        try:
            res = supabase.table("chapters").select("content, review_content, title").eq("story_id", proj_id).eq("chapter_number", chap_num).execute()
            if res.data: 
                db_content = res.data[0].get('content', '')
                db_review = res.data[0].get('review_content', '')
                db_title = res.data[0].get('title', '')
        except: pass

    if 'current_chap_view' not in st.session_state or st.session_state['current_chap_view'] != chap_num:
        st.session_state['review_res'] = db_review
        st.session_state['current_chap_view'] = chap_num

    st.divider()

    col_edit, col_tool = st.columns([2, 1])
    with col_edit:
        chap_title = st.text_input("🔖 Tên File", value=db_title, placeholder="VD: Sự khởi đầu...")
        input_text = st.text_area("Nội dung", value=db_content, height=600)
        
        if st.button("💾 Lưu Nội Dung & Tên"):
            supabase.table("chapters").upsert({
                "story_id": proj_id, "chapter_number": chap_num, 
                "title": chap_title, "content": input_text
            }, on_conflict="story_id, chapter_number").execute()
            st.toast("Đã lưu!", icon="✅")
            time.sleep(0.5)
            st.rerun()

    with col_tool:
        st.write("### 🤖 Trợ lý AI")
        if st.button("🚀 Review Mới", type="primary"):
            if not input_text: st.warning("Trống!")
            else:
                with st.status("Đang đọc..."):
                    context = smart_search_hybrid(input_text[:500], proj_id)
                    rules = get_mandatory_rules(proj_id) # Chèn Rule
                    final_prompt = f"RULES: {rules}\nTITLE: {chap_title}\nCONTEXT: {context}\nCONTENT: {input_text}\nTASK: {persona['review_prompt']}"
                    res = generate_content_with_fallback(final_prompt, system_instruction=persona['core_instruction'], stream=False)
                    st.session_state['review_res'] = res.text
                    st.rerun()
        
        if 'review_res' in st.session_state and st.session_state['review_res']:
            with st.expander("📝 Kết quả", expanded=True):
                st.markdown(st.session_state['review_res'])
                st.divider()
                if st.button("💾 Lưu Review DB"):
                    supabase.table("chapters").update({"review_content": st.session_state['review_res']}).eq("story_id", proj_id).eq("chapter_number", chap_num).execute()
                    st.toast("Saved Review!")

        st.divider()
        if st.button("📥 Trích xuất Bible"):
            with st.spinner("Phân tích..."):
                meta_desc = "Mô tả ngắn gọn MỤC ĐÍCH, DIỄN BIẾN CHÍNH và KẾT QUẢ của File này."
                if proj_type == "Coder": meta_desc = "Mô tả MỤC ĐÍCH, THÀNH PHẦN CHÍNH (Hàm/Class) và INPUT/OUTPUT."
                
                extra_req = f"""
                YÊU CẦU BẮT BUỘC: Thêm vào đầu JSON một mục tổng hợp:
                - entity_name: "[META] {chap_title if chap_title else f'File {chap_num}'}"
                - type: "Overview"
                - description: "{meta_desc}"
                """
                ext_prompt = f"TITLE: {chap_title}\nCONTENT: {input_text}\nTASK: {persona['extractor_prompt']}\n{extra_req}"
                try:
                    res = generate_content_with_fallback(ext_prompt, system_instruction="JSON Only", stream=False)
                    st.session_state['extract_json'] = res.text
                except: st.error("Lỗi AI.")

        if 'extract_json' in st.session_state:
            with st.expander("Preview", expanded=True):
                try:
                    clean = clean_json_text(st.session_state['extract_json'])
                    data = json.loads(clean)
                    st.dataframe(pd.DataFrame(data)[['entity_name', 'type', 'description']], hide_index=True)
                    if st.button("💾 Save to Bible"):
                        for item in data:
                            vec = get_embedding(f"{item.get('description')} {item.get('quote', '')}")
                            if vec: 
                                supabase.table("story_bible").insert({
                                    "story_id": proj_id, "entity_name": item['entity_name'],
                                    "description": item['description'], "embedding": vec, "source_chapter": chap_num
                                }).execute()
                        st.success("Đã lưu!")
                        del st.session_state['extract_json']
                except Exception as e: st.error(f"Lỗi Format: {e}")

# === TAB 2: SMART CHAT (SỬA LOGIC AGENTIC) ===
with tab2:
    col_left, col_right = st.columns([3, 1])
    
    # --- CỘT PHẢI: KÝ ỨC ---
    with col_right:
        st.write("### 🧠 Ký ức")
        if 'chat_cutoff' not in st.session_state: st.session_state['chat_cutoff'] = "1970-01-01" 
        
        if st.button("🧹 Clear Screen"):
            st.session_state['chat_cutoff'] = datetime.utcnow().isoformat()
            st.rerun()
            
        if st.button("🔄 Hiện lại toàn bộ"):
             st.session_state['chat_cutoff'] = "1970-01-01"
             st.rerun()
        # === [FIX] THÊM NÚT NÀY ĐỂ KHÔNG BỊ LỖI NameError ===
        enable_history = st.toggle(
            "💾 Lưu lịch sử Chat", 
            value=True, 
            help="Tắt đi để chat ẩn danh (Không lưu DB, AI không học)"
        )
        # === THÊM CÁI NÀY ===
        strict_mode = st.toggle(
            "🚫 Chế độ Nghiêm túc (Strict)", 
            value=False, 
            help="Bật lên: AI chỉ trả lời dựa trên dữ liệu tìm được. Cấm chém gió. (Temp = 0)"
        )
        st.divider()

        # Crystallize logic (Giữ nguyên)
        with st.expander("💎 Kết tinh Chat"):
            st.caption("Lưu ý chính vào Bible.")
            crys_option = st.radio("Phạm vi:", ["20 tin gần nhất", "Toàn bộ phiên"])
            memory_topic = st.text_input("Chủ đề:", placeholder="VD: Magic System")
            if st.button("✨ Kết tinh"):
                limit = 20 if crys_option == "20 tin gần nhất" else 100
                chat_data = supabase.table("chat_history").select("*").eq("story_id", proj_id).order("created_at", desc=True).limit(limit).execute().data
                chat_data.reverse()
                if chat_data:
                    with st.spinner("Đang tóm tắt..."):
                        summary = crystallize_session(chat_data, persona['role'])
                        if summary != "NO_INFO":
                            st.session_state['crys_summary'] = summary
                            st.session_state['crys_topic'] = memory_topic if memory_topic else f"Chat {datetime.now().strftime('%d/%m')}"
                        else: st.warning("Không có thông tin giá trị.")

    if 'crys_summary' in st.session_state:
        with col_right:
            final_sum = st.text_area("Hiệu chỉnh:", value=st.session_state['crys_summary'])
            if st.button("💾 Lưu Ký ức"):
                vec = get_embedding(final_sum)
                if vec:
                    supabase.table("story_bible").insert({
                        "story_id": proj_id, "entity_name": f"[CHAT] {st.session_state['crys_topic']}",
                        "description": final_sum, "embedding": vec, "source_chapter": 0
                    }).execute()
                    st.toast("Đã lưu!")
                    del st.session_state['crys_summary']
                    st.rerun()

    # --- CỘT TRÁI: CHAT UI & LOGIC AGENT ---
    with col_left:
        # 1. LOAD HISTORY
        try:
            msgs_data = supabase.table("chat_history").select("*").eq("story_id", proj_id).order("created_at", desc=True).limit(50).execute().data
            msgs = msgs_data[::-1] if msgs_data else []
            visible_msgs = [m for m in msgs if m['created_at'] > st.session_state['chat_cutoff']]
            
            for m in visible_msgs:
                # === SỬA DÒNG NÀY ===
                # Nếu là 'model' thì lấy icon của Persona hiện tại (VD: 💻), user thì để mặc định
                role_icon = persona['icon'] if m['role'] == 'model' else None
                
                with st.chat_message(m['role'], avatar=role_icon):
                    st.markdown(m['content'])
        except Exception as e: st.error(f"Lỗi load history: {e}")

        # 2. XỬ LÝ CHAT MỚI
        if prompt := st.chat_input("Hỏi V (Agentic Mode)..."):
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.spinner("Thinking..."):
                now_timestamp = datetime.utcnow().isoformat()
                
                # --- A. ROUTING ---
                # Lấy lịch sử chat để Router hiểu ngữ cảnh
                recent_history_text = "\n".join([f"{m['role']}: {m['content']}" for m in visible_msgs[-5:]])
                router_out = ai_router_pro_v2(prompt, recent_history_text)
                
                intent = router_out.get('intent', 'chat_casual')
                targets = router_out.get('target_files', [])
                rewritten_query = router_out.get('rewritten_query', prompt)
                
                ctx = ""
                debug_notes = [f"Intent: {intent}"]
                
                # --- B. CONTEXT BUILDER ---
                # B1: Mandatory Rules (Luôn luôn lấy)
                mandatory_rules = get_mandatory_rules(proj_id)
                if mandatory_rules:
                    ctx += f"{mandatory_rules}\n"
                    debug_notes.append("Rules Loaded")
                
                # B2: Content Loading (Dựa theo Intent)
                if intent == "read_full_content" and targets:
                    full_text, source_names = load_full_content(targets, proj_id)
                    ctx += f"\n--- TARGET CONTENT ---\n{full_text}\n"
                    debug_notes.append(f"Reading: {', '.join(source_names)}")
                    
                elif intent == "search_bible":
                    bible_res = smart_search_hybrid(rewritten_query, proj_id)
                    ctx += f"\n--- KNOWLEDGE BASE ---\n{bible_res}\n"
                    debug_notes.append("Vector Search")
                
                # B3: Chat History
                ctx += f"\n--- RECENT CHAT ---\n{recent_history_text}"

                # --- C. GENERATION (LOGIC MỚI) ---
                final_prompt = f"CONTEXT:\n{ctx}\n\nUSER QUERY: {prompt}"
                
                # 1. Cấu hình Strict Mode
                run_instruction = persona['core_instruction']
                run_temperature = 1.0 # Mặc định sáng tạo vừa phải

                # Biến strict_mode lấy từ cái toggle bên cột phải (col_right)
                if strict_mode:
                    run_temperature = 0.0 # Lạnh lùng, chính xác
                    run_instruction += """
                    \n\n‼️ STRICT MODE ACTIVATED:
                    1. CHỈ trả lời dựa trên thông tin trong CONTEXT.
                    2. Tuyệt đối KHÔNG dùng kiến thức bên ngoài (training data) để bịa đặt.
                    3. Nếu không có thông tin, trả lời: "Dữ liệu dự án không có thông tin này."
                    """

                try:
                    # Gọi hàm với config mới
                    res_stream = generate_content_with_fallback(
                        final_prompt, 
                        system_instruction=run_instruction, 
                        stream=True,
                        temperature=run_temperature
                    )
                    
                    with st.chat_message("assistant"):
                        if debug_notes: st.caption(f"🧠 {', '.join(debug_notes)}")
                        if strict_mode: st.caption("🔒 Strict Mode: ON")
                        
                        full_response_text = ""
                        placeholder = st.empty()
                        
                        for chunk in res_stream:
                            if hasattr(chunk, 'text') and chunk.text:
                                full_response_text += chunk.text
                                placeholder.markdown(full_response_text + "▌")
                        placeholder.markdown(full_response_text)
                    
                    # Save Log & Rule Mining (Chỉ lưu nếu enable_history bật)
                    # Biến enable_history lấy từ toggle bên cột phải
                    if full_response_text and enable_history:
                        # 1. Lưu Chat
                        supabase.table("chat_history").insert([
                            {"story_id": proj_id, "role": "user", "content": prompt, "created_at": now_timestamp},
                            {"story_id": proj_id, "role": "model", "content": full_response_text, "created_at": now_timestamp}
                        ]).execute()
                        
                        # 2. Học Luật Mới (Agentic)
                        new_rule = extract_rule_raw(prompt, full_response_text)
                        if new_rule:
                            st.session_state['pending_new_rule'] = new_rule
                            st.rerun()
                    
                    elif not enable_history:
                        st.caption("👻 Chế độ ẩn danh: Không lưu lịch sử & Không học luật.")

                except Exception as e: st.error(f"Lỗi generate: {e}")
                        
                    

    # --- UI XỬ LÝ RULE MỚI (NỔI LÊN DƯỚI INPUT) ---
    if 'pending_new_rule' in st.session_state:
        rule_content = st.session_state['pending_new_rule']
        with st.expander("🧐 V phát hiện một Quy Tắc mới!", expanded=True):
            st.write(f"**Nội dung:** {rule_content}")
            
            # Analyze Conflict
            if 'rule_analysis' not in st.session_state:
                with st.spinner("Đang kiểm tra trùng lặp..."):
                    st.session_state['rule_analysis'] = analyze_rule_conflict(rule_content, proj_id)
            
            analysis = st.session_state['rule_analysis']
            st.info(f"Đánh giá AI: **{analysis['status']}** - {analysis['reason']}")
            
            if analysis['status'] == "CONFLICT":
                st.warning(f"⚠️ Xung đột với: {analysis['existing_rule_summary']}")
            elif analysis['status'] == "MERGE":
                st.info(f"💡 Gợi ý gộp: {analysis['merged_content']}")
            
            c1, c2, c3 = st.columns(3)
            if c1.button("✅ Lưu/Gộp Rule này"):
                final_content = analysis.get('merged_content') if analysis['status'] == "MERGE" else rule_content
                vec = get_embedding(final_content)
                supabase.table("story_bible").insert({
                    "story_id": proj_id,
                    "entity_name": f"[RULE] {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "description": final_content,
                    "embedding": vec, "source_chapter": 0
                }).execute()
                st.toast("Đã học thuộc quy tắc mới!")
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()
                
            if c2.button("✏️ Sửa rồi Lưu"):
                st.session_state['edit_rule_manual'] = rule_content
                
            if c3.button("❌ Bỏ qua"):
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()

        if 'edit_rule_manual' in st.session_state:
             edited = st.text_input("Sửa lại rule:", value=st.session_state['edit_rule_manual'])
             if st.button("Lưu bản sửa"):
                vec = get_embedding(edited)
                supabase.table("story_bible").insert({
                    "story_id": proj_id, "entity_name": f"[RULE] Manual",
                    "description": edited, "embedding": vec, "source_chapter": 0
                }).execute()
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                del st.session_state['edit_rule_manual']
                st.rerun()

# === TAB 3: BIBLE (GIỮ NGUYÊN LOGIC) ===
with tab3:
    st.subheader("📚 Project Bible Manager")
    
    col_search, col_ref = st.columns([4, 1])
    with col_search:
        search_kw = st.text_input("🔍 Tìm kiếm trong Bible", placeholder="Nhập từ khóa...")
    with col_ref:
        if st.button("🔄 Refresh", use_container_width=True): st.rerun()

    bible_query = supabase.table("story_bible").select("*").eq("story_id", proj_id).order("created_at", desc=True).execute()
    bible_data = bible_query.data if bible_query.data else []

    filtered_bible = []
    if search_kw:
        kw = search_kw.lower()
        filtered_bible = [b for b in bible_data if kw in b['entity_name'].lower() or kw in b['description'].lower()]
    else:
        filtered_bible = bible_data

    opts = {f"{b['entity_name']}": b for b in filtered_bible}

    with st.expander("➕ Thêm Bible thủ công", expanded=False):
        with st.form("add_bible_form"):
            new_name = st.text_input("Tên mục (Entity Name)")
            new_desc = st.text_area("Mô tả chi tiết")
            if st.form_submit_button("Lưu mới"):
                if not new_name or not new_desc:
                    st.error("Vui lòng nhập đủ thông tin!")
                else:
                    with st.spinner("Đang vector hóa..."):
                        vec = get_embedding(f"{new_name}: {new_desc}")
                        if vec:
                            supabase.table("story_bible").insert({
                                "story_id": proj_id,
                                "entity_name": new_name, "description": new_desc,
                                "embedding": vec, "source_chapter": 0
                            }).execute()
                            st.success("Đã thêm thành công!")
                            time.sleep(1)
                            st.rerun()
                        else: st.error("Lỗi tạo Embedding.")

    st.divider()

    if filtered_bible:
        selections = st.multiselect(
            f"Chọn mục để thao tác (Đang hiển thị {len(filtered_bible)} mục):", 
            list(opts.keys()), key="bible_selector"
        )
        
        col_actions = st.columns([1, 1, 2])
        
        with col_actions[0]:
            if st.button("🔥 Xóa Mục Chọn", use_container_width=True, disabled=len(selections)==0):
                ids = [opts[k]['id'] for k in selections]
                supabase.table("story_bible").delete().in_("id", ids).execute()
                st.success("Đã xóa!")
                time.sleep(0.5)
                st.rerun()

        with col_actions[1]:
            if st.button("🧬 Gộp (AI Merge)", use_container_width=True, disabled=len(selections)<2):
                items = [opts[k] for k in selections]
                txt = "\n".join([f"- {i['description']}" for i in items])
                prompt_merge = f"Gộp các mục sau thành 1 nội dung duy nhất:\n{txt}"
                
                try:
                    with st.spinner("AI đang gộp..."):
                        res = generate_content_with_fallback(prompt_merge, system_instruction="Merge Expert", stream=False)
                        merged_text = res.text
                        
                        if merged_text and merged_text.strip():
                            vec = get_embedding(merged_text)
                            if vec: 
                                supabase.table("story_bible").insert({
                                    "story_id": proj_id, "entity_name": items[0]['entity_name'],
                                    "description": merged_text, "embedding": vec, "source_chapter": items[0]['source_chapter']
                                }).execute()
                                ids = [i['id'] for i in items]
                                supabase.table("story_bible").delete().in_("id", ids).execute()
                                st.success("Gộp xong!")
                                time.sleep(0.5)
                                st.rerun()
                            else: st.error("Lỗi Embedding.")
                except Exception as e: st.error(f"Lỗi: {e}")

        if len(selections) == 1:
            st.info("🛠️ Chế độ chỉnh sửa")
            item_to_edit = opts[selections[0]]
            with st.form("edit_bible_form"):
                edit_name = st.text_input("Sửa Tên", value=item_to_edit['entity_name'])
                edit_desc = st.text_area("Sửa Mô tả", value=item_to_edit['description'], height=150)
                
                if st.form_submit_button("Cập nhật & Re-Vectorize"):
                    with st.spinner("Đang cập nhật..."):
                        vec = get_embedding(f"{edit_name}: {edit_desc}")
                        if vec:
                            supabase.table("story_bible").update({
                                "entity_name": edit_name, "description": edit_desc, "embedding": vec
                            }).eq("id", item_to_edit['id']).execute()
                            st.success("Đã cập nhật!")
                            time.sleep(1)
                            st.rerun()
                        else: st.error("Lỗi vector hóa.")

        st.divider()
        st.dataframe(
            pd.DataFrame(filtered_bible)[['entity_name', 'description', 'created_at']], 
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Không tìm thấy dữ liệu phù hợp.")
    
    st.divider()
    with st.expander("💀 Danger Zone"):
        if st.button("💣 Xóa sạch Bible & Reset", type="primary", use_container_width=True):
            try:
                supabase.table("story_bible").delete().eq("story_id", proj_id).execute()
                st.success("Đã dọn sạch sẽ!")
                time.sleep(1)
                st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")












