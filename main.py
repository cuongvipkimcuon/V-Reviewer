import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import json
import pandas as pd
from persona import V_CORE_INSTRUCTION, REVIEW_PROMPT, EXTRACTOR_PROMPT

# --- 1. SETUP & AUTH ---
st.set_page_config(page_title="V-Reviewer", page_icon="🔥", layout="wide")

# Lấy Key từ secrets
try:
    SUPABASE_URL = st.secrets["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["supabase"]["SUPABASE_KEY"]
    GEMINI_KEY = st.secrets["gemini"]["API_KEY"]
except:
    st.error("❌ Chưa cấu hình secrets.toml! Xem lại hướng dẫn Bước 3.")
    st.stop()

# Kết nối
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_KEY)

# Hàm Login đơn giản
def login_page():
    st.title("🔐 Đăng nhập V-Reviewer")
    st.write("Hệ thống trợ lý viết truyện cực chiến")
    
    col_main, _ = st.columns([1, 1])
    with col_main:
        email = st.text_input("Email")
        password = st.text_input("Mật khẩu", type="password")
        
        col1, col2 = st.columns(2)
        if col1.button("Đăng Nhập", type="primary", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi đăng nhập: {e}")
                
        if col2.button("Đăng Ký Mới", use_container_width=True):
            try:
                res = supabase.auth.sign_up({"email": email, "password": password})
                st.session_state.user = res.user
                st.success("Đã tạo user! Hãy đăng nhập lại.")
            except Exception as e:
                st.error(f"Lỗi đăng ký: {e}")

if 'user' not in st.session_state:
    login_page()
    st.stop()

# --- 2. CÁC HÀM "NÃO BỘ" THÔNG MINH ---

def get_embedding(text):
    return genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )['embedding']

def smart_search(query_text, story_id, top_k=5):
    try:
        query_vec = get_embedding(query_text)
        response = supabase.rpc("match_bible", {
            "query_embedding": query_vec,
            "match_threshold": 0.5,
            "match_count": top_k
        }).execute()
        
        results = []
        if response.data:
            # Lọc lại ID thuộc story này (Double check)
            bible_ids = [item['id'] for item in response.data]
            if bible_ids:
                valid_data = supabase.table("story_bible").select("*").in_("id", bible_ids).eq("story_id", story_id).execute()
                results = [f"- {item['entity_name']}: {item['description']}" for item in valid_data.data]
        return "\n".join(results) if results else "Không tìm thấy dữ liệu cũ liên quan."
    except Exception as e:
        return ""

# --- 3. GIAO DIỆN CHÍNH ---

# Sidebar
with st.sidebar:
    st.title("🔥 V-Reviewer")
    st.caption(f"Logged in: {st.session_state.user.email}")
    if st.button("Đăng xuất"):
        supabase.auth.sign_out()
        del st.session_state.user
        st.rerun()
    st.divider()

# Chọn Truyện
stories = supabase.table("stories").select("*").execute()
story_map = {s['title']: s['id'] for s in stories.data}
selected_story_name = st.selectbox("📖 Chọn bộ truyện", ["-- Tạo mới --"] + list(story_map.keys()))

if selected_story_name == "-- Tạo mới --":
    st.title("✨ Khởi tạo thế giới mới")
    st.info("👈 Nhìn sang cột bên trái để chọn truyện hoặc tạo mới tại đây.")
    new_title = st.text_input("Tên truyện mới")
    if st.button("Tạo Truyện Ngay"):
        if new_title:
            supabase.table("stories").insert({"title": new_title}).execute()
            st.success(f"Đã tạo truyện: {new_title}")
            st.rerun()
    st.stop()

story_id = story_map[selected_story_name]

# TAB CHỨC NĂNG
tab1, tab2, tab3 = st.tabs(["✍️ Viết & Review", "💬 Chat với V (Smart)", "📚 Story Bible"])

# === TAB 1: VIẾT & REVIEW (LOGIC MỚI: PREVIEW -> SAVE) ===
# === TAB 1: VIẾT & REVIEW (CÓ TÍNH NĂNG LOAD DỮ LIỆU CŨ) ===
with tab1:
    st.header(f"Soạn thảo: {selected_story_name}")
    
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        # 1. Chọn số chương
        chap_num = st.number_input("Chương số", value=1, min_value=1)
        
        # --- LOGIC MỚI: TỰ ĐỘNG TẢI DỮ LIỆU CŨ TỪ DB ---
        # Tìm xem chương này đã lưu trong Database chưa
        existing_data = supabase.table("chapters").select("*").eq("story_id", story_id).eq("chapter_number", chap_num).execute()
        
        loaded_content = ""
        loaded_review = ""
        
        if existing_data.data:
            # Nếu tìm thấy, lấy dữ liệu ra
            record = existing_data.data[0]
            loaded_content = record['content']
            loaded_review = record['review_content']
            st.toast(f"📂 Đã tải lại nội dung cũ của Chương {chap_num}!", icon="✅")

        # 2. Ô nhập liệu (Dùng key động để nó tự reset khi đổi số chương)
        # Logic ưu tiên: Nếu đang có temp (vừa bấm review xong) thì lấy temp, nếu không thì lấy data cũ từ DB
        display_content = st.session_state.get('temp_content', loaded_content) if st.session_state.get('temp_chap') == chap_num else loaded_content
        
        content = st.text_area(
            "Nội dung chương", 
            height=450, 
            value=display_content, 
            placeholder="Chương này chưa có nội dung...",
            key=f"editor_{story_id}_{chap_num}" # QUAN TRỌNG: Key này giúp reset ô nhập khi đổi chương
        )
        
    with col_r:
        st.write("### 🎮 Điều khiển")
        
        # Nếu đã có review cũ trong DB, hiện thông báo
        if loaded_review and 'temp_review' not in st.session_state:
            st.info("✅ Chương này đã được Review và Lưu trước đó.")
        
        if st.button("🚀 Gửi V Thẩm Định", type="primary", use_container_width=True):
            if not content:
                st.warning("Viết gì đi đã cha nội!")
            else:
                with st.spinner("V đang đọc, lục lại trí nhớ và soi mói..."):
                    # Các bước Review y hệt cũ
                    related_context = smart_search(content[:1000], story_id)
                    
                    final_prompt = f"""
                    THÔNG TIN BỐI CẢNH TÌM ĐƯỢC TỪ QUÁ KHỨ:
                    {related_context}
                    
                    NỘI DUNG CHƯƠNG CẦN REVIEW:
                    {content}
                    """
                    model_review = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=REVIEW_PROMPT)
                    review_res = model_review.generate_content(final_prompt)
                    
                    model_extract = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=EXTRACTOR_PROMPT)
                    extract_res = model_extract.generate_content(content)
                    
                    # Lưu vào Session State
                    st.session_state['temp_review'] = review_res.text
                    st.session_state['temp_bible'] = extract_res.text
                    st.session_state['temp_content'] = content
                    st.session_state['temp_chap'] = chap_num
                    st.rerun() # Load lại trang để hiển thị kết quả

    # --- KHU VỰC HIỂN THỊ KẾT QUẢ ---
    st.divider()
    
    # Ưu tiên hiển thị Review mới nhất (Temp), nếu không có thì hiển thị Review cũ (DB)
    # MỚI (CHUẨN): Ưu tiên Temp, nếu Temp rỗng thì lấy Database
    temp_r = st.session_state.get('temp_review')
    if st.session_state.get('temp_chap') == chap_num and temp_r:
        display_review = temp_r
    else:
        display_review = loaded_review
    
    if display_review:
        st.subheader("🧐 Kết quả thẩm định")
        
        # Nếu đây là review CŨ (đã lưu), hiện thẻ màu xanh cho dễ biết
        if display_review == loaded_review and 'temp_review' not in st.session_state:
            st.success("Dưới đây là kết quả review ĐÃ ĐƯỢC LƯU trong Database:")
        elif 'temp_review' in st.session_state:
            st.warning("Đây là bản Review MỚI (Chưa lưu). Bấm nút Lưu bên dưới nếu ưng ý.")

        with st.chat_message("assistant", avatar="🔥"):
            st.markdown(display_review)
            
        st.divider()
        
        # Nút Lưu (Chỉ hiện khi có review MỚI chưa lưu)
        if 'temp_review' in st.session_state and st.session_state['temp_chap'] == chap_num:
            c1, c2 = st.columns([1, 3])
            with c1:
                if st.button("💾 LƯU KẾT QUẢ MỚI", type="primary", use_container_width=True):
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
                                    "embedding": vec
                                }).execute()
                        except: pass

                        # 2. UPSERT Chương (Cập nhật nếu đã có, Thêm mới nếu chưa)
                        # Dùng upsert để đè nội dung cũ bằng nội dung mới
                        
                        # Lưu ý: Muốn upsert hoạt động, trong DB bạn nên set cặp (story_id, chapter_number) là unique.
                        # Nhưng hiện tại cứ insert, nếu trùng id nó sẽ báo lỗi hoặc tạo dòng mới. 
                        # Để đơn giản cho bản này: Ta xóa cũ chèn mới hoặc cứ insert (nhưng sẽ bị double dòng nếu không xử lý kỹ).
                        # ==> CÁCH AN TOÀN NHẤT CHO BẢN NÀY:
                        
                        # Xóa dòng cũ của chương này đi (nếu có) rồi insert cái mới
                        supabase.table("chapters").delete().eq("story_id", story_id).eq("chapter_number", st.session_state['temp_chap']).execute()
                        
                        supabase.table("chapters").insert({
                            "story_id": story_id,
                            "chapter_number": st.session_state['temp_chap'],
                            "content": st.session_state['temp_content'],
                            "review_content": st.session_state['temp_review']
                        }).execute()
                        
                        st.success("✅ Đã cập nhật dữ liệu thành công!")
                        del st.session_state['temp_review'] # Xóa temp
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Lỗi lưu: {e}")

# === TAB 2: CHAT THÔNG MINH ===
with tab2:
    st.header("Chém gió với V (Có não)")
    
    # Load lịch sử chat
    history = supabase.table("chat_history").select("*").eq("story_id", story_id).order("created_at", desc=False).execute()
    
    for msg in history.data:
        role = "user" if msg['role'] == 'user' else "assistant"
        with st.chat_message(role):
            st.markdown(msg['content'])
            
    if prompt := st.chat_input("Hỏi gì đi (VD: Thằng Hùng chap trước bị sao?)"):
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.spinner("V đang nhớ lại..."):
            context = smart_search(prompt, story_id)
            
            full_prompt = f"CONTEXT TỪ DATABASE:\n{context}\n\nUSER HỎI:\n{prompt}"
            # Dùng gemini-3-pro-preview cho chat thông minh
            model_chat = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=V_CORE_INSTRUCTION)
            response = model_chat.generate_content(full_prompt)
            
            with st.chat_message("assistant"):
                st.markdown(response.text)
                with st.expander("🔍 V đã tìm thấy gì trong ký ức?"):
                    st.info(context)
            
            # Lưu chat
            supabase.table("chat_history").insert([
                {"story_id": story_id, "role": "user", "content": prompt},
                {"story_id": story_id, "role": "model", "content": response.text}
            ]).execute()

# === TAB 3: QUẢN LÝ BIBLE ===
with tab3:
    st.subheader("📚 Dữ liệu cốt truyện (Bible)")
    st.caption("Đây là những gì V tự động ghi nhớ từ các chương truyện của bạn.")
    
    data = supabase.table("story_bible").select("entity_name, description, created_at").eq("story_id", story_id).order("created_at", desc=True).execute()
    
    if data.data:
        df = pd.DataFrame(data.data)
        st.dataframe(
            df, 
            column_config={
                "entity_name": "Tên thực thể",
                "description": "Mô tả / Thông tin",
                "created_at": "Ngày tạo"
            },
            use_container_width=True
        )
    else:
        st.info("Chưa có dữ liệu. Hãy viết và review chương đầu tiên để V bắt đầu học!")