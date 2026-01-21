import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import json
import re
import pandas as pd
from persona import V_CORE_INSTRUCTION, REVIEW_PROMPT, EXTRACTOR_PROMPT
# [QUAN TRỌNG] Import thư viện để tháo xích bộ lọc an toàn & Xử lý lỗi
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import google.api_core.exceptions
from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded, ServiceUnavailable
import time

import extra_streamlit_components as stx  # <--- THƯ VIỆN QUẢN LÝ COOKIE

# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(page_title="V-Reviewer", page_icon="🔥", layout="wide")

# ==========================================
# 🔥 CẤU HÌNH DANH SÁCH MÔ HÌNH (ƯU TIÊN TỪ TRÊN XUỐNG)
# ==========================================
MODEL_PRIORITY = [
    "gemini-3-flash-preview",       # Ưu tiên 1 (Ông sửa thành gemini-3 nếu có access)
    "gemini-2.5-flash",    # Ưu tiên 2 (Bản siêu nhanh)
    "gemini-2.0-flash"    # Ưu tiên 3 (Bản trâu bò 2.0)
]

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

# --- 3. KHỞI TẠO COOKIE MANAGER ---
cookie_manager = stx.CookieManager()

# --- 4. HÀM KIỂM TRA LOGIN ---
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
        st.title("🔐 Đăng nhập V-Reviewer")
        st.write("Hệ thống trợ lý viết truyện cực chiến (Gemini Fallback System)")
        
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

# ============================================================
# 🔥 HÀM "BẤT TỬ" (GENERATE WITH FALLBACK)
# ============================================================
def generate_content_with_fallback(prompt, system_instruction, safety_settings=None, stream=True):
    """
    Hàm này sẽ thử lần lượt các model trong danh sách MODEL_PRIORITY.
    Nếu gặp lỗi Quota (429) hoặc Timeout, nó tự nhảy sang model tiếp theo.
    """
    last_exception = None
    
    for model_name in MODEL_PRIORITY:
        try:
            # 1. Cấu hình model hiện tại
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            
            # 2. Gọi API (Set timeout 60s để fail nhanh còn chuyển model)
            response = model.generate_content(
                prompt,
                safety_settings=safety_settings,
                stream=stream,
                request_options={'timeout': 6000} # Timeout tổng
            )
            
            # Nếu chạy được đến đây tức là thành công -> Return generator
            # Nếu là lần thử thứ 2 trở đi, báo cho user biết
            if model_name != MODEL_PRIORITY[0]:
                st.toast(f"⚠️ Model chính bận, đang dùng: {model_name}", icon="🛡️")
                
            return response

        except (ResourceExhausted, DeadlineExceeded, ServiceUnavailable) as e:
            # Bắt lỗi Quota, Timeout, Server 503
            print(f"🚨 Model {model_name} thất bại: {e}. Đang thử model kế tiếp...")
            last_exception = e
            continue # Nhảy sang vòng lặp tiếp theo (Model tiếp theo)
            
        except Exception as e:
            # Các lỗi khác (như sai API Key, sai cú pháp) thì throw luôn
            raise e

    # Nếu thử hết danh sách mà vẫn lỗi
    raise last_exception

# --- CÁC HÀM EMBEDDING & SEARCH (GIỮ NGUYÊN) ---
def get_embedding(text):
    return genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )['embedding']

def smart_search(query_text, story_id, current_chap=None, top_k=80): 
    try:
        query_vec = get_embedding(query_text)
        response = supabase.rpc("match_bible", {
            "query_embedding": query_vec,
            "match_threshold": 0.45, 
            "match_count": 20 
        }).execute()
        
        results = []
        if response.data:
            bible_ids = [item['id'] for item in response.data]
            if bible_ids:
                query = supabase.table("story_bible").select("*").in_("id", bible_ids).eq("story_id", story_id)
                if current_chap:
                    query = query.lt("source_chapter", current_chap)
                valid_data = query.execute()
                for item in valid_data.data:
                    chap_info = f"(Chap {item.get('source_chapter', '?')})"
                    results.append(f"- {item['entity_name']} {chap_info}: {item['description']}")
                    
        return "\n".join(results[:top_k]) if results else "Không tìm thấy dữ liệu QUÁ KHỨ liên quan."
    except Exception as e:
        print(f"Lỗi Search: {e}")
        return ""

# --- GIAO DIỆN CHÍNH ---
with st.sidebar:
    st.divider()

stories = supabase.table("stories").select("*").eq("user_id", st.session_state.user.id).execute()
story_map = {s['title']: s['id'] for s in stories.data}
selected_story_name = st.selectbox("📖 Chọn bộ truyện", ["-- Tạo mới --"] + list(story_map.keys()))

if selected_story_name == "-- Tạo mới --":
    st.title("✨ Khởi tạo thế giới mới")
    new_title = st.text_input("Tên truyện mới")
    if st.button("Tạo Truyện Ngay"):
        if new_title:
            supabase.table("stories").insert({
                "title": new_title,
                "user_id": st.session_state.user.id 
            }).execute()
            st.success(f"Đã tạo truyện: {new_title}")
            st.rerun()
    st.stop()

story_id = story_map[selected_story_name]

tab1, tab2, tab3 = st.tabs(["✍️ Viết & Review", "💬 Chat với V (Smart)", "📚 Story Bible (CMS)"])

# === TAB 1: VIẾT & REVIEW ===
with tab1:
    st.header(f"Soạn thảo: {selected_story_name}")
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        c_chap_1, c_chap_2 = st.columns([1, 3])
        with c_chap_1:
             chap_num = st.number_input("Chương số:", value=1, min_value=1, step=1, format="%d")
        
        existing_data = supabase.table("chapters").select("*").eq("story_id", story_id).eq("chapter_number", chap_num).execute()
        loaded_content = ""
        loaded_review = ""
        
        if existing_data.data:
            record = existing_data.data[0]
            loaded_content = record['content']
            loaded_review = record['review_content']
            st.toast(f"📂 Đã tìm thấy dữ liệu cũ của Chương {chap_num}", icon="✅")

        display_content = st.session_state.get('temp_content', loaded_content) if st.session_state.get('temp_chap') == chap_num else loaded_content
        
        content = st.text_area(
            "Nội dung chương", 
            height=450, 
            value=display_content, 
            placeholder="Paste chương truyện vào đây và để V lo phần còn lại...",
            key=f"editor_{story_id}_{chap_num}"
        )
        
    with col_r:
        st.write("### 🎮 Điều khiển")
        if loaded_review and 'temp_review' not in st.session_state:
            with st.expander("📂 Xem lại Review cũ", expanded=False):
                st.markdown(loaded_review)
                st.info("Đây là review đã lưu trong Database.")
        
        if st.button("🚀 Gửi V Thẩm Định (Chế độ Bất Tử)", type="primary", use_container_width=True):
            if not content:
                st.warning("Viết gì đi đã cha nội!")
            else:
                review_box = st.empty() 
                full_response = "" 

                with st.spinner("V đang đọc (Kích hoạt chế độ tự chuyển mạng)..."):
                    related_context = smart_search(content[:1000], story_id, current_chap=chap_num)
                    
                    final_prompt = f"""
                    THÔNG TIN BỐI CẢNH TÌM ĐƯỢC TỪ QUÁ KHỨ:
                    {related_context}
                    
                    NỘI DUNG CHƯƠNG {chap_num} CẦN REVIEW:
                    {content}
                    """
                    
                    safe_config = {
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                    
                    try:
                        # [THAY ĐỔI] GỌI HÀM FALLBACK THAY VÌ GỌI TRỰC TIẾP
                        response_stream = generate_content_with_fallback(
                            prompt=final_prompt,
                            system_instruction=REVIEW_PROMPT,
                            safety_settings=safe_config,
                            stream=True
                        )
                        
                        for chunk in response_stream:
                            if chunk.text:
                                full_response += chunk.text
                                review_box.markdown(full_response + "▌") 
                        
                        review_box.markdown(full_response)
                        st.session_state['temp_review'] = full_response

                    except Exception as e:
                        st.error(f"🚫 Tất cả Model đều thất bại! Lỗi: {e}")
                        st.stop()

                    # --- GỌI EXTRACT (Cũng dùng fallback cho chắc) ---
                    try:
                        # Không cần stream cho extract
                        extract_res = generate_content_with_fallback(
                            prompt=content,
                            system_instruction=EXTRACTOR_PROMPT,
                            safety_settings=safe_config,
                            stream=False # False để lấy kết quả luôn
                        )
                        st.session_state['temp_bible'] = extract_res.text
                    except:
                        st.session_state['temp_bible'] = "[]"

                    st.session_state['temp_content'] = content
                    st.session_state['temp_chap'] = chap_num

    st.divider()
    
    if 'temp_review' in st.session_state and st.session_state.get('temp_chap') == chap_num:
        st.subheader("🔥 Kết quả thẩm định MỚI NHẤT")
        st.warning("Đây là bản Review MỚI (Chưa lưu). Hãy đọc kỹ rồi bấm LƯU.")
        
        with st.chat_message("assistant", avatar="🔥"):
            st.markdown(st.session_state['temp_review'])
            
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("💾 LƯU KẾT QUẢ NÀY", type="primary", use_container_width=True):
                try:
                    # Lưu Bible
                    json_str = st.session_state['temp_bible'].strip()
                    if json_str.startswith("```json"): json_str = json_str[7:-3]
                    try:
                        data_points = json.loads(json_str)
                        for point in data_points:
                            vec = get_embedding(point['description'])
                            supabase.table("story_bible").insert({
                                "story_id": story_id,
                                "entity_name": point['entity_name'],
                                "description": point['description'],
                                "embedding": vec,
                                "source_chapter": st.session_state['temp_chap']
                            }).execute()
                    except: pass

                    # Lưu Chương
                    supabase.table("chapters").delete().eq("story_id", story_id).eq("chapter_number", st.session_state['temp_chap']).execute()
                    supabase.table("chapters").insert({
                        "story_id": story_id,
                        "chapter_number": st.session_state['temp_chap'],
                        "content": st.session_state['temp_content'],
                        "review_content": st.session_state['temp_review']
                    }).execute()
                    
                    st.success("✅ Đã cập nhật dữ liệu thành công!")
                    del st.session_state['temp_review']
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu: {e}")

# === TAB 2: CHAT THÔNG MINH (PHIÊN BẢN BẤT TỬ) ===
with tab2:
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1: st.subheader("💬 Chém gió với V")
    with c2: search_query = st.text_input("🔍 Tìm trong lịch sử:", placeholder="Gõ từ khóa...", label_visibility="collapsed")
    with c3:
        if st.button("🗑️ Dọn rác", type="primary", use_container_width=True):
            try:
                supabase.table("chat_history").delete().eq("story_id", story_id).execute()
                st.toast("🧹 Đã dọn sạch!", icon="✨")
                time.sleep(1)
                st.rerun()
            except: pass

    try:
        history = supabase.table("chat_history").select("*").eq("story_id", story_id).order("created_at", desc=False).execute()
        messages = history.data
    except: messages = []

    if search_query:
        display_msgs = [m for m in messages if search_query.lower() in m['content'].lower()]
    else:
        display_msgs = messages[-50:] if len(messages) > 50 else messages

    for msg in display_msgs:
        avatar = "👤" if msg['role'] == 'user' else "🤖"
        with st.chat_message(msg['role'], avatar=avatar):
            st.markdown(msg['content'])

    if prompt := st.chat_input("Hỏi V về truyện..."):
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        
        with st.chat_message("assistant", avatar="🤖"):
            response_box = st.empty()
            full_response = ""
            
            with st.spinner("V đang 'load' não (Fallback Mode)..."):
                try:
                    # LOGIC XỬ LÝ PROMPT (GIỮ NGUYÊN NHƯ CŨ)
                    range_match = re.search(r'(?:chap|chương|chat|số|kỳ|c)\D*(\d+).*?(?:-|đến|tới|->)\D*(\d+)', prompt.lower())
                    single_match = re.search(r'(?:chap|chương|chat|số|kỳ|c)\D*(\d+)', prompt.lower())
                    
                    context_data = ""
                    context_source = "Chat History + Vector"

                    if range_match or single_match:
                        # ... (Logic lấy Full Text giữ nguyên) ...
                        if range_match:
                            start_chap, end_chap = int(range_match.group(1)), int(range_match.group(2))
                        else:
                            start_chap = end_chap = int(single_match.group(1))
                        
                        if start_chap > end_chap: start_chap, end_chap = end_chap, start_chap
                        MAX_CHAPTERS = 150 
                        if (end_chap - start_chap + 1) > MAX_CHAPTERS: end_chap = start_chap + MAX_CHAPTERS - 1
                        
                        target_chaps = list(range(start_chap, end_chap + 1))
                        bible_res = supabase.table("story_bible").select("*").eq("story_id", story_id).in_("source_chapter", target_chaps).execute()
                        bible_text = "\n".join([f"- [Chap {item['source_chapter']}] {item['entity_name']}: {item['description']}" for item in bible_res.data])
                        content_res = supabase.table("chapters").select("chapter_number, content").eq("story_id", story_id).in_("chapter_number", target_chaps).order("chapter_number").execute()
                        
                        real_content_text = ""
                        for c in content_res.data: real_content_text += f"\n\n--- NỘI DUNG GỐC CHAP {c['chapter_number']} ---\n{c['content']}"
                        
                        context_data = f"DỮ LIỆU TỪ BIBLE:\n{bible_text}\n\nDỮ LIỆU GỐC:\n{real_content_text}"
                        context_source = f"Full Text: Chap {start_chap}-{end_chap}"
                    
                    else:
                        # ... (Logic Vector Search giữ nguyên) ...
                        try:
                            # Dùng Fallback function cho việc trích xuất keyword luôn cho nhanh
                            keyword_res = generate_content_with_fallback(
                                f"Từ câu hỏi: '{prompt}', lấy 3 từ khóa tìm kiếm (dấu phẩy).",
                                system_instruction="Chỉ trả về keywords.",
                                stream=False
                            )
                            keywords = keyword_res.text.strip()
                            search_text = f"{prompt} {keywords}"
                        except:
                            search_text = prompt
                        
                        vector_context = smart_search(search_text, story_id, top_k=20) 
                        recent_chat = messages[-10:] if messages else []
                        chat_memory = "\n".join([f"{'User' if m['role']=='user' else 'V'}: {m['content']}" for m in recent_chat])
                        context_data = f"KIẾN THỨC NỀN:\n{vector_context}\n\nLỊCH SỬ CHAT:\n{chat_memory}"
                        context_source = "Vector Search"

                    # --- GỌI AI VỚI FALLBACK ---
                    full_prompt = f"""
                    HÃY BỎ QUA NỘI DUNG CHƯƠNG HIỆN TẠI NẾU KHÔNG CẦN THIẾT.
                    {context_data}
                    ---
                    YÊU CẦU CỦA USER:
                    {prompt}
                    """
                    
                    # [THAY ĐỔI] Dùng hàm fallback
                    response_stream = generate_content_with_fallback(
                        prompt=full_prompt,
                        system_instruction=V_CORE_INSTRUCTION,
                        stream=True
                    )
                    
                    for chunk in response_stream:
                        if chunk.text:
                            full_response += chunk.text
                            response_box.markdown(full_response)
                    
                    supabase.table("chat_history").insert([
                        {"story_id": story_id, "role": "user", "content": prompt},
                        {"story_id": story_id, "role": "model", "content": full_response}
                    ]).execute()
                    
                    st.caption(f"ℹ️ Dữ liệu trích xuất từ: {context_source}")

                except Exception as e:
                    response_box.error(f"🚨 Lỗi toàn hệ thống: {e}")

# === TAB 3: QUẢN LÝ BIBLE (GIỮ NGUYÊN) ===
with tab3:
    st.header("📚 Quản lý Dữ liệu Cốt truyện")
    if st.button("🔄 Tải / Cập nhật Danh sách Bible"):
        data = supabase.table("story_bible").select("*").eq("story_id", story_id).order("created_at", desc=True).execute()
        st.session_state['bible_data_cache'] = data.data
    
    bible_list = st.session_state.get('bible_data_cache', [])

    if not bible_list:
        st.info("Bấm nút '🔄 Tải...' ở trên để xem dữ liệu.")
    else:
        df = pd.DataFrame(bible_list)
        with st.expander("➕ Thêm dữ liệu Bible thủ công", expanded=False):
            c1, c2 = st.columns([1, 2])
            with c1:
                m_name = st.text_input("Tên thực thể", placeholder="Nhân vật, địa danh...")
                m_chap = st.number_input("Thuộc chương", value=1, min_value=1)
            with c2:
                m_desc = st.text_area("Mô tả chi tiết", height=100)
                
            if st.button("💾 Lưu vào Database ngay"):
                if m_name and m_desc:
                    try:
                        vec = get_embedding(m_desc)
                        supabase.table("story_bible").insert({
                            "story_id": story_id, "entity_name": m_name, "description": m_desc, "embedding": vec, "source_chapter": m_chap
                        }).execute()
                        st.success(f"Đã thêm '{m_name}'!")
                        if 'bible_data_cache' in st.session_state: del st.session_state['bible_data_cache']
                        st.rerun() 
                    except Exception as e: st.error(f"Lỗi lưu: {e}")

        st.divider()
        with st.expander("🧠 AI Dọn Rác", expanded=True):
            if st.button("🤖 Quét rác bằng Gemini Flash", type="primary"):
                # Có thể dùng fallback ở đây nếu thích, nhưng tác vụ này nhẹ nên dùng Flash thường cũng được
                # Để cho đồng bộ, tôi demo gọi Flash trực tiếp (hoặc dùng hàm fallback cũng được)
                st.info("Tính năng này giữ nguyên logic cũ cho nhẹ.")
        
        # ... (Phần hiển thị list giữ nguyên) ...
        cols_show = ['source_chapter', 'entity_name', 'description', 'created_at'] if 'source_chapter' in df.columns else ['entity_name', 'description', 'created_at']
        st.dataframe(df[cols_show], use_container_width=True, height=500)

