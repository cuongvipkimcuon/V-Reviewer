# ai_verifier.py - V7 Verifier & Self-Correction Loop (Anti-Hallucination)
"""Verify theo từng intent: skip / numerical / timeline / grounding. Vòng lặp tự sửa với giới hạn retry."""
import re
from typing import Dict, List, Tuple, Any, Callable, Optional

MAX_RETRIES = 2

# Intent không cần verify (không sinh fact từ context)
INTENTS_SKIP_VERIFY = {"ask_user_clarification", "update_data", "chat_casual"}

# Intent verify số (so với Python executor)
INTENTS_VERIFY_NUMERICAL = {"numerical_calculation"}

# Intent verify timeline (độ dài, thứ tự)
INTENTS_VERIFY_TIMELINE = {"manage_timeline"}

# Intent verify grounding (chỉ được dựa trên Bible/chunk/timeline/context)
INTENTS_VERIFY_GROUNDING = {
    "read_full_content",
    "search_chunks",
    "search_bible",
    "mixed_context",
    "query_Sql",
}

# web_search: tùy chọn verify nhẹ (mặc định bỏ qua)
INTENT_WEB_SEARCH = "web_search"


def _extract_numbers(text: str) -> List[float]:
    """Trích các số thực/số nguyên từ text (để so sánh tolerance)."""
    if not text:
        return []
    numbers = []
    for m in re.finditer(r"-?\d+\.?\d*", text.replace(",", ".")):
        try:
            numbers.append(float(m.group()))
        except ValueError:
            pass
    return numbers


def _verify_numerical(response: str, context: str) -> Tuple[bool, str]:
    """So sánh số trong response với executor result trong context (tolerance 1%)."""
    exec_block = "KẾT QUẢ TÍNH TOÁN (Python Executor)"
    if exec_block not in context:
        return True, ""
    ctx_nums = _extract_numbers(context)
    resp_nums = _extract_numbers(response)
    if not ctx_nums or not resp_nums:
        return True, ""
    try:
        ref = ctx_nums[-1]
        for r in resp_nums:
            if ref != 0 and abs(r - ref) / abs(ref) > 0.01:
                return False, f"Số trong câu trả lời ({r}) lệch >1% so với kết quả tính toán ({ref})."
    except (ZeroDivisionError, TypeError):
        pass
    return True, ""


def _verify_timeline(response: str, context: str) -> Tuple[bool, str]:
    """Context có timeline thì response không được quá ngắn."""
    if "TIMELINE" not in context.upper() and "event_order" not in context.lower():
        return True, ""
    if len((response or "").strip()) < 10:
        return False, "Câu trả lời về timeline quá ngắn so với context."
    return True, ""


def _verify_grounding_llm(response: str, context: str, max_context_chars: int = 10000) -> Tuple[bool, str]:
    """
    LLM-as-judge: kiểm tra response chỉ dựa trên context.
    Returns (is_valid, error_msg). error_msg rỗng nếu valid.
    """
    try:
        from ai_engine import AIService, _get_default_tool_model
    except ImportError:
        return True, ""

    if not response or not context:
        return True, ""
    ctx_slice = context[:max_context_chars] if len(context) > max_context_chars else context
    resp_slice = (response[:4000] + "...") if len(response) > 4000 else response

    judge_prompt = f"""Bạn là người kiểm tra. Nhiệm vụ: xác định xem RESPONSE có CHỈ dựa trên thông tin trong CONTEXT không.

CONTEXT:
{ctx_slice}

RESPONSE:
{resp_slice}

Nếu RESPONSE chứa bất kỳ thông tin/claim nào KHÔNG có nguồn trong CONTEXT (bịa đặt, suy diễn ngoài context), trả lời:
VIOLATION: <trích đoạn ngắn vi phạm>
Nếu RESPONSE chỉ dùng thông tin từ CONTEXT, trả lời:
OK"""

    try:
        r = AIService.call_openrouter(
            messages=[{"role": "user", "content": judge_prompt}],
            model=_get_default_tool_model(),
            temperature=0.0,
            max_tokens=200,
        )
        content = (r.choices[0].message.content or "").strip().upper()
        if content.startswith("OK") or content.startswith("VIOLATION:"):
            if content.startswith("VIOLATION:"):
                msg = (r.choices[0].message.content or "").strip()
                return False, msg.replace("VIOLATION:", "").strip() or "Câu trả lời chứa thông tin không có trong Context."
            return True, ""
        # Không parse được -> coi như pass để tránh block
        return True, ""
    except Exception as e:
        print(f"_verify_grounding_llm error: {e}")
        return True, ""


def _intents_from_plan(plan: List[Dict]) -> List[str]:
    """Lấy danh sách intent có trong plan (không trùng)."""
    seen = set()
    out = []
    for s in plan or []:
        i = (s.get("intent") or "").strip()
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def verify_output(
    response: str,
    context: str,
    plan: List[Dict],
    step_results: Optional[List[Dict]] = None,
) -> Tuple[bool, str]:
    """
    Kiểm tra response theo từng loại intent trong plan.
    - ask_user_clarification, update_data, chat_casual: không verify.
    - numerical_calculation: so sánh số với executor (1%).
    - manage_timeline: độ dài và timeline có trong context.
    - read_full_content, search_chunks, search_bible, mixed_context, query_Sql: grounding (LLM judge).
    - web_search: bỏ qua (hoặc tùy chọn sau).
    Returns: (is_valid, error_msg).
    """
    if not response or not response.strip():
        return False, "Response trống."

    step_results = step_results or []
    intents = _intents_from_plan(plan)

    # Chỉ toàn intent skip -> không cần verify
    if intents and all(i in INTENTS_SKIP_VERIFY for i in intents):
        return True, ""

    # Numerical
    if any(i in INTENTS_VERIFY_NUMERICAL for i in intents):
        ok, err = _verify_numerical(response, context)
        if not ok:
            return False, err

    # Timeline
    if any(i in INTENTS_VERIFY_TIMELINE for i in intents):
        ok, err = _verify_timeline(response, context)
        if not ok:
            return False, err

    # Grounding (Bible / chunk / timeline / file context)
    if any(i in INTENTS_VERIFY_GROUNDING for i in intents):
        ok, err = _verify_grounding_llm(response, context)
        if not ok:
            return False, err

    return True, ""


def run_verification_loop(
    draft_response: str,
    context: str,
    plan: List[Dict],
    step_results: List[Dict],
    llm_generate_fn: Callable[[str, str], str],
    verification_required: bool = True,
) -> tuple:
    """
    Vòng lặp tự sửa: verify -> nếu fail thì gửi correction prompt -> generate lại -> verify.
    Tối đa MAX_RETRIES lần. Sau đó trả về response kèm cảnh báo (anti-death).
    llm_generate_fn(system_content, user_content) -> response_text.
    Returns: (final_response: str, retries_used: int)
    """
    current_response = draft_response
    retry_count = 0
    error_msg = ""

    if not verification_required:
        return current_response, 0

    while retry_count < MAX_RETRIES:
        is_valid, error_msg = verify_output(current_response, context, plan, step_results)
        if is_valid:
            return current_response, retry_count

        retry_count += 1
        print(f"⚠️ Verification Failed (Attempt {retry_count}/{MAX_RETRIES}): {error_msg}")

        correction_system = """Bạn là trợ lý chỉnh sửa. Nhiệm vụ: tạo lại câu trả lời ĐÚNG dựa trên Context, sửa lỗi đã được báo."""
        correction_user = f"""[SYSTEM ALERT: VERIFICATION FAILED]
Lỗi phát hiện: {error_msg}

CONTEXT (dữ liệu đã thu thập):
{context[:12000]}

Câu trả lời trước (có lỗi):
{current_response[:3000]}

Yêu cầu: Tạo lại câu trả lời MỚI, tuân thủ chặt chẽ Context và sửa lỗi trên. Chỉ trả về nội dung câu trả lời, không giải thích thêm."""

        try:
            current_response = llm_generate_fn(correction_system, correction_user)
            if not current_response or not current_response.strip():
                current_response = draft_response
                break
        except Exception as e:
            print(f"Verification re-generate error: {e}")
            break

    is_valid_final, final_error = verify_output(current_response, context, plan, step_results)
    if not is_valid_final and final_error:
        current_response += f"\n\n(⚠️ Cảnh báo: Câu trả lời có thể chứa mâu thuẫn chưa được kiểm chứng hoàn toàn. Lỗi: {final_error})"
    return current_response, retry_count
