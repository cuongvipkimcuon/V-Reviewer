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

# --- 2. CÁC HÀM "NÃO BỘ" THÔNG MINH (ĐÃ NÂNG CẤP) ---

def get_embedding(text):
    return genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )['embedding']

def smart_search(query_text, story_id, top_k=7): # Tăng top_k lên 7 để AI có nhiều context hơn
    try:
        query_vec = get_embedding(query_text)
        # Gọi hàm RPC match_bible (Đã update SQL để lấy source_chapter)
        response = supabase.rpc("match_bible", {
            "query_embedding": query_vec,
            "match_threshold": 0.45, # Giảm ngưỡng nhẹ để AI bắt được nhiều thông tin liên quan hơn
            "match_count": top_k
        }).execute()
        
        results = []
        if response.data:
            bible_ids = [item['id'] for item in response.data]
            if bible_ids:
                # Query lại bảng để filter story_id (an toàn)
                valid_data = supabase.table("story_bible").select("*").in_("id", bible_ids).eq("story_id", story_id).execute()
                
                # Format kết quả: Thêm (Chap X) vào để AI biết dòng thời gian
                for item in valid_data.data:
                    chap_info = f"(Chap {item.get('source_chapter', '?')})"
                    results.append(f"- {item['entity_name']} {chap_info}: {item['description']}")
                    
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

# Chọn Truyện (ĐÃ SỬA: CHỈ HIỆN TRUYỆN CỦA USER ĐÓ)
stories = supabase.table("stories").select("*").eq("user_id", st.session_state.user.id).execute()
story_map = {s['title']: s['id'] for s in stories.data}
selected_story_name = st.selectbox("📖 Chọn bộ truyện", ["-- Tạo mới --"] + list(story_map.keys()))

if selected_story_name == "-- Tạo mới --":
    st.title("✨ Khởi tạo thế giới mới")
    st.info("👈 Nhìn sang cột bên trái để chọn truyện hoặc tạo mới tại đây.")
    new_title = st.text_input("Tên truyện mới")
    if st.button("Tạo Truyện Ngay"):
        if new_title:
            # LƯU USER_ID KHI TẠO
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

# === TAB 1: VIẾT & REVIEW (CÓ TÍNH NĂNG LOAD DỮ LIỆU CŨ) ===
with tab1:
    st.header(f"Soạn thảo: {selected_story_name}")
    
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        # 1. Chọn số chương
        chap_num = st.number_input("Chương số", value=1, min_value=1)
        
        # --- LOGIC: TỰ ĐỘNG TẢI DỮ LIỆU CŨ TỪ DB ---
        existing_data = supabase.table("chapters").select("*").eq("story_id", story_id).eq("chapter_number", chap_num).execute()
        
        loaded_content = ""
        loaded_review = ""
        
        if existing_data.data:
            record = existing_data.data[0]
            loaded_content = record['content']
            loaded_review = record['review_content']
            st.toast(f"📂 Đã tải lại nội dung cũ của Chương {chap_num}!", icon="✅")

        # 2. Ô nhập liệu
        display_content = st.session_state.get('temp_content', loaded_content) if st.session_state.get('temp_chap') == chap_num else loaded_content
        
        content = st.text_area(
            "Nội dung chương", 
            height=450, 
            value=display_content, 
            placeholder="Chương này chưa có nội dung...",
            key=f"editor_{story_id}_{chap_num}"
        )
        
    with col_r:
        st.write("### 🎮 Điều khiển")
        
        if loaded_review and 'temp_review' not in st.session_state:
            st.info("✅ Chương này đã được Review và Lưu trước đó.")
        
        if st.button("🚀 Gửi V Thẩm Định", type="primary", use_container_width=True):
            if not content:
                st.warning("Viết gì đi đã cha nội!")
            else:
                with st.spinner("V đang đọc, lục lại trí nhớ và soi mói..."):
                    related_context = smart_search(content[:1000], story_id, current_chap=chap_num)
                    
                    final_prompt = f"""
                    THÔNG TIN BỐI CẢNH TÌM ĐƯỢC TỪ QUÁ KHỨ:
                    {related_context}
                    
                    NỘI DUNG CHƯƠNG {chap_num} CẦN REVIEW:
                    {content}
                    """
                    
                    # --- 1. CẤU HÌNH "THÁO XÍCH" AN TOÀN ---
                    # Bắt buộc phải có cái này, không là viết truyện tình cảm tí là nó chặn
                    safe_config = [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                    
                    # --- 2. GỌI REVIEW (CÓ BẮT LỖI) ---
                    try:
                        # Thêm safety_settings vào đây
                        review_res = model_review.generate_content(final_prompt, safety_settings=safe_config)
                        
                        # Kiểm tra xem nó có trả lời không trước khi lấy .text
                        if review_res.text:
                            st.session_state['temp_review'] = review_res.text
                    except ValueError:
                        # Nếu bị chặn, hiện thông báo khéo léo thay vì sập web
                        st.error("🚫 V từ chối review chương này!")
                        st.warning("Lý do: Bộ lọc an toàn của Google quá nhạy cảm với từ ngữ trong bài (Safety Filter).")
                        # Mẹo: In ra lý do chặn để ông biết đường sửa
                        if review_res.prompt_feedback:
                            st.caption(f"Chi tiết chặn: {review_res.prompt_feedback}")
                        st.stop()
                    except Exception as e:
                        st.error(f"Lỗi lạ: {e}")
                        st.stop()

                    # --- 3. GỌI BIBLE EXTRACT (Dùng Flash cho rẻ & nhanh) ---
                    try:
                        # Cũng phải tháo xích cho thằng Extract luôn
                        model_extract = genai.GenerativeModel('gemini-3-flash-preview', system_instruction=EXTRACTOR_PROMPT)
                        extract_res = model_extract.generate_content(content, safety_settings=safe_config)
                        st.session_state['temp_bible'] = extract_res.text
                    except:
                        st.session_state['temp_bible'] = "[]" # Nếu lỗi thì trả về rỗng để không sập

                    st.session_state['temp_content'] = content
                    st.session_state['temp_chap'] = chap_num
                    st.rerun()

    # --- KHU VỰC HIỂN THỊ KẾT QUẢ ---
    st.divider()
    
    temp_r = st.session_state.get('temp_review')
    if st.session_state.get('temp_chap') == chap_num and temp_r:
        display_review = temp_r
    else:
        display_review = loaded_review
    
    if display_review:
        st.subheader("🧐 Kết quả thẩm định")
        
        if display_review == loaded_review and 'temp_review' not in st.session_state:
            st.success("Dưới đây là kết quả review ĐÃ ĐƯỢC LƯU trong Database:")
        elif 'temp_review' in st.session_state:
            st.warning("Đây là bản Review MỚI (Chưa lưu). Bấm nút Lưu bên dưới nếu ưng ý.")

        with st.chat_message("assistant", avatar="🔥"):
            st.markdown(display_review)
            
        st.divider()
        
        if 'temp_review' in st.session_state and st.session_state['temp_chap'] == chap_num:
            c1, c2 = st.columns([1, 3])
            with c1:
                if st.button("💾 LƯU KẾT QUẢ MỚI", type="primary", use_container_width=True):
                    try:
                        # 1. Lưu Bible (CÓ THÊM SỐ CHƯƠNG - source_chapter)
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
                                    "source_chapter": st.session_state['temp_chap'] # <--- LƯU CHAP
                                }).execute()
                        except: pass

                        # 2. Lưu Chương (Xóa cũ - Chèn mới)
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

# === TAB 2: CHAT THÔNG MINH ===
with tab2:
    st.header("Chém gió với V (Có não)")
    
    history = supabase.table("chat_history").select("*").eq("story_id", story_id).order("created_at", desc=False).execute()
    
    for msg in history.data:
        role = "user" if msg['role'] == 'user' else "assistant"
        with st.chat_message(role):
            st.markdown(msg['content'])
            
    if prompt := st.chat_input("Hỏi gì đi (VD: Thằng Hùng chap trước bị sao?)"):
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.spinner("V đang nhớ lại..."):
            context = smart_search(prompt, story_id, top_k=7) # Tăng context
            full_prompt = f"CONTEXT TỪ DATABASE (Các chap liên quan):\n{context}\n\nUSER HỎI:\n{prompt}"
            
            # Bảo vệ chống lỗi Safety
            try:
                model_chat = genai.GenerativeModel('gemini-3-pro-preview', system_instruction=V_CORE_INSTRUCTION)
                response = model_chat.generate_content(full_prompt)
                
                if response.text:
                    with st.chat_message("assistant"):
                        st.markdown(response.text)
                        with st.expander("🔍 V đã tìm thấy gì trong ký ức?"):
                            st.info(context)
                    
                    supabase.table("chat_history").insert([
                        {"story_id": story_id, "role": "user", "content": prompt},
                        {"story_id": story_id, "role": "model", "content": response.text}
                    ]).execute()
            except Exception as e:
                 with st.chat_message("assistant"):
                    st.error("🚫 V từ chối trả lời!")
                    st.warning("Có thể câu hỏi vi phạm tiêu chuẩn an toàn hoặc Model đang quá tải.")

# === TAB 3: QUẢN LÝ BIBLE (NÂNG CẤP CMS: LỌC & XÓA) ===
with tab3:
    st.header("📚 Quản lý Dữ liệu Cốt truyện")
    st.caption("Nơi dọn dẹp ký ức cho V đỡ bị 'lú'.")
    
    data = supabase.table("story_bible").select("*").eq("story_id", story_id).order("created_at", desc=True).execute()
    
    if not data.data:
        st.info("Chưa có dữ liệu. Hãy Review chương truyện để AI tự trích xuất.")
    else:
        df = pd.DataFrame(data.data)
        
       # --- CÔNG CỤ 1: DỌN DẸP TRÙNG LẶP (LOGIC MỚI: AN TOÀN TUYỆT ĐỐI) ---
        with st.expander("🧹 Công cụ dọn trùng lặp (Auto Cleaner)", expanded=False):
            st.write("Chỉ xóa những dòng GIỐNG Y HỆT nhau (Cùng tên & Cùng mô tả). Giữ lại các thông tin khác nhau.")
            if st.button("Chạy dọn dẹp ngay", type="primary"):
                with st.spinner("Đang soi từng chữ..."):
                    seen_content = set() # Tập hợp chứa các nội dung đã gặp
                    ids_to_delete = []
                    
                    for item in data.data:
                        # Tạo một cái "dấu vân tay" cho dòng dữ liệu
                        # Kết hợp Tên + Mô tả (viết thường, bỏ khoảng trắng thừa)
                        name = item['entity_name'].lower().strip()
                        desc = item['description'].lower().strip()
                        
                        # Dấu vân tay duy nhất
                        unique_key = f"{name}|||{desc}"
                        
                        if unique_key in seen_content:
                            # Nếu đã từng thấy nội dung y hệt thế này rồi -> XÓA thằng cũ hơn (do list đã sort DESC)
                            ids_to_delete.append(item['id'])
                        else:
                            # Nếu chưa thấy -> Lưu lại vào bộ nhớ
                            seen_content.add(unique_key)
                    
                    if ids_to_delete:
                        supabase.table("story_bible").delete().in_("id", ids_to_delete).execute()
                        st.success(f"Đã dọn sạch {len(ids_to_delete)} dòng copy y chang nhau!")
                        st.rerun()
                    else:
                        st.info("Dữ liệu sạch bong! Không có dòng nào trùng lặp hoàn toàn.")

        st.divider()

        # --- CÔNG CỤ 2: XÓA THỦ CÔNG ---
        st.subheader("Danh sách chi tiết")
        
        # Tạo list hiển thị có cả số chương
        options = {f"[Chap {row.get('source_chapter', '?')}] {row['entity_name']} | {row['description'][:50]}...": row['id'] for index, row in df.iterrows()}
        
        selected_items = st.multiselect(
            "🗑️ Chọn dòng muốn xóa (Sai lệch, lỗi thời...):",
            options=options.keys()
        )
        
        if selected_items:
            if st.button(f"Xác nhận xóa {len(selected_items)} dòng", type="primary"):
                ids_to_remove = [options[item] for item in selected_items]
                supabase.table("story_bible").delete().in_("id", ids_to_remove).execute()
                st.success("Đã xóa xong!")
                st.rerun()

        # Hiển thị bảng data (CÓ CỘT CHAP)
        if 'source_chapter' in df.columns:
            display_cols = ['source_chapter', 'entity_name', 'description', 'created_at']
        else:
            display_cols = ['entity_name', 'description', 'created_at']

        st.dataframe(
            df[display_cols],
            column_config={
                "source_chapter": "Chap",
                "entity_name": "Thực thể",
                "description": "Mô tả",
                "created_at": "Ngày tạo"
            },
            use_container_width=True,
            height=600
        )


