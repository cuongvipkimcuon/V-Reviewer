# ai/router.py - is_multi_*, get_v7_reminder_message, SmartAIRouter
import json
import re
from typing import Dict

from config import Config

from ai.context_helpers import get_mandatory_rules
from ai.service import AIService, _get_default_tool_model
from ai.utils import (
    cap_chat_history_to_tokens,
    get_bible_index,
    get_chapter_list_for_router,
)


def is_multi_step_update_data_request(query: str) -> bool:
    """
    Bộ lọc nhỏ: phát hiện câu hỏi có yêu cầu 2+ thao tác update_data (extract/update/delete bible, relation, timeline, chunking).
    Dùng cho V6: nếu True thì không thực hiện mà cảnh báo user bật V7.
    """
    if not query or not isinstance(query, str):
        return False
    q = query.strip().lower()
    if len(q) < 3:
        return False
    multi_phrases = [
        "tất cả", "toàn bộ", "cả 4", "cả bốn", "full", "mọi bước", "tất cả các bước",
        "data analyze", "phân tích đầy đủ", "4 bước", "bốn bước", "bible và relation",
        "relation và timeline", "timeline và chunk", "bible, relation", "relation, timeline",
        "extract bible và", "trích xuất bible và", "chạy đủ", "làm đủ", "thực hiện đủ",
    ]
    for phrase in multi_phrases:
        if phrase in q:
            return True
    targets = ["bible", "relation", "timeline", "chunking"]
    if sum(1 for t in targets if t in q) >= 2:
        return True
    return False


def is_multi_intent_request(query: str) -> bool:
    """
    Bộ lọc: phát hiện câu hỏi có vẻ cần nhiều intent (nhiều bước xử lý khác nhau) để trả lời đủ.
    Dùng cho V6: hiển thị lời nhắc bật V7 khi True.
    """
    if not query or not isinstance(query, str):
        return False
    q = query.strip().lower()
    if len(q) < 5:
        return False
    multi_intent_phrases = [
        " rồi ", " sau đó ", " xong thì ", " xong rồi ", " rồi so sánh", " rồi tìm ",
        " rồi kiểm tra", " rồi trích ", " và so sánh", " và tìm ", " và kiểm tra", " và trích ",
        " tóm tắt rồi", " tóm tắt và ", " trích xuất rồi", " trích xuất và ", " extract rồi",
        " extract và ", " kiểm tra .* và ", " vừa .* vừa ", " đồng thời ",
        " kết hợp với timeline", " kết hợp với bible", " so sánh với timeline",
        " đối chiếu với ", " rồi đối chiếu", " sau khi .* thì ",
    ]
    for phrase in multi_intent_phrases:
        if ".*" in phrase:
            if re.search(phrase.replace(".*", r".{2,40}"), q):
                return True
        elif phrase in q:
            return True
    return False


def get_v7_reminder_message() -> str:
    """Lời nhắc thống nhất khi V6 phát hiện câu hỏi cần nhiều bước / nhiều intent."""
    return (
        "**Yêu cầu của bạn có vẻ gồm nhiều thao tác hoặc nhiều bước xử lý** (nhiều intent). "
        "Chế độ V6 chỉ xử lý **một** intent mỗi lần. "
        "Vui lòng **bật V7 Planner** (trong cài đặt Chat) để thực hiện nhiều bước trong một lần."
    )


class SmartAIRouter:
    """Bộ định tuyến AI thông minh với hybrid search và bible index"""

    @staticmethod
    def ai_router_pro_v2(user_prompt: str, chat_history_text: str, project_id: str = None) -> Dict:
        """Router V2: Phân tích Intent và Target Files, có inject bible_index để nhận diện ý định."""
        chat_history_text = cap_chat_history_to_tokens(chat_history_text or "")
        rules_context = ""
        bible_index = ""
        prefix_setup_str = ""
        if project_id:
            rules_context = get_mandatory_rules(project_id)
            bible_index = get_bible_index(project_id, max_tokens=2000)
        try:
            prefix_setup = Config.get_prefix_setup()
            if prefix_setup:
                prefix_setup_str = "\n".join(
                    f"- [{p.get('prefix_key', '')}]: {p.get('description', '')}" for p in prefix_setup
                )
            else:
                prefix_setup_str = "(Chưa cấu hình loại thực thể trong Bible Prefix / bảng bible_prefix_config.)"
        except Exception:
            prefix_setup_str = "(Chưa cấu hình loại thực thể trong Bible Prefix.)"

        chapter_list_str = get_chapter_list_for_router(project_id) if project_id else "(Trống)"
        filter_multi = is_multi_step_update_data_request(user_prompt) or is_multi_intent_request(user_prompt)
        router_prompt = f"""
### VAI TRÒ
Bạn là AI Điều Phối Viên (Router) cho hệ thống V7-Universal. Nhiệm vụ của bạn là phân tích Input của User và quyết định công cụ (Intent) chính xác nhất để xử lý. Chỉ trả về JSON.

### 1. DỮ LIỆU ĐẦU VÀO
- QUY TẮC DỰ ÁN: {rules_context}
- BẢNG PREFIX ENTITY: {prefix_setup_str}
- DANH SÁCH ENTITY (Bible): {bible_index if bible_index else "(Trống)"}
- DANH SÁCH CHƯƠNG (số - tên): {chapter_list_str}
- LỊCH SỬ CHAT: {chat_history_text}
- REFERENCE (bộ lọc nhanh): Câu hỏi có thể cần **nhiều bước / nhiều intent**: {filter_multi}. Chỉ dùng làm tham khảo; bạn có quyền quyết định cuối.

### 2. BẢNG QUY TẮC CHỌN INTENT (ƯU TIÊN TỪ TRÊN XUỐNG)

| INTENT | ĐIỀU KIỆN KÍCH HOẠT (TRIGGER) | TỪ KHÓA NHẬN DIỆN |
| :--- | :--- | :--- |
| **ask_user_clarification** | Câu hỏi quá ngắn, mơ hồ, thiếu chủ ngữ hoặc không rõ ngữ cảnh. | "Tính đi", "Nó là ai", "Cái đó sao rồi" (khi không có history). |
| **web_search** | Cần thông tin **THỰC TẾ, THỜI GIAN THỰC** bên ngoài dự án. | "Tỷ giá", "Giá vàng", "Thời tiết", "Tin tức", "Thông số súng Glock ngoài đời", "mới nhất", "tra cứu". |
| **numerical_calculation** | Yêu cầu **TÍNH TOÁN CON SỐ**, thống kê, so sánh dữ liệu định lượng. | "Tính tổng", "Doanh thu", "Trung bình", "Đếm số lượng", "% tăng trưởng". |
| **update_data** | User yêu cầu **thay đổi/ghi dữ liệu** hệ thống. Gồm hai nhóm: (1) **Ghi nhớ quy tắc**: "Hãy nhớ rằng...", "Cập nhật quy tắc...", "Thêm nhân vật..." -> data_operation_type: "remember_rule", data_operation_target: "rule", update_summary: mô tả. (2) **Thao tác theo chương**: trích xuất/xóa/cập nhật Bible, Relation, Timeline, Chunking theo chương -> data_operation_type: "extract"|"update"|"delete", data_operation_target: "bible"|"relation"|"timeline"|"chunking", chapter_range. | "Hãy nhớ rằng...", "Trích xuất Bible chương 1", "Xóa relation chương 2", "Cập nhật timeline chương 3". |
| **read_full_content** | 1. Nhắc **TÊN FILE** hoặc **SỐ CHƯƠNG** cụ thể. 2. Yêu cầu: Tóm tắt, Review, Viết tiếp, Kiểm tra logic toàn bài. | "Chương 1", "Chapter 5", "File luong.xlsx", "Tóm tắt chương này". |
| **manage_timeline** | Hỏi về **THỨ TỰ THỜI GIAN**, sự kiện trước/sau, timeline, flashback. | "Sự kiện nào trước", "Sau khi A chết thì...", "Mốc thời gian", "Năm bao nhiêu". |
| **query_Sql** | User **CHỈ MUỐN XEM/LIỆT KÊ** dữ liệu thô (không hỏi tự nhiên). Dùng khi: "Liệt kê chương", "Cho tôi xem luật", "Xuất timeline dạng danh sách". **KHÔNG** chọn query_Sql khi user **hỏi tự nhiên** kiểu "A và B có quan hệ gì", "Quan hệ giữa X và Y", "Sự kiện nào diễn ra trước" — những câu đó chọn search_bible hoặc manage_timeline. Khi chọn query_Sql BẮT BUỘC điền **query_target**. | "Liệt kê chương", "Cho tôi xem luật", "Xuất timeline chương 2 dạng list". |
| **mixed_context** | User hỏi **MỘT việc** duy nhất nhưng để trả lời cần **dữ liệu hỗn hợp**: vừa nội dung chương/file vừa Bible (nhân vật, lore, quan hệ). Một câu hỏi → một câu trả lời. **Không** chọn khi user nói rõ **nhiều thao tác** — lúc đó chọn suggest_v7. | "Trong chương 3 nhân vật A làm gì và quan hệ với B", "Chương 5 mô tả nhân vật X thế nào". |
| **search_chunks** | Hỏi **CHI TIẾT VỤN VẶT** trong văn bản nhưng **KHÔNG** nhắc số chương cụ thể. | "Ai nói câu...", "Hùng cầm vũ khí gì", "Chi tiết cái áo màu đỏ". |
| **search_bible** | Hỏi về **Lore, nhân vật, quan hệ giữa các nhân vật, timeline/sự kiện** (chi tiết); hoặc tham chiếu chat cũ. Intent này **mở rộng**: khi user hỏi **quan hệ** (A và B có quan hệ gì, mối quan hệ giữa X và Y) -> chọn search_bible, điền target_bible_entities = [A, B] hoặc [X, Y]. Khi user hỏi **timeline/sự kiện** (sự kiện nào trước, mốc thời gian) nhưng không chỉ rõ "liệt kê" -> có thể search_bible hoặc manage_timeline. **Ưu tiên search_bible** cho câu hỏi tự nhiên về quan hệ/timeline. | "A và B có quan hệ gì", "Quan hệ giữa X và Y", "Mối quan hệ của nhân vật A", (tên nhân vật), "Thế giới này vận hành sao", "Sự kiện nào diễn ra trước", "như tôi đã nói về...". |
| **suggest_v7** | Câu hỏi **rõ ràng cần 2+ intent** hoặc **2+ thao tác update_data** (vd: trích xuất Bible + Relation + Timeline + Chunking; hoặc "tóm tắt chương 1 rồi so sánh timeline"). Dùng REFERENCE (bộ lọc nhanh) làm gợi ý; nếu đồng ý thì trả về suggest_v7. | "Chạy tất cả data analyze chương 1", "tóm tắt chương 1 rồi so sánh với timeline", "trích xuất bible và relation chương 2". |
| **chat_casual** | Chào hỏi xã giao, không yêu cầu dữ liệu hay tra cứu. | "Hello", "Cảm ơn", "Bạn khỏe không". |

**BẢNG QUERY_TARGET (chỉ dùng khi intent = query_Sql):**
| query_target | Ý user | Ví dụ |
| :--- | :--- | :--- |
| chapters | Danh sách / thông tin chương | "Liệt kê chương", "Chương 1 tên gì", "Có bao nhiêu chương" |
| rules | Luật, quy tắc dự án | "Luật là gì", "Liệt kê quy tắc", "Rule nào đang dùng" |
| bible_entity | Entity Bible (nhân vật, địa điểm, khái niệm) | "Nhân vật A trong Bible", "Entity X có mô tả gì" |
| chunks | Đoạn văn đã chunk | "Chunks chương 2", "Đoạn văn đã tách chương 1" |
| timeline | Sự kiện, mốc thời gian (liệt kê/xem) | "Timeline chương 1", "Sự kiện chương 2", "Mốc thời gian" |
| relation | Chỉ khi user **liệt kê/xem dữ liệu** quan hệ (không hỏi tự nhiên). Câu hỏi "A và B có quan hệ gì" -> search_bible. | "Liệt kê quan hệ của A", "Xuất bảng relation" |
| summary | Tóm tắt (crystallize) | "Tóm tắt đã lưu", "Summary chương 3" |
| art | Nghệ thuật, style | "Nghệ thuật chương 1", "Style tác phẩm" |

### 3. HƯỚNG DẪN XỬ LÝ ĐẶC BIỆT (CRITICAL RULES)
1. **Quy tắc "Chương Cụ Thể":** Khi user nhắc "Chương X", "Chapter Y" và yêu cầu **đọc/tóm tắt/xem** nội dung -> chọn `read_full_content`, tuyệt đối KHÔNG chọn `search_chunks`. Nếu user **ra lệnh thao tác dữ liệu** (extract/update/delete Bible, Relation, Timeline, Chunking) theo chương thì ưu tiên quy tắc 7 -> `update_data`, không áp dụng "Chương Cụ Thể" cho read_full_content.
2. **Quy tắc "Thực Tế":** Nếu hỏi tỷ giá, tin tức, thời tiết, giá vàng, thông số thực tế -> BẮT BUỘC chọn `web_search`. Tuyệt đối KHÔNG chọn `chat_casual` hay `search_bible`.
3. **Quy tắc "Làm Rõ":** Nếu không hiểu user muốn gì (câu quá ngắn/mơ hồ) -> Chọn `ask_user_clarification` và điền `clarification_question`.
4. **Quy tắc "Tham chiếu chat cũ":** Nếu tin nhắn mới CHỈ là tham chiếu đến lệnh/câu hỏi trước (vd: "làm cái đó", "ok làm đi", "như vừa nói", "thực hiện đi", "đúng rồi làm đi") thì dựa vào LỊCH SỬ CHAT: lấy lại intent và rewritten_query của tin nhắn user gần nhất có nội dung cụ thể, điền vào output.
5. **Quy tắc "Tham chiếu nội dung chat (crystallize)":** Nếu user nói đã bàn / đã nói về chủ đề X trong chat -> chọn `search_bible`. Điền `rewritten_query` là chủ đề hoặc từ khóa cần tìm.
6. **Quy tắc "Nhiều bước (suggest_v7)":** Nếu câu hỏi **rõ ràng** cần thực thi 2+ intent hoặc 2+ thao tác update_data -> chọn `suggest_v7`, điền `reason` giải thích ngắn.
7. **Quy tắc "update_data — tránh nhầm":** Chỉ chọn `update_data` khi user **ra lệnh thay đổi/ghi dữ liệu**. Nếu user **chỉ muốn xem, tóm tắt, hỏi** thì KHÔNG chọn update_data.
8. **Quy tắc "Tra cứu":** "Tra cứu" đi với tỷ giá, tin tức, thời tiết -> `web_search`. "Tra cứu" đi với nội dung dự án -> `search_bible` hoặc `read_full_content`.
9. **Quy tắc "query_Sql":** Chọn `query_Sql` CHỈ khi user **chỉ muốn XEM/LIỆT KÊ/TRÍCH** dữ liệu thô (vd "Liệt kê chương", "Cho tôi xem luật"). **KHÔNG** chọn query_Sql cho câu hỏi tự nhiên về quan hệ hay timeline. Điền **query_target** đúng một giá trị trong bảng QUERY_TARGET.
10. **Quy tắc "query_Sql vs search_bible vs read_full_content":** `query_Sql` = xem/liệt kê dữ liệu cấu trúc (liệt kê, xuất, cho tôi xem). `search_bible` = hỏi lore, nhân vật, **quan hệ giữa nhân vật** (vd "A và B có quan hệ gì", "Quan hệ giữa X và Y"), timeline/sự kiện chi tiết. `read_full_content` = đọc/tóm tắt **nội dung văn bản** chương/file.
12. **Quy tắc "Quan hệ nhân vật":** Khi user hỏi **quan hệ giữa hai hay nhiều nhân vật** (vd "A và B có quan hệ gì", "Quan hệ giữa X và Y", "Mối quan hệ của nhân vật A") -> luôn chọn **search_bible**, điền **target_bible_entities** = [tên các nhân vật]. **Tuyệt đối KHÔNG** chọn query_Sql cho loại câu này.
11. **Quy tắc "mixed_context (một việc, dữ liệu hỗn hợp)":** User chỉ hỏi **một điều** nhưng câu trả lời cần **cả** nội dung chương/file **và** Bible (nhân vật, quan hệ, lore) → chọn `mixed_context`. Chỉ đọc/tóm tắt/xem nội dung chương, không đòi hỏi kết hợp Bible → `read_full_content`. **Phân biệt với suggest_v7:** Nếu user nói rõ **nhiều việc** (vd "tóm tắt chương 1 **rồi** so sánh với timeline", "trích Bible **và** relation chương 2") → `suggest_v7`, không dùng `mixed_context`.

### 4. LOGIC TRÍCH XUẤT CHAPTER RANGE
- "Chương 1", "Chap 5" -> chapter_range_mode: "range", chapter_range: [1, 1] hoặc [5, 5]
- "Chương 1 đến 5" -> chapter_range_mode: "range", chapter_range: [1, 5]
- "3 chương đầu" -> chapter_range_mode: "first", chapter_range_count: 3
- "Chương mới nhất" -> chapter_range_mode: "latest", chapter_range_count: 1
- Không liên quan chương -> chapter_range: null, chapter_range_mode: null

### 5. VÍ DỤ MINH HỌA (FEW-SHOT)
**Input:** "Tóm tắt nội dung chương 1 cho anh."
**Output:** {{ "intent": "read_full_content", "reason": "User yêu cầu tóm tắt và chỉ định chương 1.", "chapter_range": [1, 1], "chapter_range_mode": "range", "rewritten_query": "Tóm tắt chương 1", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Tỷ giá USD/VND hôm nay bao nhiêu?"
**Output:** {{ "intent": "web_search", "reason": "Hỏi thông tin thời gian thực ngoài hệ thống.", "rewritten_query": "Tỷ giá USD VND hôm nay", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Trong chương 3 nhân vật A làm gì và quan hệ với B thế nào?"
**Output:** {{ "intent": "mixed_context", "reason": "Một câu hỏi cần cả nội dung chương 3 và thông tin Bible (A, B, quan hệ). Dữ liệu hỗn hợp, một câu trả lời.", "chapter_range": [3, 3], "chapter_range_mode": "range", "rewritten_query": "Nhân vật A làm gì trong chương 3 và quan hệ với B", "target_files": [], "target_bible_entities": ["A", "B"], "inferred_prefixes": [], "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "A và B có quan hệ gì?" hoặc "Quan hệ giữa nhân vật X và Y?"
**Output:** {{ "intent": "search_bible", "reason": "User hỏi tự nhiên về quan hệ giữa nhân vật. Dùng search_bible, không dùng query_Sql.", "rewritten_query": "Quan hệ giữa A và B", "target_files": [], "target_bible_entities": ["A", "B"], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "", "query_target": "" }}

**Input:** "Tóm tắt chương 1 rồi so sánh với timeline chương 2."
**Output:** {{ "intent": "suggest_v7", "reason": "User yêu cầu rõ ràng hai việc: tóm tắt chương 1 và so sánh với timeline. Cần nhiều bước.", "rewritten_query": "Tóm tắt chương 1 rồi so sánh với timeline chương 2", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

### 6. INPUT CỦA USER
"{user_prompt}"

### 7. OUTPUT (JSON ONLY) — Trả về đúng format sau, đủ các key:
{{
    "intent": "ask_user_clarification" | "web_search" | "numerical_calculation" | "update_data" | "read_full_content" | "manage_timeline" | "query_Sql" | "mixed_context" | "search_chunks" | "search_bible" | "suggest_v7" | "chat_casual",
    "target_files": [],
    "target_bible_entities": [],
    "inferred_prefixes": [],
    "reason": "Lý do ngắn gọn bằng tiếng Việt",
    "rewritten_query": "Viết lại câu hỏi cho search",
    "chapter_range": null hoặc [start, end],
    "chapter_range_mode": null hoặc "first" | "latest" | "range",
    "chapter_range_count": 5,
    "clarification_question": "" hoặc "Câu hỏi gợi ý (khi intent ask_user_clarification)",
    "update_summary": "" hoặc "Mô tả nội dung sẽ ghi (khi update_data + remember_rule)",
    "data_operation_type": "" hoặc "remember_rule" | "extract" | "update" | "delete" (khi intent update_data),
    "data_operation_target": "" hoặc "rule" | "bible" | "relation" | "timeline" | "chunking",
    "query_target": "" hoặc "chapters" | "rules" | "bible_entity" | "chunks" | "timeline" | "relation" | "summary" | "art" (BẮT BUỘC khi intent = query_Sql)
}}
"""

        messages = [
            {"role": "system", "content": "Bạn là AI Router thông minh. Chỉ trả về JSON."},
            {"role": "user", "content": router_prompt}
        ]
        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=_get_default_tool_model(),
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)
            result = json.loads(content)
            result.setdefault("target_files", [])
            result.setdefault("target_bible_entities", [])
            result.setdefault("inferred_prefixes", [])
            result.setdefault("rewritten_query", user_prompt)
            result.setdefault("chapter_range", None)
            result.setdefault("chapter_range_mode", None)
            result.setdefault("chapter_range_count", 5)
            result.setdefault("clarification_question", "")
            result.setdefault("update_summary", "")
            result.setdefault("data_operation_type", "")
            result.setdefault("data_operation_target", "")
            result.setdefault("query_target", "")
            if not isinstance(result.get("inferred_prefixes"), list):
                result["inferred_prefixes"] = []
            valid_keys = Config.get_valid_prefix_keys()
            if valid_keys:
                result["inferred_prefixes"] = [
                    p for p in result["inferred_prefixes"]
                    if p and str(p).strip().upper().replace(" ", "_") in valid_keys
                ]
            return result
        except Exception as e:
            print(f"Router error: {e}")
            return {
                "intent": "chat_casual",
                "target_files": [], "target_bible_entities": [], "inferred_prefixes": [],
                "reason": f"Router error: {e}", "rewritten_query": user_prompt,
                "chapter_range": None, "chapter_range_mode": None, "chapter_range_count": 5,
                "clarification_question": "", "update_summary": "",
                "data_operation_type": "", "data_operation_target": "", "query_target": "",
            }

    @staticmethod
    def get_plan_v7(user_prompt: str, chat_history_text: str, project_id: str = None) -> Dict:
        """V7 Agentic Planner: Trả về plan (mảng bước) thay vì single intent."""
        rules_context = ""
        bible_index = ""
        prefix_setup_str = ""
        if project_id:
            rules_context = get_mandatory_rules(project_id)
            bible_index = get_bible_index(project_id, max_tokens=2000)
        try:
            prefix_setup = Config.get_prefix_setup()
            prefix_setup_str = "\n".join(
                f"- [{p.get('prefix_key', '')}]: {p.get('description', '')}" for p in (prefix_setup or [])
            ) if prefix_setup else "(Chưa cấu hình Bible Prefix.)"
        except Exception:
            prefix_setup_str = "(Chưa cấu hình Bible Prefix.)"
        chat_history_capped = cap_chat_history_to_tokens(chat_history_text or "")
        chapter_list_str = get_chapter_list_for_router(project_id) if project_id else "(Trống)"
        planner_prompt = f"""Bạn là V7 Planner. Nhiệm vụ: phân tích câu user và đưa ra KẾ HOẠCH (mảng bước) thực thi.

DỮ LIỆU: QUY TẮC={rules_context[:1500]} | PREFIX={prefix_setup_str[:800]} | BIBLE INDEX={bible_index[:2000] if bible_index else "(Trống)"} | DANH SÁCH CHƯƠNG (số - tên)={chapter_list_str} | LỊCH SỬ={chat_history_capped}

INPUT USER: "{user_prompt}"

QUY TẮC:
- Tham chiếu chat cũ -> lấy query_refined từ LỊCH SỬ.
- **mixed_context (một việc, dữ liệu hỗn hợp):** Khi user hỏi MỘT điều nhưng câu trả lời cần CẢ nội dung chương/file VÀ Bible (nhân vật, quan hệ, lore) -> dùng ĐÚNG MỘT bước intent `mixed_context`. Không tách thành 2 bước read_full_content + search_bible. mixed_context = một câu hỏi, một câu trả lời, chỉ khác là context gom nhiều nguồn.
- **Nhiều bước (plan 2+ step):** Chỉ khi user nói RÕ nhiều việc hoặc thao tác (vd "tóm tắt chương 1 rồi so sánh với timeline", "trích Bible và relation chương 2") -> tách thành nhiều bước, đặt dependency khi bước sau cần output bước trước.
- Chương cụ thể đọc/tóm tắt (không đòi Bible) -> read_full_content. update_data chỉ khi ra lệnh thực thi. update_data theo khoảng chương -> một bước mỗi (data_operation_type, data_operation_target) với chapter_range [start,end]. **Quan hệ/timeline:** Câu hỏi tự nhiên về quan hệ giữa nhân vật (A và B có quan hệ gì) hoặc timeline/sự kiện -> dùng **search_bible** (hoặc manage_timeline nếu chỉ thứ tự thời gian), điền target_bible_entities khi có tên nhân vật. **KHÔNG** dùng query_Sql cho câu hỏi dạng này. query_Sql chỉ khi user muốn XEM/LIỆT KÊ dữ liệu thô (liệt kê chương, xuất luật, xuất timeline dạng list). query_Sql -> args có query_target. dependency: null cho update_data, query_Sql, web_search, ask_user_clarification, chat_casual; step_id bước trước khi bước sau cần output. verification_required: true nếu plan có numerical_calculation, manage_timeline, read_full_content, search_chunks, search_bible, mixed_context, query_Sql.

Trả về ĐÚNG MỘT JSON:
{{ "analysis": "...", "plan": [ {{ "step_id": 1, "intent": "...", "args": {{ "query_refined": "...", "target_files": [], "target_bible_entities": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "data_operation_type": "", "data_operation_target": "", "query_target": "" }}, "dependency": null }} ], "verification_required": true }}
Chỉ trả về JSON."""

        try:
            response = AIService.call_openrouter(
                messages=[
                    {"role": "system", "content": "Bạn là V7 Planner. Chỉ trả về JSON với analysis, plan, verification_required."},
                    {"role": "user", "content": planner_prompt}
                ],
                model=_get_default_tool_model(),
                temperature=0.1,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)
            data = json.loads(content)
        except Exception as e:
            print(f"Planner V7 error: {e}")
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)
        plan = data.get("plan")
        if not plan or not isinstance(plan, list):
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)
        analysis = data.get("analysis", "")
        verification_required = bool(data.get("verification_required", False))
        valid_intents = {"manage_timeline", "numerical_calculation", "read_full_content", "search_chunks", "search_bible", "mixed_context", "web_search", "ask_user_clarification", "update_data", "query_Sql", "chat_casual"}
        normalized_plan = []
        for i, s in enumerate(plan):
            if not isinstance(s, dict):
                continue
            intent = (s.get("intent") or "chat_casual").strip().lower()
            args = s.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if intent not in valid_intents:
                if intent in ("extract_bible", "extract_relation", "extract_timeline", "extract_chunking"):
                    target = intent.replace("extract_", "")
                    intent = "update_data"
                    args = dict(args)
                    if not args.get("data_operation_target"):
                        args["data_operation_target"] = target
                    if not args.get("data_operation_type"):
                        args["data_operation_type"] = "extract"
                else:
                    intent = "chat_casual"
            step_id = int(s.get("step_id", i + 1))
            dependency = s.get("dependency")
            normalized_plan.append({
                "step_id": step_id,
                "intent": intent,
                "args": {
                    "query_refined": args.get("query_refined") or args.get("rewritten_query") or user_prompt,
                    "target_files": args.get("target_files") if isinstance(args.get("target_files"), list) else [],
                    "target_bible_entities": args.get("target_bible_entities") if isinstance(args.get("target_bible_entities"), list) else [],
                    "chapter_range": args.get("chapter_range"),
                    "chapter_range_mode": args.get("chapter_range_mode"),
                    "chapter_range_count": args.get("chapter_range_count", 5),
                    "inferred_prefixes": args.get("inferred_prefixes") if isinstance(args.get("inferred_prefixes"), list) else [],
                    "clarification_question": args.get("clarification_question") or "",
                    "update_summary": args.get("update_summary") or "",
                    "data_operation_type": args.get("data_operation_type") or "",
                    "data_operation_target": args.get("data_operation_target") or "",
                    "query_target": args.get("query_target") or "",
                },
                "dependency": dependency,
            })
        if not normalized_plan:
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)
        intents_need_verify = {"numerical_calculation", "manage_timeline", "read_full_content", "search_chunks", "search_bible", "mixed_context", "query_Sql"}
        if any(s.get("intent") in intents_need_verify for s in normalized_plan):
            verification_required = True
        return {"analysis": analysis, "plan": normalized_plan, "verification_required": verification_required}

    @staticmethod
    def _single_intent_to_plan(single_router_result: Dict, user_prompt: str) -> Dict:
        """Chuyển kết quả router single-intent thành plan 1 bước (tương thích V7)."""
        intent = single_router_result.get("intent", "chat_casual")
        return {
            "analysis": single_router_result.get("reason", ""),
            "plan": [{
                "step_id": 1,
                "intent": intent,
                "args": {
                    "query_refined": single_router_result.get("rewritten_query") or user_prompt,
                    "target_files": single_router_result.get("target_files") or [],
                    "target_bible_entities": single_router_result.get("target_bible_entities") or [],
                    "chapter_range": single_router_result.get("chapter_range"),
                    "chapter_range_mode": single_router_result.get("chapter_range_mode"),
                    "chapter_range_count": single_router_result.get("chapter_range_count", 5),
                    "inferred_prefixes": single_router_result.get("inferred_prefixes") or [],
                    "clarification_question": single_router_result.get("clarification_question") or "",
                    "update_summary": single_router_result.get("update_summary") or "",
                    "data_operation_type": single_router_result.get("data_operation_type") or "",
                    "data_operation_target": single_router_result.get("data_operation_target") or "",
                    "query_target": single_router_result.get("query_target") or "",
                },
                "dependency": None,
            }],
            "verification_required": intent in (
                "numerical_calculation", "manage_timeline",
                "read_full_content", "search_chunks", "search_bible", "mixed_context", "query_Sql",
            ),
        }
