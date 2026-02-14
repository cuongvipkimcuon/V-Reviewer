# Changelog: Intent nâng cấp & Schema V7

## 0. Phân biệt query_Sql vs manage_timeline (cập nhật)

- **query_Sql**: Dữ liệu dạng **đối tượng** (entity, thuộc tính, chi tiết) — trả lời từ story_bible, chapters. Ví dụ: "nhân vật A là ai", "địa điểm B ở đâu". Có fallback search_bible. **Không** dùng timeline_events.
- **manage_timeline**: Chỉ **sự kiện** và **thứ tự thời gian** — truy vấn bảng timeline_events. Ví dụ: "thứ tự sự kiện", "flashback", "mốc thời gian", "kiểm tra nhất quán thời gian". Không dùng cho hỏi đối tượng/nhân vật/thuộc tính.

## 1. Sửa nhập nhằng search_chunks / read_full_content (hỏi "chương 1")

### Vấn đề
User hỏi "chương 1" thì Router trả về `search_chunks`, nhưng nội dung chunk được vector hóa thường không chứa số chương → AI báo "không có".

### Thay đổi
- **Router (ai_engine.py)**  
  - Bổ sung quy tắc: khi user nói rõ **"chương 1", "chương 5", "chapter 3"** (một hoặc khoảng chương cụ thể) → dùng **read_full_content** và đặt `chapter_range` tương ứng (vd `[1,1]` cho "chương 1"), **không** dùng search_chunks.  
  - Mô tả intent `read_full_content` có thêm: "hoặc hỏi theo SỐ CHƯƠNG cụ thể".  
  - Mô tả intent `search_chunks`: "KHÔNG nhắc số chương cụ thể".

- **Fallback trong build_context (search_chunks)**  
  - Thêm hàm `parse_chapter_range_from_query(query)` để nhận diện "chương N", "chương A đến B", "chapter N" trong câu.  
  - Trong nhánh `search_chunks`: nếu không có chunk nào **hoặc** câu hỏi có số chương cụ thể → gọi `load_chapters_by_range(project_id, start, end)` và thêm vào context với nguồn "📄 Chapter fallback".  
  - Nhờ đó dù Router vẫn trả về search_chunks, khi có "chương 1" trong câu vẫn có nội dung chương để trả lời.

---

## 2. Schema V7 – Bảng timeline_events

**File:** `schema_v7_migration.sql` (chạy sau schema_v6.6)

- Bảng **timeline_events**:  
  `id`, `story_id`, `arc_id`, `chapter_id`, `event_order`, `title`, `description`, `raw_date`, `event_type` ('event'|'flashback'|'milestone'|'timeskip'|'other'), `meta_json`, `created_at`, `updated_at`.  
- Index: `story_id`, `arc_id`, `(story_id, event_order)`, `chapter_id`.

Dùng cho intent **manage_timeline** (truy vấn thứ tự sự kiện, mốc thời gian, flashback, kiểm tra nhất quán thời gian).

---

## 3. Các intent mới (Router + xử lý)

Router (SmartAIRouter.ai_router_pro_v2) và build_context đã mở rộng cho 5 intent mới.

### 3.1. manage_timeline
- **Kích hoạt:** User hỏi thứ tự sự kiện, mốc thời gian, flashback, kiểm tra tính nhất quán thời gian.
- **Xử lý:** Gọi `get_timeline_events(project_id)` (SELECT bảng `timeline_events`), format theo `event_order`, inject vào context với nguồn "📅 Timeline Events". Nếu chưa có dữ liệu → thông báo và gợi ý dùng Bible/chương.

### 3.2. web_search
- **Kích hoạt:** User cần thông tin thời gian thực hoặc ngoài Bible (tỷ giá, thông số vũ khí thực tế, tin tức...).
- **Xử lý:** Gọi `utils.web_search.web_search(rewritten_query)` (Tavily trước, không có thì Google Custom Search). Kết quả format text inject vào context, nguồn "🌐 Web Search".  
- **Cấu hình:** Trong secrets: `tavily.API_KEY` hoặc `TAVILY_API_KEY`; hoặc `google_search.API_KEY` + `google_search.SEARCH_ENGINE_ID` (hoặc `GOOGLE_SEARCH_API_KEY` / `GOOGLE_CX`).

### 3.3. ask_user_clarification
- **Kích hoạt:** Câu hỏi quá mơ hồ, Router trả về intent này và điền `clarification_question`.
- **Xử lý:**  
  - **Chat (views/chat.py):** Không gọi LLM trả lời. Hiển thị message assistant với nội dung "[Cần làm rõ]" và `clarification_question` (popup/block), kèm ô gợi ý user gõ lại; vẫn lưu lịch sử (user + model = clarification).  
  - **build_context:** Nếu vẫn gọi build_context (vd từ chỗ khác), inject instruction "[CẦN LÀM RÕ]" + `clarification_question` để model có thể trả lời ngắn yêu cầu làm rõ.

### 3.4. update_data
- **Kích hoạt:** User ra lệnh ghi nhớ quy tắc mới, cập nhật entity vào Bible, hoặc sửa nội dung file/chương. Router điền `update_summary`.
- **Xử lý:**  
  - **build_context:** Inject `update_summary` + hướng dẫn "Thao tác chỉ thực hiện sau khi user xác nhận".  
  - **Chat:** Sau khi AI trả lời, nếu `intent == update_data` và user có quyền ghi → set `st.session_state["pending_update_confirm"]` (project_id, prompt, response, update_summary).  
  - **Bước xác nhận:** Expander "✏️ Xác nhận thực hiện cập nhật?" với tóm tắt + nội dung sẽ ghi; nút "✅ Xác nhận thực hiện" → ghi vào `story_bible` (entity [RULE] + description từ response/update_summary), rồi xóa `pending_update_confirm`; nút "❌ Hủy" chỉ xóa pending.

### 3.5. query_Sql
- **Kích hoạt:** User hỏi kỹ về một đối tượng/chi tiết có thể trả lời bằng dữ liệu từ các bảng (story_bible, chapters, timeline_events...).
- **Xử lý:**  
  - Gọi HybridSearch (rewritten_query) + `get_timeline_events(project_id)`; format Bible + timeline vào context, nguồn "🔍 Query SQL".  
  - **Fallback:** Nếu không có dữ liệu nào → gán `intent = "search_bible"` để block `search_bible` / `mixed_context` chạy tiếp (Bible + relations như bình thường).

---

## 4. Router JSON mở rộng

- **Intent:** Thêm 5 giá trị: `manage_timeline`, `web_search`, `ask_user_clarification`, `update_data`, `query_Sql`.  
- **Trường mới:**  
  - `clarification_question`: dùng khi intent = ask_user_clarification.  
  - `update_summary`: dùng khi intent = update_data.  
- **setdefault:** Router result và fallback khi parse lỗi đều set `clarification_question`, `update_summary` (chuỗi rỗng nếu không có).

---

## 5. File thay đổi / thêm

| File | Nội dung |
|------|----------|
| `ai_engine.py` | `parse_chapter_range_from_query`; cập nhật router prompt và output; fallback chapter trong search_chunks; `get_timeline_events`; build_context cho manage_timeline, web_search, ask_user_clarification, update_data, query_Sql. |
| `views/chat.py` | Nhánh ask_user_clarification (không gọi LLM, hiện clarification + lưu history); set pending_update_confirm khi update_data; expander xác nhận cập nhật (Xác nhận/Hủy) và ghi Bible. |
| `utils/web_search.py` | **Mới.** Tavily Search API + Google Custom Search; hàm `web_search(query)` trả về text để inject context. |
| `schema_v7_migration.sql` | **Mới.** Tạo bảng `timeline_events`. |
| `CHANGELOG_INTENTS_V7.md` | **Mới.** Tài liệu tóm tắt thay đổi. |

---

## 6. Tavily API key (web_search)

- **Local (.streamlit/secrets.toml):** Thêm section `[tavily]` và `API_KEY = "your-key"`.  
- **Streamlit Cloud:** Trong app settings → Secrets, thêm key `TAVILY_API_KEY` (hoặc cấu hình `tavily` → `API_KEY` nếu dùng TOML).  
- Code đọc: ưu tiên `st.secrets.tavily.API_KEY`, sau đó `st.secrets.TAVILY_API_KEY`.

## 7. Timeline UI

- **Data Analyze → tab "📅 Timeline":** Chọn chương → "AI trích xuất timeline từ chương này" → AI trả về danh sách sự kiện (event_order, title, description, raw_date, event_type) → chỉnh sửa (tùy chọn) → "Lưu vào Timeline" để ghi vào bảng `timeline_events`. Cần đã chạy schema_v7.  
- **Knowledge → tab "📅 Timeline":** Xem danh sách sự kiện, **thêm mới** (form), **sửa** (nút Sửa → form chỉnh sửa), **xóa** (nút Xóa → xác nhận). Chỉ thành viên có quyền ghi mới thêm/sửa/xóa.

## 8. Hướng dẫn vận hành

1. **Supabase:** Chạy `schema_v7_migration.sql` trên project (sau khi đã chạy v6.6).  
2. **Timeline:** Dữ liệu có thể thêm từ **Data Analyze → Timeline** (AI trích xuất từ chương) hoặc **Knowledge → Timeline** (thêm/sửa/xóa thủ công).  
3. **Web search:** Cấu hình Tavily (hoặc Google) theo mục 6.  
4. **Clarification / Update:** Không cần cấu hình thêm.

---

## 9. Context cho Router / Planner (không nhồi chat vào LLM trả lời)

- **Slider "Số tin nhắn cũ đưa vào Router & V7 Planner":** 0–50, bước 1. Chỉ điều khiển số tin gần nhất đưa vào **Router** và **V7 Planner** để chọn intent và lên kế hoạch (rewritten_query, tham chiếu "làm cái đó", v.v.).
- **LLM trả lời:** Không nhồi lịch sử chat vào context; trả lời chỉ dựa trên context đã thu thập (Bible, chương, timeline, search…) từ build_context / plan.
- **Đã bỏ:** Toggle "Không dùng lịch sử chat" (router_ignore_history).
- **ai_engine.py:** `cap_chat_history_to_tokens()` giới hạn lịch sử chat gửi Router/Planner tối đa 6000 token (giữ tin gần nhất) để tránh vượt context window.

### Prompt chọn intent: tham chiếu nội dung chat (crystallize)

- **Router:** Bổ sung mô tả intent `search_bible`: "hoặc user tham chiếu nội dung đã nói trong chat (crystallize)". Từ khóa: "như tôi đã nói về...", "chủ đề trước đó", "đoạn chat trước về X". Thêm **Quy tắc 5**: user nói đã bàn/đã nói về chủ đề X -> chọn `search_bible`, `rewritten_query` = chủ đề/từ khóa (Bible gồm entry [CHAT] crystallize).
- **V7 Planner:** Thêm quy tắc tương tự: tham chiếu nội dung chat -> intent `search_bible`, query_refined = chủ đề cần tìm.

---

## 10. Verifier theo intent & mixed_context đủ nguồn

### Verifier (ai_verifier.py)
- **Cấu trúc theo intent:**  
  - **Không verify:** ask_user_clarification, update_data, chat_casual.  
  - **Verify số:** numerical_calculation (so với Python executor, tolerance 1%).  
  - **Verify timeline:** manage_timeline (độ dài, context có timeline).  
  - **Verify grounding:** read_full_content, search_chunks, search_bible, mixed_context, query_Sql — LLM-as-judge: response chỉ được dựa trên CONTEXT.  
  - **web_search:** bỏ qua verify.
- **Grounding:** Gọi LLM (ROUTER_MODEL) với prompt kiểm tra "RESPONSE có CHỈ dựa trên CONTEXT không"; VIOLATION thì fail và retry correction.
- **verification_required:** Bật khi plan chứa numerical_calculation, manage_timeline hoặc bất kỳ intent grounding (kể cả single-step từ _single_intent_to_plan và get_plan_v7).

### mixed_context (build_context)
- **Nguồn:** Bible (entity + reverse lookup chương) + target_files (related files) + **timeline** (get_timeline_events, limit 30) + **chunks** (search_chunks_vector + reverse lookup, top_k=5, token_limit 5000).  
- mixed_context cho phép lấy đủ Bible, chunk, timeline (và file) để trả lời.

---

## 11. V7 Dynamic Re-planning

- **Mục tiêu:** Sau mỗi bước thực thi, đánh giá "có cần đổi kế hoạch không?". Nếu không tìm thấy dữ liệu (vd file A), có thể thay bằng bước khác (vd tìm file B) thay vì chạy tiếp plan cũ.
- **evaluate_step_outcome (ai_engine):** Rule-based: theo intent và (ctx_text, sources) xác định bước vừa chạy có "thất bại" không (read_full_content không có TARGET CONTENT, search_chunks không có chunk/fallback, search_bible/mixed_context/query_Sql không có dữ liệu, manage_timeline không có timeline). Trả về (should_replan, reason).
- **replan_after_step (ai_engine):** Gọi LLM (ROUTER_MODEL) với prompt: user_prompt + context đã tích lũy + bước vừa làm + outcome_reason + plan còn lại. LLM trả về action: **continue** (chạy tiếp), **replace** (thay plan còn lại bằng new_plan), **abort** (dừng, trả lời theo context hiện có). Trả về (action, reason, new_plan).
- **execute_plan (core/executor_v7.py):** Đổi từ `for step in plan` sang `while remaining_steps`: mỗi lần chạy 1 bước → evaluate_step_outcome → nếu should_replan và còn bước sau và replan_count < max_replan_rounds thì gọi replan_after_step → cập nhật remaining_steps (replace/abort/continue). Trả về thêm **replan_events** (danh sách { step_id, reason, action, new_plan_summary }).
- **Tham số:** max_steps_per_turn=10, max_replan_rounds=2.
- **Chat UI:** Hiển thị caption "🔄 Re-plan: ..." khi có replan_events; trong V7 Details hiển thị replan_events và số steps thực thi (len(step_results)). Verifier dùng plan_for_verifier = [{"intent": r["intent"]} for r in step_results] để verify theo đúng các bước đã chạy (kể cả bước thay thế).
