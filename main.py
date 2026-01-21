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
SAFE_CONFIG = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
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
def generate_content_with_fallback(prompt, system_instruction, safety_settings=SAFE_CONFIG, stream=True):
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
        
        # 1. Tìm kiếm Vector
        response = supabase.rpc("match_bible", {
            "query_embedding": query_vec,
            "match_threshold": 0.35, # <--- Hạ thấp ngưỡng một chút để lấy được nhiều context rộng hơn (đừng khắt khe quá)
            "match_count": top_k # <--- QUAN TRỌNG: Truyền biến top_k vào đây, đừng để số cứng 20 nữa!
        }).execute()
        
        results = []
        if response.data:
            bible_ids = [item['id'] for item in response.data]
            if bible_ids:
                # 2. Query lại DB
                query = supabase.table("story_bible").select("*").in_("id", bible_ids).eq("story_id", story_id)
                
                # Logic chặn tương lai (Spoiler)
                if current_chap:
                    query = query.lt("source_chapter", current_chap)
                
                valid_data = query.execute()
                
                # Format kết quả
                for item in valid_data.data:
                    chap_info = f"(Chap {item.get('source_chapter', '?')})"
                    results.append(f"- {item['entity_name']} {chap_info}: {item['description']}")
                    
        # Trả về TOÀN BỘ kết quả tìm được (vì giờ mình tin tưởng khả năng đọc hiểu của Gemini)
        return "\n".join(results) if results else "Không tìm thấy dữ liệu QUÁ KHỨ liên quan."
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

# ... (Phần import giữ nguyên) ...

# === TAB 1: VIẾT & REVIEW (GIAO DIỆN MỚI: TÁCH NÚT LƯU) ===
with tab1:
    st.header(f"Soạn thảo: {selected_story_name}")
    
    # Chia layout: 65% Soạn thảo - 35% Công cụ & Review
    col_l, col_r = st.columns([65, 35])
    
    # --- CỘT TRÁI: SOẠN THẢO ---
    with col_l:
        c_chap_1, c_chap_2 = st.columns([1, 4])
        with c_chap_1:
             chap_num = st.number_input("Chương số:", value=1, min_value=1, step=1, format="%d")
        
        # Load dữ liệu cũ
        existing_data = supabase.table("chapters").select("*").eq("story_id", story_id).eq("chapter_number", chap_num).execute()
        loaded_content = ""
        loaded_review = ""
        
        if existing_data.data:
            record = existing_data.data[0]
            loaded_content = record['content']
            loaded_review = record['review_content']
            if 'temp_content' not in st.session_state: # Chỉ báo toast lần đầu load
                 st.toast(f"📂 Đã tải dữ liệu Chương {chap_num}", icon="✅")

        # Logic hiển thị nội dung (Ưu tiên bản đang sửa trong Session)
        display_content = st.session_state.get('temp_content', loaded_content) if st.session_state.get('temp_chap') == chap_num else loaded_content
        
        content = st.text_area(
            "Nội dung chương (Viết ở đây)", 
            height=600, 
            value=display_content, 
            placeholder="Paste chương truyện vào đây...",
            key=f"editor_{story_id}_{chap_num}"
        )
        
        # Cập nhật session state khi gõ (để không mất chữ khi bấm nút khác)
        st.session_state['temp_content'] = content
        st.session_state['temp_chap'] = chap_num

        # --- NÚT LƯU NỘI DUNG CHƯƠNG (NÚT 1) ---
        # Nằm ngay dưới ô soạn thảo cho tiện tay
        if st.button("💾 Lưu Nội Dung Chương (Chỉ Text)", use_container_width=True):
            if not content:
                st.warning("Có chữ nào đâu mà lưu cha!")
            else:
                try:
                    # Upsert (Chèn hoặc Cập nhật)
                    supabase.table("chapters").upsert({
                        "story_id": story_id,
                        "chapter_number": chap_num,
                        "content": content,
                        # Giữ nguyên review cũ nếu có, đừng ghi đè null vào
                        "review_content": loaded_review if loaded_review else None 
                    }, on_conflict="story_id, chapter_number").execute()
                    st.success(f"✅ Đã lưu nội dung Chương {chap_num}!")
                except Exception as e:
                    st.error(f"Lỗi lưu chương: {e}")

    # --- CỘT PHẢI: AI REVIEW & BIBLE ---
    with col_r:
        st.write("### 🤖 Trợ lý V")
        
        # 1. NÚT GỌI AI (TRIGGER)
        if st.button("🚀 Phân Tích & Trích Xuất (AI Run)", type="primary", use_container_width=True):
            if not content:
                st.warning("Chưa có nội dung để phân tích!")
            else:
                # Clear kết quả cũ
                if 'temp_review' in st.session_state: del st.session_state['temp_review']
                if 'temp_bible' in st.session_state: del st.session_state['temp_bible']

                # --- CHẠY REVIEW (STREAM) ---
                review_box = st.empty()
                full_review = ""
                
                with st.spinner("V đang đọc & soi lỗi..."):
                    # Lấy context
                    related_context = smart_search(content[:1000], story_id, current_chap=chap_num, top_k=30)
                    
                    final_prompt = f"""
                    THÔNG TIN QUÁ KHỨ (CONTEXT):
                    {related_context}
                    
                    NỘI DUNG CHƯƠNG {chap_num}:
                    {content}
                    """
                    
                    try:
                        # Gọi Review
                        forced_prompt = f"{REVIEW_PROMPT}\n\n---\n{final_prompt}"

                        stream_review = generate_content_with_fallback(
                            prompt=forced_prompt,
                            system_instruction=None, # Tắt cái này đi cho đỡ lỗi
                            stream=True
                        )
                        
                        for chunk in stream_review:
                            if chunk.text:
                                full_review += chunk.text
                                review_box.markdown(full_review + "▌")
                        
                        review_box.markdown(full_review)
                        st.session_state['temp_review'] = full_review
                        
                    except Exception as e:
                        st.error(f"Lỗi Review: {e}")

                # --- CHẠY BIBLE EXTRACT (NGẦM) ---
                with st.spinner("Đang trích xuất dữ liệu Bible..."):
                    try:
                        res_extract = generate_content_with_fallback(
                            prompt=content,
                            system_instruction=EXTRACTOR_PROMPT, # Dùng cái Prompt nâng cấp ở trên
                            stream=False
                        )
                        st.session_state['temp_bible'] = res_extract.text
                        st.toast("Đã trích xuất xong Bible!", icon="✨")
                    except Exception as e:
                        st.error(f"Lỗi Extract: {e}")

        st.divider()

        # 2. KHU VỰC HIỂN THỊ KẾT QUẢ & LƯU RIÊNG LẺ
        
        # A. HIỂN THỊ REVIEW
        review_to_show = st.session_state.get('temp_review', loaded_review)
        
        with st.expander("📝 Kết quả Review", expanded=True):
            if review_to_show:
                st.markdown(review_to_show)
                st.divider()
                # --- NÚT LƯU REVIEW (NÚT 2) ---
                if st.button("💾 Lưu bản Review này", key="btn_save_review", use_container_width=True):
                    try:
                         supabase.table("chapters").upsert({
                            "story_id": story_id,
                            "chapter_number": chap_num,
                            "content": content, # Vẫn phải gửi content để đảm bảo row tồn tại
                            "review_content": review_to_show
                        }, on_conflict="story_id, chapter_number").execute()
                         st.success("Đã lưu Review vào DB!")
                    except Exception as e:
                        st.error(f"Lỗi: {e}")
            else:
                st.info("Chưa có review nào.")

        # B. HIỂN THỊ & LƯU BIBLE (QUAN TRỌNG: CƠ CHẾ GỘP THÔNG MINH)
        bible_json = st.session_state.get('temp_bible', "[]")
        
        with st.expander("📚 Dữ liệu Bible trích xuất", expanded=False):
            if bible_json and bible_json != "[]":
                # Clean chuỗi JSON nếu có markdown ```json
                clean_json = bible_json.strip()
                if clean_json.startswith("```json"): clean_json = clean_json[7:-3]
                
                try:
                    data_points = json.loads(clean_json)
                    
                    # Hiện bảng Preview cho user check trước khi lưu
                    df_preview = pd.DataFrame(data_points)
                    if not df_preview.empty:
                        # Chọn cột hiển thị cho gọn
                        cols_show = ['entity_name', 'type', 'description'] if 'type' in df_preview.columns else ['entity_name', 'description']
                        st.dataframe(df_preview[cols_show], hide_index=True)
                    
                    # --- NÚT LƯU BIBLE (NÚT 3) ---
                    # Logic gộp: Tìm tên trùng -> Gộp mô tả
                    if st.button("💾 Cập nhật vào Story Bible", key="btn_save_bible", type="primary", use_container_width=True):
                        success_count = 0
                        with st.status("Đang đồng bộ dữ liệu...", expanded=True) as status:
                            for point in data_points:
                                name = point['entity_name']
                                new_desc = point['description']
                                p_type = point.get('type', 'General')
                                
                                # 1. Kiểm tra xem entity này đã có trong DB chưa (Check trùng tên)
                                # Dùng RPC hoặc Select thường
                                existing = supabase.table("story_bible").select("*").eq("story_id", story_id).eq("entity_name", name).execute()
                                
                                if existing.data:
                                    # --- TRƯỜNG HỢP TRÙNG: GỘP THÔNG TIN ---
                                    old_record = existing.data[0]
                                    old_desc = old_record['description']
                                    old_id = old_record['id']
                                    
                                    # Chỉ gộp nếu mô tả khác nhau đáng kể (đỡ spam)
                                    if new_desc not in old_desc:
                                        # Tạo mô tả gộp: "Mô tả cũ [Cập nhật Chap X]: Mô tả mới"
                                        merged_desc = f"{old_desc}\n\n[Cập nhật Chap {chap_num}]: {new_desc}"
                                        
                                        # Cập nhật lại Embedding cho mô tả mới
                                        new_vec = get_embedding(merged_desc)
                                        
                                        supabase.table("story_bible").update({
                                            "description": merged_desc,
                                            "embedding": new_vec,
                                            "source_chapter": chap_num # Cập nhật chap mới nhất
                                        }).eq("id", old_id).execute()
                                        st.write(f"🔄 Đã gộp thông tin mới cho: **{name}**")
                                        success_count += 1
                                else:
                                    # --- TRƯỜNG HỢP MỚI: TẠO MỚI ---
                                    vec = get_embedding(new_desc)
                                    supabase.table("story_bible").insert({
                                        "story_id": story_id,
                                        "entity_name": name,
                                        "description": new_desc, # Có thể lưu thêm cột 'type' vào DB nếu ông muốn mở rộng bảng
                                        "embedding": vec,
                                        "source_chapter": chap_num
                                    }).execute()
                                    st.write(f"✨ Đã thêm mới: **{name}**")
                                    success_count += 1
                            
                            status.update(label=f"✅ Hoàn tất! Đã xử lý {success_count} mục.", state="complete", expanded=False)
                            
                        # Xóa cache để tab quản lý tải lại data mới
                        if 'bible_data_cache' in st.session_state: del st.session_state['bible_data_cache']
                        
                except json.JSONDecodeError:
                    st.error("AI trả về JSON lỗi, không lưu được. Hãy thử lại.")
                    st.code(bible_json) # Hiện code lỗi cho ông debug
                except Exception as e:
                     st.error(f"Lỗi logic lưu Bible: {e}")
            else:
                st.info("Chưa có dữ liệu trích xuất.")

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

# === TAB 3: QUẢN LÝ BIBLE (PHIÊN BẢN BIÊN TẬP VIÊN) ===
with tab3:
    st.header("📚 Quản lý Dữ liệu Cốt truyện (CMS)")
    
    # Nút tải dữ liệu (Giữ nguyên logic cache để đỡ tốn API)
    col_load, col_stat = st.columns([1, 3])
    with col_load:
        if st.button("🔄 Tải / Refresh Dữ liệu"):
            data = supabase.table("story_bible").select("*").eq("story_id", story_id).order("source_chapter", desc=True).execute()
            st.session_state['bible_data_cache'] = data.data
            st.rerun()

    bible_list = st.session_state.get('bible_data_cache', [])

    if not bible_list:
        st.info("Dữ liệu trống hoặc chưa tải. Bấm nút '🔄 Tải...' để xem.")
    else:
        # Convert sang Pandas để dễ xử lý
        df = pd.DataFrame(bible_list)
        
        # Sắp xếp cột cho đẹp
        df = df[['source_chapter', 'entity_name', 'description', 'id', 'created_at']]
        
        # =========================================================
        # TÍNH NĂNG 1: AI DỌN DẸP & HỢP NHẤT (SMART MERGE)
        # =========================================================
        with st.expander("🧠 AI Hợp Nhất & Dọn Dẹp (Smart Merge)", expanded=False):
            st.write("AI sẽ tìm các mục **trùng tên**, gộp nội dung của chúng lại thành một bản hoàn chỉnh nhất và cập nhật vào chương mới nhất.")
            
            # 1. Tìm các mục trùng tên
            name_counts = df['entity_name'].value_counts()
            duplicates = name_counts[name_counts > 1].index.tolist()
            
            if not duplicates:
                st.success("✅ Dữ liệu rất sạch! Không có tên nào bị trùng.")
            else:
                st.warning(f"⚠️ Phát hiện {len(duplicates)} thực thể bị trùng lặp: {', '.join(duplicates)}")
                
                if st.button(f"🤖 Hợp nhất {len(duplicates)} thực thể này ngay", type="primary"):
                    progress_bar = st.progress(0)
                    log_box = st.empty()
                    
                    for idx, entity_name in enumerate(duplicates):
                        # Lấy tất cả các dòng của thực thể này
                        rows = df[df['entity_name'] == entity_name].sort_values(by='source_chapter')
                        
                        # Chuẩn bị dữ liệu gửi cho AI
                        context_to_merge = []
                        ids_to_delete = []
                        latest_chapter = 0
                        latest_id = None
                        
                        for _, row in rows.iterrows():
                            context_to_merge.append(f"- [Chap {row['source_chapter']}]: {row['description']}")
                            ids_to_delete.append(row['id'])
                            
                            # Tìm chương mới nhất để giữ lại ID đó (hoặc tạo mới)
                            if row['source_chapter'] >= latest_chapter:
                                latest_chapter = row['source_chapter']
                                latest_id = row['id']
                        
                        # ID giữ lại là cái mới nhất, các cái khác xóa
                        ids_to_delete.remove(latest_id)
                        
                        # Prompt gộp
                        merge_prompt = f"""
                        Hãy đóng vai Editor chuyên nghiệp. Dưới đây là các mảnh thông tin rời rạc về nhân vật/sự kiện "{entity_name}" qua các chương:
                        
                        {chr(10).join(context_to_merge)}
                        
                        YÊU CẦU:
                        Viết lại một đoạn mô tả TỔNG HỢP duy nhất (khoảng 100-150 từ).
                        - Kết hợp thông tin từ quá khứ và hiện tại.
                        - Giữ lại các chi tiết quan trọng (ngoại hình, năng lực, thay đổi tâm lý).
                        - Đánh dấu [MỚI] trước thông tin cập nhật gần nhất.
                        - Không dùng gạch đầu dòng, viết thành đoạn văn.
                        """
                        
                        try:
                            # Gọi AI Merge
                            log_box.info(f"Đang gộp: {entity_name}...")
                            merged_desc_res = generate_content_with_fallback(
                                prompt=merge_prompt,
                                system_instruction="Bạn là người tóm tắt cốt truyện.",
                                stream=False
                            )
                            new_desc = merged_desc_res.text.strip()
                            
                            # Tính lại Vector
                            new_vec = get_embedding(new_desc)
                            
                            # Update dòng mới nhất (giữ ID mới nhất)
                            supabase.table("story_bible").update({
                                "description": new_desc,
                                "embedding": new_vec,
                                "source_chapter": latest_chapter # Đảm bảo nó ở chương mới nhất
                            }).eq("id", latest_id).execute()
                            
                            # Xóa các dòng cũ thừa thãi
                            if ids_to_delete:
                                supabase.table("story_bible").delete().in_("id", ids_to_delete).execute()
                                
                        except Exception as e:
                            st.error(f"Lỗi khi gộp {entity_name}: {e}")
                            
                        # Update progress
                        progress_bar.progress((idx + 1) / len(duplicates))
                    
                    st.success("✅ Đã hợp nhất xong! Hãy bấm Refresh để xem kết quả.")
                    if st.button("🔄 Refresh ngay"):
                        st.rerun()

        st.divider()

        # =========================================================
        # TÍNH NĂNG 2: BẢNG CHỈNH SỬA TRỰC TIẾP (EXCEL STYLE)
        # =========================================================
        st.subheader("📝 Chỉnh sửa Dữ liệu (Click vào ô để sửa)")
        st.caption("⚠️ Lưu ý: Sửa 'Mô tả' sẽ tốn thời gian hơn chút vì hệ thống phải tính lại Vector.")

        # Cấu hình bảng Editor
        edited_df = st.data_editor(
            df,
            column_config={
                "source_chapter": st.column_config.NumberColumn("Chap", min_value=1, width="small"),
                "entity_name": st.column_config.TextColumn("Tên Thực Thể", width="medium"),
                "description": st.column_config.TextColumn("Mô tả chi tiết (Double click để sửa)", width="large"),
                "id": None, # Ẩn cột ID không cho sửa
                "created_at": None # Ẩn ngày tạo
            },
            use_container_width=True,
            num_rows="dynamic", # Cho phép thêm/xóa dòng trực tiếp
            key="bible_editor"
        )

        # NÚT LƯU THAY ĐỔI
        if st.button("💾 Lưu các thay đổi", type="primary"):
            with st.spinner("Đang đồng bộ dữ liệu..."):
                try:
                    # Lấy thông tin thay đổi từ Session State của data_editor
                    changes = st.session_state["bible_editor"]
                    
                    # 1. XỬ LÝ DÒNG ĐÃ XÓA (DELETED ROWS)
                    # changes['deleted_rows'] trả về list index của dòng bị xóa
                    if changes["deleted_rows"]:
                        # Phải map index bị xóa với ID trong dataframe gốc (df)
                        ids_to_del = [df.iloc[i]['id'] for i in changes["deleted_rows"]]
                        if ids_to_del:
                            supabase.table("story_bible").delete().in_("id", ids_to_del).execute()
                            st.toast(f"🗑️ Đã xóa {len(ids_to_del)} mục.", icon="🗑️")

                    # 2. XỬ LÝ DÒNG ĐÃ SỬA (EDITED ROWS)
                    # changes['edited_rows'] là dict {row_index: {col_name: new_value}}
                    for idx, edits in changes["edited_rows"].items():
                        row_id = df.iloc[idx]['id']
                        original_row = df.iloc[idx]
                        
                        update_data = {}
                        
                        # Check xem có sửa Tên hay Chap không
                        if "entity_name" in edits: update_data["entity_name"] = edits["entity_name"]
                        if "source_chapter" in edits: update_data["source_chapter"] = edits["source_chapter"]
                        
                        # Check xem có sửa MÔ TẢ không (Quan trọng: Phải tính lại Vector)
                        if "description" in edits:
                            new_desc = edits["description"]
                            update_data["description"] = new_desc
                            # Gọi API Embedding
                            update_data["embedding"] = get_embedding(new_desc)
                        
                        if update_data:
                            supabase.table("story_bible").update(update_data).eq("id", row_id).execute()
                    
                    # 3. XỬ LÝ DÒNG MỚI THÊM (ADDED ROWS)
                    # changes['added_rows'] là list các dict
                    for new_row in changes["added_rows"]:
                        # Chỉ lưu nếu có điền tên và mô tả (tránh lưu dòng trống)
                        if "entity_name" in new_row and "description" in new_row and new_row["entity_name"] and new_row["description"]:
                            vec = get_embedding(new_row["description"])
                            supabase.table("story_bible").insert({
                                "story_id": story_id,
                                "entity_name": new_row["entity_name"],
                                "description": new_row["description"],
                                "source_chapter": new_row.get("source_chapter", 1), # Mặc định chap 1 nếu ko điền
                                "embedding": vec
                            }).execute()

                    st.success("✅ Đã cập nhật database thành công!")
                    
                    # Xóa cache để load lại bảng mới
                    del st.session_state['bible_data_cache']
                    time.sleep(1)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Lỗi khi lưu: {e}")



