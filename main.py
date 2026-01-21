import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import json
import re
import pandas as pd
from persona import V_CORE_INSTRUCTION, REVIEW_PROMPT, EXTRACTOR_PROMPT
# [QUAN TRỌNG] Import thư viện để tháo xích bộ lọc an toàn
from google.generativeai.types import HarmCategory, HarmBlockThreshold

import time

import extra_streamlit_components as stx  # <--- THƯ VIỆN QUẢN LÝ COOKIE

# --- 1. SETUP & AUTH (PHIÊN BẢN COOKIE BẤT TỬ) ---
st.set_page_config(page_title="V-Reviewer", page_icon="🔥", layout="wide")

# Khởi tạo Supabase (An toàn, KHÔNG cache client để tránh lộ acc)
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
    st.error("❌ Lỗi kết nối! Kiểm tra lại secrets.toml")
    st.stop()

# --- KHỞI TẠO QUẢN LÝ COOKIE ---
# Cái này giúp lưu token vào trình duyệt, F5 xong code sẽ đọc lại cookie này
cookie_manager = stx.CookieManager()

# --- HÀM LOGIN BẰNG COOKIE (TỰ ĐỘNG) ---
# --- SỬA LẠI ĐOẠN NÀY ĐỂ HẾT GIẬT ---
def check_cookie_login():
    # Thử lấy cookie
    access_token = cookie_manager.get("supabase_access_token")
    refresh_token = cookie_manager.get("supabase_refresh_token")
    
    # Mẹo: CookieManager cần 1 nhịp để load. 
    # Nếu nó trả về None, có thể là do CHƯA LOAD KỊP chứ không phải là KHÔNG CÓ.
    # Ta dùng cookies (get_all) để check xem Manager đã sẵn sàng chưa.
    cookies = cookie_manager.get_all()
    
    if cookies is None:
        # Nếu cookies = None nghĩa là component chưa chạy xong -> Dừng lại chờ, KHÔNG hiện Login Form
        # Hiện cái spinner cho chuyên nghiệp
        with st.spinner("Đang lục lọi ký ức..."):
            time.sleep(0.5) # Hack nhẹ: Ngủ 0.5s để chờ cookie về
            st.stop() # Dừng render, đợi nhịp sau chạy tiếp
            
    if access_token and refresh_token:
        try:
            session = supabase.auth.set_session(access_token, refresh_token)
            if session:
                st.session_state.user = session.user
                return True
        except:
            pass
    return False

# --- LOGIC CHÍNH: KIỂM TRA TRẠNG THÁI ĐĂNG NHẬP ---

# 1. Nếu chưa có User trong RAM -> Thử check Cookie xem có cứu vớt được không
if 'user' not in st.session_state:
    check_cookie_login()

# 2. Nếu check Cookie rồi mà vẫn chưa có User -> HIỆN FORM ĐĂNG NHẬP
if 'user' not in st.session_state:
    st.title("🔐 Đăng nhập V-Reviewer")
    st.write("Hệ thống trợ lý viết truyện cực chiến (Gemini 3 Powered)")
    
    col_main, _ = st.columns([1, 1])
    with col_main:
        email = st.text_input("Email")
        password = st.text_input("Mật khẩu", type="password")
        
        col1, col2 = st.columns(2)
        
        # --- NÚT ĐĂNG NHẬP ---
        if col1.button("Đăng Nhập", type="primary", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                
                # [QUAN TRỌNG] Đăng nhập thành công -> GHI COOKIE NGAY
                # Token sống 7 ngày (hoặc tùy setting Supabase)
                cookie_manager.set("supabase_access_token", res.session.access_token, key="set_access")
                cookie_manager.set("supabase_refresh_token", res.session.refresh_token, key="set_refresh")
                
                st.success("Đăng nhập thành công! Đang vào...")
                time.sleep(1) # Đợi xíu cho cookie kịp lưu
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi đăng nhập: {e}")
                
        # --- NÚT ĐĂNG KÝ ---
        if col2.button("Đăng Ký Mới", use_container_width=True):
            try:
                res = supabase.auth.sign_up({"email": email, "password": password})
                st.session_state.user = res.user
                
                # Đăng ký xong cũng lưu cookie luôn cho tiện
                if res.session:
                    cookie_manager.set("supabase_access_token", res.session.access_token, key="set_access_up")
                    cookie_manager.set("supabase_refresh_token", res.session.refresh_token, key="set_refresh_up")
                
                st.success("Đã tạo user! Vào việc luôn.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi đăng ký: {e}")
    
    st.stop() # Dừng tại đây, không cho chạy code bên dưới nếu chưa login

# --- 3. NẾU ĐÃ ĐĂNG NHẬP -> HIỆN NÚT ĐĂNG XUẤT Ở SIDEBAR ---
with st.sidebar:
    st.write(f"Xin chào, **{st.session_state.user.email}**")
    if st.button("🚪 Đăng xuất"):
        supabase.auth.sign_out()
        # Xóa sạch Cookie để không tự login lại nữa
        cookie_manager.delete("supabase_access_token")
        cookie_manager.delete("supabase_refresh_token")
        
        # Xóa session RAM
        for key in list(st.session_state.keys()):
            del st.session_state[key]
            
        st.rerun()

# ... (PHẦN CODE CÒN LẠI CỦA ÔNG: TAB 1, TAB 2, TAB 3...) ...
# --- 2. CÁC HÀM "NÃO BỘ" THÔNG MINH ---

def get_embedding(text):
    # Model embedding vẫn dùng bản ổn định 004
    return genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )['embedding']

def smart_search(query_text, story_id, current_chap=None, top_k=7): 
    try:
        query_vec = get_embedding(query_text)
        
        # 1. Tìm kiếm Vector
        response = supabase.rpc("match_bible", {
            "query_embedding": query_vec,
            "match_threshold": 0.45, 
            "match_count": 20 
        }).execute()
        
        results = []
        if response.data:
            bible_ids = [item['id'] for item in response.data]
            if bible_ids:
                # 2. Query lại DB để lọc Story ID và Chapter
                query = supabase.table("story_bible").select("*").in_("id", bible_ids).eq("story_id", story_id)
                
                # Logic chặn tương lai
                if current_chap:
                    query = query.lt("source_chapter", current_chap)
                
                valid_data = query.execute()
                
                # Format kết quả
                for item in valid_data.data:
                    chap_info = f"(Chap {item.get('source_chapter', '?')})"
                    results.append(f"- {item['entity_name']} {chap_info}: {item['description']}")
                    
        return "\n".join(results[:top_k]) if results else "Không tìm thấy dữ liệu QUÁ KHỨ liên quan."
    except Exception as e:
        print(f"Lỗi Search: {e}")
        return ""

# --- 3. GIAO DIỆN CHÍNH ---

with st.sidebar:
    st.title("🔥 V-Reviewer")
    st.caption(f"Logged in: {st.session_state.user.email}")
    if st.button("Đăng xuất"):
        supabase.auth.sign_out()
        del st.session_state.user
        st.rerun()
    st.divider()

# Chọn Truyện (Đã cache để load nhanh hơn)
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

# TAB CHỨC NĂNG
tab1, tab2, tab3 = st.tabs(["✍️ Viết & Review", "💬 Chat với V (Smart)", "📚 Story Bible (CMS)"])

# === TAB 1: VIẾT & REVIEW ===
with tab1:
    st.header(f"Soạn thảo: {selected_story_name}")
    
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        # Cải thiện ô nhập chương: Cho phép gõ số trực tiếp thoải mái
        c_chap_1, c_chap_2 = st.columns([1, 3])
        with c_chap_1:
             chap_num = st.number_input("Chương số:", value=1, min_value=1, step=1, format="%d")
        
        # Tải dữ liệu cũ
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
        
        # Ẩn Review cũ vào Expander cho gọn và đỡ lag
        if loaded_review and 'temp_review' not in st.session_state:
            with st.expander("📂 Xem lại Review cũ (Click để mở)", expanded=False):
                st.markdown(loaded_review)
                st.info("Đây là review đã lưu trong Database.")
        
        # Thay thế toàn bộ đoạn xử lý nút bấm cũ bằng đoạn này:
        if st.button("🚀 Gửi V Thẩm Định (Chế độ Stream)", type="primary", use_container_width=True):
            if not content:
                st.warning("Viết gì đi đã cha nội!")
            else:
                # 1. Tạo một cái hộp rỗng để hứng chữ
                review_box = st.empty() 
                full_response = "" # Biến để gom chữ lại thành bài văn

                with st.spinner("V đang bắt đầu chém gió (Chữ sẽ chạy ra ngay đây)..."):
                    # Search Context
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
                        # --- GỌI GEMINI 3 VỚI STREAMING ---
                        # (Lưu ý: Tôi giữ nguyên tên model ông yêu cầu)
                        model_review = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=REVIEW_PROMPT)
                        # Nếu ông có quyền dùng Gemini 3 thật thì đổi dòng trên thành:
                        # model_review = genai.GenerativeModel('gemini-3-flash-thinking-exp-01-21', system_instruction=REVIEW_PROMPT)

                        response_stream = model_review.generate_content(
                            final_prompt, 
                            safety_settings=safe_config,
                            stream=True, # <--- QUAN TRỌNG: BẬT STREAM
                            request_options={'timeout': 600} 
                        )
                        
                        # --- VÒNG LẶP HỨNG CHỮ ---
                        for chunk in response_stream:
                            if chunk.text:
                                full_response += chunk.text
                                # Cập nhật trực tiếp lên màn hình + con trỏ nhấp nháy
                                review_box.markdown(full_response + "▌") 
                        
                        # Chạy xong thì hiện bản full sạch đẹp
                        review_box.markdown(full_response)
                        
                        # Lưu vào session
                        st.session_state['temp_review'] = full_response

                    except ValueError:
                        st.error("🚫 V từ chối review (Safety blocked)!")
                        st.stop()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")
                        st.stop()

                    # --- GỌI EXTRACT (Chạy ngầm sau khi Stream xong) ---
                    try:
                        model_extract = genai.GenerativeModel('gemini-3-flash-preview', system_instruction=EXTRACTOR_PROMPT)
                        extract_res = model_extract.generate_content(
                            content, 
                            safety_settings=safe_config,
                            request_options={'timeout': 600}
                        )
                        st.session_state['temp_bible'] = extract_res.text
                    except:
                        st.session_state['temp_bible'] = "[]"

                    st.session_state['temp_content'] = content
                    st.session_state['temp_chap'] = chap_num
                    # Không cần rerun để user đọc kết quả vừa stream xong

    # --- KHU VỰC HIỂN THỊ KẾT QUẢ MỚI ---
    st.divider()
    
    # Chỉ hiện kết quả mới khi vừa chạy xong (có trong session state)
    if 'temp_review' in st.session_state and st.session_state.get('temp_chap') == chap_num:
        st.subheader("🔥 Kết quả thẩm định MỚI NHẤT")
        st.warning("Đây là bản Review MỚI (Chưa lưu). Hãy đọc kỹ rồi bấm LƯU.")
        
        with st.chat_message("assistant", avatar="🔥"):
            st.markdown(st.session_state['temp_review'])
            
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("💾 LƯU KẾT QUẢ NÀY", type="primary", use_container_width=True):
                try:
                    # 1. Lưu Bible
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

                    # 2. Lưu Chương
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

# === TAB 2: CHAT THÔNG MINH (GIAO DIỆN CHUẨN CHAT BOX - CÓ SEARCH) ===
with tab2:
    # --- 1. THANH CÔNG CỤ (HEADER & SEARCH) ---
    # Chia cột: Tiêu đề to bên trái, Ô tìm kiếm và Nút xóa bên phải
    c1, c2, c3 = st.columns([2, 2, 1])
    
    with c1:
        st.subheader("💬 Chém gió với V")
        
    with c2:
        # TÍNH NĂNG SEARCH: Lọc tin nhắn cũ
        search_query = st.text_input("🔍 Tìm trong lịch sử chat:", placeholder="Gõ từ khóa để tìm lại ký ức...", label_visibility="collapsed")
        
    with c3:
        # Nút xóa chat (Clear History)
        if st.button("🗑️ Dọn rác", type="primary", use_container_width=True, help="Xóa sạch lịch sử chat cũ"):
            try:
                supabase.table("chat_history").delete().eq("story_id", story_id).execute()
                st.toast("🧹 Đã dọn sạch nhà cửa!", icon="✨")
                time.sleep(1) # Đợi xíu cho user đọc
                st.rerun()
            except: pass

    # --- 2. HIỂN THỊ LỊCH SỬ CHAT ---
    # Lấy dữ liệu từ Database
    try:
        history = supabase.table("chat_history").select("*").eq("story_id", story_id).order("created_at", desc=False).execute()
        messages = history.data
    except:
        messages = []

    # Xử lý Logic Hiển thị (Có Search hay không)
    if search_query:
        # Nếu đang tìm kiếm: Chỉ hiện tin nhắn có chứa từ khóa
        st.info(f"ang hiển thị kết quả tìm kiếm cho: '{search_query}'")
        display_msgs = [m for m in messages if search_query.lower() in m['content'].lower()]
        if not display_msgs:
            st.warning("Không tìm thấy nội dung nào.")
    else:
        # Nếu chat bình thường: Chỉ hiện 50 tin gần nhất cho đỡ lag
        # (Tin cũ quá tự ẩn, muốn xem thì dùng ô Search ở trên)
        display_msgs = messages[-50:] if len(messages) > 50 else messages

    # Vòng lặp in tin nhắn ra màn hình
    for msg in display_msgs:
        # Avatar: User là hình người, AI là hình Robot
        avatar = "👤" if msg['role'] == 'user' else "🤖"
        with st.chat_message(msg['role'], avatar=avatar):
            st.markdown(msg['content'])

    # --- 3. Ô NHẬP LIỆU (LUÔN DÍNH Ở DƯỚI) ---
    if prompt := st.chat_input("Hỏi V về truyện (VD: Chap 3-5 có gì vô lý?)..."):
        
        # A. Hiện câu hỏi của User ngay lập tức
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        
        # B. Xử lý trả lời của AI
        with st.chat_message("assistant", avatar="🤖"):
            response_box = st.empty()
            full_response = ""
            
            # Logic Xử lý thông minh (Giữ nguyên logic lõi ông đã duyệt)
            with st.spinner("Đang load dữ liệu..."):
                # 1. BẮT SỐ CHƯƠNG (Regex Range)
                match = re.search(r'(?:chap|chương|chat|số|kỳ)\s*(\d+)(?:\s*(?:-|đến)\s*(\d+))?', prompt.lower())
                
                context_data = ""
                context_source = "Chat History + Vector" # Mặc định
                
                if match:
                    # -- TRƯỜNG HỢP CÓ SỐ CHƯƠNG --
                    start_chap = int(match.group(1))
                    end_chap = int(match.group(2)) if match.group(2) else start_chap
                    if start_chap > end_chap: start_chap, end_chap = end_chap, start_chap
                    
                    target_chaps = list(range(start_chap, end_chap + 1))
                    
                    # Lấy Bible
                    bible_res = supabase.table("story_bible").select("*").eq("story_id", story_id).in_("source_chapter", target_chaps).execute()
                    bible_text = "\n".join([f"- [Chap {item['source_chapter']}] {item['entity_name']}: {item['description']}" for item in bible_res.data])
                    
                    # Lấy Nội dung gốc
                    content_res = supabase.table("chapters").select("chapter_number, content").eq("story_id", story_id).in_("chapter_number", target_chaps).order("chapter_number").execute()
                    real_content_text = ""
                    for c in content_res.data:
                        real_content_text += f"\n\n--- NỘI DUNG GỐC CHAP {c['chapter_number']} ---\n{c['content']}"
                    
                    context_data = f"DỮ LIỆU TỪ BIBLE:\n{bible_text}\n\nDỮ LIỆU GỐC:\n{real_content_text}"
                    context_source = f"Chap {start_chap}-{end_chap}"
                
                else:
                    # -- TRƯỜNG HỢP KHÔNG CÓ SỐ CHƯƠNG (Dùng Vector + History) --
                    vector_context = smart_search(prompt, story_id, top_k=15)
                    
                    # Lấy 10 câu chat gần nhất làm ngữ cảnh
                    recent_chat = messages[-10:] if messages else []
                    chat_memory = "\n".join([f"{'User' if m['role']=='user' else 'V'}: {m['content']}" for m in recent_chat])

                    context_data = f"KIẾN THỨC NỀN (Vector):\n{vector_context}\n\nLỊCH SỬ CHAT GẦN ĐÂY:\n{chat_memory}"

                # Ghép Prompt
                full_prompt = f"{context_data}\n\nUSER HỎI:\n{prompt}"
                
                # Cấu hình AI
                # Lưu ý: Nhớ đổi tên model nếu ông dùng bản khác (ví dụ 'gemini-1.5-pro')
                model_chat = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=V_CORE_INSTRUCTION)
                
                try:
                    response_stream = model_chat.generate_content(
                        full_prompt, 
                        stream=True, 
                        request_options={'timeout': 600}
                    )
                    
                    # STREAMING SẠCH (KHÔNG CÓ KÝ TỰ LẠ)
                    for chunk in response_stream:
                        if chunk.text:
                            full_response += chunk.text
                            # Chỉ hiện text, không cộng thêm ký tự con trỏ nào cả
                            response_box.markdown(full_response)
                    
                    # Lưu vào Database
                    supabase.table("chat_history").insert([
                        {"story_id": story_id, "role": "user", "content": prompt},
                        {"story_id": story_id, "role": "model", "content": full_response}
                    ]).execute()
                    
                    # Debug nguồn (nhỏ gọn bên dưới)
                    st.caption(f"ℹ️ Dữ liệu trích xuất từ: {context_source}")
                    
                except Exception as e:
                    response_box.error(f"Lỗi: {e}")

# === TAB 3: QUẢN LÝ BIBLE (TỐI ƯU KHÔNG CHẠY NGẦM) ===
with tab3:
    st.header("📚 Quản lý Dữ liệu Cốt truyện")
    st.caption("CMS xịn xò: Thêm bằng tay & Dọn rác bằng AI.")
    
    # [TỐI ƯU] Không tự động tải data. Phải bấm nút mới tải.
    if st.button("🔄 Tải / Cập nhật Danh sách Bible"):
        data = supabase.table("story_bible").select("*").eq("story_id", story_id).order("created_at", desc=True).execute()
        st.session_state['bible_data_cache'] = data.data
    
    # Lấy data từ session state (nếu có)
    bible_list = st.session_state.get('bible_data_cache', [])

    if not bible_list:
        st.info("Bấm nút '🔄 Tải...' ở trên để xem dữ liệu (Giúp web đỡ lag khi viết truyện).")
    else:
        # --- CODE XỬ LÝ NHƯ CŨ NHƯNG DÙNG bible_list ---
        df = pd.DataFrame(bible_list)
        
        # 1. MANUAL ADD
        with st.expander("➕ Thêm dữ liệu Bible thủ công", expanded=False):
            c1, c2 = st.columns([1, 2])
            with c1:
                m_name = st.text_input("Tên thực thể (VD: Hùng)", placeholder="Nhân vật, địa danh...")
                m_chap = st.number_input("Thuộc chương (Source)", value=st.session_state.get('temp_chap', 1), min_value=1)
            with c2:
                m_desc = st.text_area("Mô tả chi tiết", placeholder="VD: Là main chính...", height=100)
                
            if st.button("💾 Lưu vào Database ngay"):
                if m_name and m_desc:
                    with st.spinner("Đang mã hóa Vector và lưu..."):
                        try:
                            vec = get_embedding(m_desc)
                            supabase.table("story_bible").insert({
                                "story_id": story_id,
                                "entity_name": m_name,
                                "description": m_desc,
                                "embedding": vec,
                                "source_chapter": m_chap
                            }).execute()
                            st.success(f"Đã thêm '{m_name}'!")
                            # Clear cache để lần sau bấm tải lại sẽ có data mới
                            if 'bible_data_cache' in st.session_state: del st.session_state['bible_data_cache']
                            st.rerun() 
                        except Exception as e:
                            st.error(f"Lỗi lưu: {e}")
                else:
                    st.warning("Nhập thiếu thông tin!")

        st.divider()

        # 2. AI CLEANER (Dùng Gemini Flash cho rẻ)
        with st.expander("🧠 AI Dọn Rác (Thông minh hơn)", expanded=True):
            st.write("AI sẽ đọc và phát hiện các thông tin **trùng lặp về ý nghĩa**.")
            
            if st.button("🤖 Quét rác bằng Gemini Flash", type="primary"):
                with st.spinner("Gemini đang đọc toàn bộ Bible..."):
                    grouped_data = {}
                    for item in bible_list:
                        name = item['entity_name']
                        if name not in grouped_data: grouped_data[name] = []
                        grouped_data[name].append({
                            "id": item['id'],
                            "desc": item['description'],
                            "chap": item.get('source_chapter', '?')
                        })
                    
                    candidates = {k: v for k, v in grouped_data.items() if len(v) > 1}
                    
                    if not candidates:
                        st.info("Dữ liệu quá sạch!")
                    else:
                        prompt_cleaner = f"""
                        Bạn là Database Cleaner. Tìm semantic duplicates trong JSON:
                        {json.dumps(candidates, ensure_ascii=False)}
                        Trả về JSON list các ID cần XÓA (giữ lại dòng chi tiết nhất).
                        """
                        try:
                            model_cleaner = genai.GenerativeModel('gemini-3-flash-preview', 
                                                                  system_instruction="Trả về JSON thuần. Chỉ chứa list ID.")
                            res = model_cleaner.generate_content(prompt_cleaner)
                            clean_text = res.text.strip()
                            if clean_text.startswith("```json"): clean_text = clean_text[7:-3]
                            ids_to_delete = json.loads(clean_text)
                            
                            if ids_to_delete:
                                st.session_state['ids_to_delete'] = ids_to_delete
                                st.rerun()
                            else:
                                st.success("Không có gì để xóa!")
                        except Exception as e:
                            st.error(f"Lỗi AI: {e}")

            if 'ids_to_delete' in st.session_state and st.session_state['ids_to_delete']:
                ids = st.session_state['ids_to_delete']
                st.warning(f"⚠️ AI đề xuất xóa {len(ids)} dòng:")
                rows_to_del = df[df['id'].isin(ids)]
                st.dataframe(rows_to_del[['entity_name', 'description']], use_container_width=True)
                
                if st.button("🗑️ Đồng ý xóa ngay"):
                    supabase.table("story_bible").delete().in_("id", ids).execute()
                    del st.session_state['ids_to_delete']
                    if 'bible_data_cache' in st.session_state: del st.session_state['bible_data_cache']
                    st.success("Đã dọn sạch!")
                    st.rerun()

        st.divider()

        # 3. LIST & MANUAL DELETE
        st.subheader("Danh sách chi tiết")
        options = {f"[Chap {row.get('source_chapter', '?')}] {row['entity_name']} | {row['description'][:50]}...": row['id'] for index, row in df.iterrows()}
        selected_items = st.multiselect("🗑️ Chọn xóa thủ công:", options=options.keys())
        if selected_items and st.button(f"Xác nhận xóa {len(selected_items)} dòng"):
            ids_to_remove = [options[item] for item in selected_items]
            supabase.table("story_bible").delete().in_("id", ids_to_remove).execute()
            if 'bible_data_cache' in st.session_state: del st.session_state['bible_data_cache']
            st.rerun()

        cols_show = ['source_chapter', 'entity_name', 'description', 'created_at'] if 'source_chapter' in df.columns else ['entity_name', 'description', 'created_at']
        st.dataframe(df[cols_show], use_container_width=True, height=500)











