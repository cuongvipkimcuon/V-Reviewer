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
</style>
""", unsafe_allow_html=True)

# THÁO XÍCH AN TOÀN
SAFE_CONFIG = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
MODEL_PRIORITY = ["gemini-2.0-flash", "gemini-1.5-flash"]

# --- 2. KHỞI TẠO KẾT NỐI (AN TOÀN) ---
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

# --- 3. COOKIE MANAGER & LOGIN ---
cookie_manager = stx.CookieManager()

def check_login_status():
    if 'user' not in st.session_state:
        if 'cookie_check_done' not in st.session_state:
            with st.spinner("⏳ Đang lục lọi ký ức (Chờ 3s)..."):
                time.sleep(3) 
                access_token = cookie_manager.get("supabase_access_token")
                refresh_token = cookie_manager.get("supabase_refresh_token")
                
                if access_token and refresh_token:
                    try:
                        session = supabase.auth.set_session(access_token, refresh_token)
                        if session:
                            st.session_state.user = session.user
                            st.toast("👋 Mừng ông giáo trở lại!", icon="🍪")
                            st.rerun() 
                    except: pass
                st.session_state['cookie_check_done'] = True
                st.rerun()

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
                    cookie_manager.set("supabase_access_token", res.session.access_token, key="set_access")
                    cookie_manager.set("supabase_refresh_token", res.session.refresh_token, key="set_refresh")
                    st.success("Đăng nhập thành công!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")
            if c2.button("Đăng Ký", use_container_width=True):
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    st.session_state.user = res.user
                    if res.session:
                        cookie_manager.set("supabase_access_token", res.session.access_token, key="set_acc_up")
                        cookie_manager.set("supabase_refresh_token", res.session.refresh_token, key="set_ref_up")
                    st.success("Tạo user thành công!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")
        st.stop() 

check_login_status()

# --- SIDEBAR ---
with st.sidebar:
    st.info(f"👤 {st.session_state.user.email}")
    if st.button("🚪 Đăng xuất", use_container_width=True):
        supabase.auth.sign_out()
        cookie_manager.delete("supabase_access_token")
        cookie_manager.delete("supabase_refresh_token")
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ==========================================
# 🧠 4. CORE AI LOGIC
# ==========================================
def generate_content_with_fallback(prompt, system_instruction, stream=True):
    for model_name in MODEL_PRIORITY:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            response = model.generate_content(
                prompt, safety_settings=SAFE_CONFIG, stream=stream, request_options={'timeout': 60}
            )
            return response
        except Exception as e: continue
    raise Exception("All models failed")

def get_embedding(text):
    # Kiểm tra an toàn để tránh ValueError khi text rỗng
    if not text or not isinstance(text, str) or not text.strip():
        # Trả về None hoặc raise lỗi có kiểm soát
        return None 
    return genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")['embedding']

def smart_search_hybrid(query_text, project_id, top_k=10):
    try:
        query_vec = get_embedding(query_text)
        if not query_vec: return "" # Nếu không embed được thì trả về rỗng
        
        response = supabase.rpc("hybrid_search", {
            "query_text": query_text, 
            "query_embedding": query_vec,
            "match_threshold": 0.3, "match_count": top_k, "story_id_input": project_id
        }).execute()
        results = []
        if response.data:
            for item in response.data:
                results.append(f"- [{item['entity_name']}]: {item['description']}")
        return "\n".join(results) if results else ""
    except: return ""

def ai_router_pro(user_prompt):
    router_prompt = f"""
    Phân tích User Prompt và trả về JSON:
    1. "intent": "search_bible" OR "chat_casual".
    2. "target_chapter": Số chương cần đọc (Int/Null).
    USER: "{user_prompt}"
    JSON OUTPUT ONLY.
    """
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        res = model.generate_content(router_prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except: return {"intent": "chat_casual", "target_chapter": None}

def crystallize_session(chat_history, persona_role):
    chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history])
    crystallize_prompt = f"""
    Bạn là Thư Ký Ghi Chép ({persona_role}).
    Nhiệm vụ: Đọc đoạn hội thoại sau và LỌC BỎ RÁC.
    Chỉ giữ lại và TÓM TẮT các thông tin giá trị.
    CHAT LOG: {chat_text}
    OUTPUT: Trả về tóm tắt súc tích (50-100 từ). Nếu rác, trả về "NO_INFO".
    """
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        res = model.generate_content(crystallize_prompt)
        return res.text.strip()
    except: return "Lỗi AI Filter."

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

tab1, tab2, tab3 = st.tabs(["✍️ Workstation", "💬 Smart Chat & Memory", "📚 Project Bible"])

# === TAB 1: WORKSTATION (FULL TITLE & META) ===
with tab1:
    # 1. LOAD DATA
    files = supabase.table("chapters").select("chapter_number, title").eq("story_id", proj_id).order("chapter_number").execute()
    
    f_opts = {}
    for f in files.data:
        display_name = f"Chương {f['chapter_number']}"
        if f['title']: display_name += f": {f['title']}"
        f_opts[display_name] = f['chapter_number']

    sel_file = st.selectbox("📂 Chọn Chương:", ["-- New --"] + list(f_opts.keys()))
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

    # 2. UI EDIT
    col_edit, col_tool = st.columns([2, 1])
    with col_edit:
        chap_title = st.text_input("🔖 Tên Chương", value=db_title, placeholder="VD: Sự khởi đầu...")
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
        # REVIEW
        if st.button("🚀 Review Mới", type="primary"):
            if not input_text: st.warning("Trống!")
            else:
                with st.status("Đang đọc..."):
                    context = smart_search_hybrid(input_text[:500], proj_id)
                    final_prompt = f"TITLE: {chap_title}\nCONTEXT: {context}\nCONTENT: {input_text}\nTASK: {persona['review_prompt']}"
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
        # EXTRACT META
        if st.button("📥 Trích xuất Bible"):
            with st.spinner("Phân tích..."):
                meta_desc = "Mô tả ngắn gọn MỤC ĐÍCH, DIỄN BIẾN CHÍNH và KẾT QUẢ của chương này."
                if proj_type == "Coder": meta_desc = "Mô tả MỤC ĐÍCH, THÀNH PHẦN CHÍNH (Hàm/Class) và INPUT/OUTPUT."
                
                extra_req = f"""
                YÊU CẦU BẮT BUỘC: Thêm vào đầu JSON một mục tổng hợp:
                - entity_name: "[META] {chap_title if chap_title else f'Chương {chap_num}'}"
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
                    clean = st.session_state['extract_json'].replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean)
                    st.dataframe(pd.DataFrame(data)[['entity_name', 'type', 'description']], hide_index=True)
                    if st.button("💾 Save to Bible"):
                        for item in data:
                            vec = get_embedding(f"{item.get('description')} {item.get('quote', '')}")
                            if vec: # Chỉ lưu nếu có embedding
                                supabase.table("story_bible").insert({
                                    "story_id": proj_id, "entity_name": item['entity_name'],
                                    "description": item['description'], "embedding": vec, "source_chapter": chap_num
                                }).execute()
                        st.success("Đã lưu!")
                        del st.session_state['extract_json']
                except Exception as e: st.error(f"Lỗi Format: {e}")

# === TAB 2: SMART CHAT (FIX LỖI HIỂN THỊ RAW OBJECT) ===
with tab2:
    col_left, col_right = st.columns([3, 1])
    
    with col_right:
        st.write("### 🧠 Ký ức")
        use_bible = st.toggle("Dùng Bible Context", value=True)
        if st.button("🧹 Clear Screen"):
            st.session_state['temp_chat_view'] = [] 
            st.rerun()
        
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

    with col_left:
        # Load History
        try:
            msgs = supabase.table("chat_history").select("*").eq("story_id", proj_id).order("created_at", desc=False).execute().data
            for m in msgs[-30:]:
                with st.chat_message(m['role']): st.markdown(m['content'])
        except: pass

        if prompt := st.chat_input("Hỏi V..."):
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.spinner("Thinking..."):
                # Context Building
                route = ai_router_pro(prompt)
                target_chap = route.get('target_chapter')
                ctx = ""
                note = []
                
                if target_chap:
                    c = supabase.table("chapters").select("content").eq("story_id", proj_id).eq("chapter_number", target_chap).execute()
                    if c.data: 
                        ctx += f"\n--- CHAP {target_chap} ---\n{c.data[0]['content']}\n"
                        note.append(f"Read Chap {target_chap}")
                
                if use_bible:
                    bible_res = smart_search_hybrid(prompt, proj_id)
                    if bible_res: 
                        ctx += f"\n--- BIBLE ---\n{bible_res}\n"
                        note.append("Bible")

                recent = "\n".join([f"{m['role']}: {m['content']}" for m in msgs[-10:]])
                ctx += f"\n--- RECENT ---\n{recent}"
                final = f"CONTEXT:\n{ctx}\n\nUSER: {prompt}"

                # === FIX CHAT STREAM ===
                try:
                    res_stream = generate_content_with_fallback(final, system_instruction=persona['core_instruction'])
                    
                    with st.chat_message("assistant"):
                        # Hàm generator để bóc tách text từ object response
                        def stream_parser(stream):
                            for chunk in stream:
                                if chunk.text: yield chunk.text
                        
                        full_res = st.write_stream(stream_parser(res_stream))
                        st.caption(f"ℹ️ {', '.join(note) if note else 'Chat Only'}")
                    
                    # Lưu vào DB (Giờ full_res chắc chắn là string)
                    if full_res:
                        supabase.table("chat_history").insert([
                            {"story_id": proj_id, "role": "user", "content": str(prompt)},
                            {"story_id": proj_id, "role": "model", "content": str(full_res)}
                        ]).execute()
                except Exception as e: st.error(f"Lỗi Chat: {e}")

# === TAB 3: BIBLE (FIX LỖI MERGE) ===
with tab3:
    st.subheader("📚 Project Bible")
    if st.button("🔄 Refresh"): st.rerun()
    
    bible = supabase.table("story_bible").select("*").eq("story_id", proj_id).order("created_at", desc=True).execute().data
    if bible:
        opts = {f"{b['entity_name']}": b for b in bible}
        selections = st.multiselect("Chọn mục Gộp/Xóa:", opts.keys())
        
        c1, c2 = st.columns(2)
        if c1.button("🔥 Xóa"):
            ids = [opts[k]['id'] for k in selections]
            supabase.table("story_bible").delete().in_("id", ids).execute()
            st.success("Đã xóa!")
            time.sleep(0.5)
            st.rerun()
            
        if c2.button("🧬 Gộp (AI Merge)"):
            if len(selections) < 2: st.warning("Chọn >= 2 mục!")
            else:
                items = [opts[k] for k in selections]
                txt = "\n".join([f"- {i['description']}" for i in items])
                prompt_merge = f"Gộp các mục sau thành 1 nội dung duy nhất:\n{txt}"
                
                try:
                    res = generate_content_with_fallback(prompt_merge, system_instruction="Merge Expert", stream=False)
                    merged_text = res.text
                    
                    # === FIX: Kiểm tra kết quả trước khi embed ===
                    if not merged_text or not merged_text.strip():
                        st.error("AI trả về rỗng, không thể gộp.")
                    else:
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
        
        st.dataframe(pd.DataFrame(bible)[['entity_name', 'description']], use_container_width=True)
    else: st.info("Bible trống.")
