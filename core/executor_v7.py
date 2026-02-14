# core/executor_v7.py - V7 Sequential Execution Engine + Dynamic Re-planning
"""Thực thi plan tuần tự; sau mỗi bước đánh giá outcome và có thể re-plan (thay bước còn lại)."""
from typing import Dict, List, Tuple, Any, Optional

# Import từ ai_engine khi cần (tránh circular)
def _get_engine():
    from ai_engine import ContextManager, AIService, parse_chapter_range_from_query, _get_default_tool_model
    from config import Config
    return ContextManager, AIService, Config, parse_chapter_range_from_query, _get_default_tool_model


def _get_replan():
    from ai_engine import evaluate_step_outcome, replan_after_step
    return evaluate_step_outcome, replan_after_step


def step_to_router_result(step: Dict, user_prompt: str) -> Dict:
    """Chuyển một step trong plan thành dict router_result cho ContextManager.build_context."""
    intent = step.get("intent", "chat_casual")
    args = step.get("args") or {}
    return {
        "intent": intent,
        "target_files": args.get("target_files") or [],
        "target_bible_entities": args.get("target_bible_entities") or [],
        "rewritten_query": args.get("query_refined") or user_prompt,
        "chapter_range": args.get("chapter_range"),
        "chapter_range_mode": args.get("chapter_range_mode"),
        "chapter_range_count": args.get("chapter_range_count", 5),
        "inferred_prefixes": args.get("inferred_prefixes") or [],
        "clarification_question": args.get("clarification_question") or "",
        "update_summary": args.get("update_summary") or "",
    }


def _normalize_step(step: Dict, step_id: int, user_prompt: str) -> Dict:
    """Chuẩn hóa step từ LLM re-plan (có thể thiếu key) thành format đủ args."""
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    return {
        "step_id": step_id,
        "intent": (step.get("intent") or "chat_casual").strip(),
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
        },
        "dependency": step.get("dependency"),
    }


def execute_plan(
    plan: List[Dict],
    project_id: str,
    persona: Dict,
    user_prompt: str,
    strict_mode: bool = False,
    current_arc_id: Optional[str] = None,
    session_state: Optional[Dict] = None,
    free_chat_mode: bool = False,
    max_context_tokens: Optional[int] = None,
    run_numerical_executor: bool = True,
    max_steps_per_turn: int = 5,
    max_replan_rounds: int = 2,
) -> Tuple[str, List[str], List[Dict], List[Dict]]:
    """
    Thực thi plan; sau mỗi bước có thể re-plan (đổi phần còn lại nếu bước vừa thất bại).
    Returns: (cumulative_context, sources, step_results, replan_events).
    replan_events: [ { "step_id", "reason", "action", "new_plan_summary" } ].
    """
    ContextManager, AIService, Config, parse_chapter_range_from_query, _get_default_tool_model = _get_engine()
    try:
        from utils.python_executor import PythonExecutor
    except ImportError:
        PythonExecutor = None

    evaluate_step_outcome, replan_after_step = _get_replan()

    cumulative_parts: List[str] = []
    all_sources: List[str] = []
    step_results: List[Dict] = []
    replan_events: List[Dict] = []

    token_limit = max_context_tokens or Config.CONTEXT_SIZE_TOKENS.get("medium", 60000)
    remaining_steps = list(plan)
    steps_executed = 0
    replan_count = 0

    while remaining_steps and steps_executed < max_steps_per_turn:
        step = remaining_steps[0]
        step_id = step.get("step_id", len(step_results) + 1)
        intent = step.get("intent", "chat_casual")
        router_result = step_to_router_result(step, user_prompt)

        ctx_text, sources, _ = ContextManager.build_context(
            router_result,
            project_id,
            persona,
            strict_mode=strict_mode,
            current_arc_id=current_arc_id,
            session_state=session_state,
            free_chat_mode=free_chat_mode,
            max_context_tokens=token_limit,
        )

        executor_result = None
        if intent == "numerical_calculation" and run_numerical_executor and PythonExecutor and not free_chat_mode:
            try:
                code_prompt = f"""User hỏi: "{user_prompt}"
Context có sẵn:
{ctx_text[:6000]}

Nhiệm vụ: Tạo code Python (pandas/numpy) để trả lời. Gán kết quả cuối vào biến result.
Chỉ trả về code trong block ```python ... ```, không giải thích."""
                model = _get_default_tool_model()
                resp = AIService.call_openrouter(
                    messages=[{"role": "user", "content": code_prompt}],
                    model=model,
                    temperature=0.1,
                    max_tokens=2000,
                )
                import re
                raw = (resp.choices[0].message.content or "").strip()
                m = re.search(r'```(?:python)?\s*(.*?)```', raw, re.DOTALL)
                code = (m.group(1).strip() if m else raw).strip()
                if code:
                    val, err = PythonExecutor.execute(code, result_variable="result")
                    executor_result = str(val) if val is not None else f"(Lỗi: {err})"
                    ctx_text += f"\n\n--- KẾT QUẢ TÍNH TOÁN (Python Executor) ---\n{executor_result}"
            except Exception as ex:
                executor_result = f"(Lỗi: {ex})"
                ctx_text += f"\n\n--- KẾT QUẢ TÍNH TOÁN ---\n{executor_result}"

        block = f"\n--- [STEP {step_id}: {intent}] ---\n{ctx_text}\n"
        cumulative_parts.append(block)
        all_sources.extend([f"Step {step_id}: {intent}"] + (sources or []))
        step_results.append({
            "step_id": step_id,
            "intent": intent,
            "context_snippet": ctx_text[:2000],
            "executor_result": executor_result,
        })
        steps_executed += 1
        cumulative_so_far = "\n".join(cumulative_parts)
        remaining_after = remaining_steps[1:]

        # Dynamic re-planning: đánh giá outcome và có thể thay plan còn lại
        should_replan, outcome_reason = evaluate_step_outcome(intent, ctx_text, sources or [])
        if should_replan and remaining_after and replan_count < max_replan_rounds:
            action, reason, new_plan = replan_after_step(
                user_prompt,
                cumulative_so_far,
                step_results,
                step,
                outcome_reason,
                remaining_after,
                project_id,
            )
            replan_events.append({
                "step_id": step_id,
                "reason": reason or outcome_reason,
                "action": action,
                "new_plan_summary": [s.get("intent") for s in new_plan] if new_plan else [],
            })
            if action == "replace" and new_plan:
                replan_count += 1
                # Chuẩn hóa new_plan và gán step_id liên tiếp
                normalized = []
                for i, s in enumerate(new_plan):
                    normalized.append(_normalize_step(s, len(step_results) + 1 + i, user_prompt))
                remaining_steps = normalized
                continue
            if action == "abort":
                remaining_steps = []
                break
        remaining_steps = remaining_after

    cumulative_context = "\n".join(cumulative_parts)
    if max_context_tokens and AIService.estimate_tokens(cumulative_context) > token_limit:
        cumulative_context = cumulative_context[: token_limit * 4]
    return cumulative_context, all_sources, step_results, replan_events
