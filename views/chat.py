import threading
from datetime import datetime

import streamlit as st

from config import Config, init_services, CostManager
from ai_engine import (
    AIService,
    ContextManager,
    SmartAIRouter,
    RuleMiningSystem,
    HybridSearch,
    check_semantic_intent,
)
from ai_verifier import run_verification_loop
from core.executor_v7 import execute_plan
from persona import PersonaSystem
from utils.auth_manager import check_permission, submit_pending_change
from utils.python_executor import PythonExecutor


def _get_crystallize_count(project_id, user_id):
    """Lấy số tin nhắn từ lần crystallize gần nhất (schema v7.1). Trả về 0 nếu chưa có bảng."""
    try:
        services = init_services()
        if not services:
            return 0
        r = services["supabase"].table("chat_crystallize_state").select("messages_since_crystallize").eq(
            "story_id", project_id
        ).eq("user_id", str(user_id) or "").limit(1).execute()
        if r.data and len(r.data) > 0:
            return int(r.data[0].get("messages_since_crystallize", 0) or 0)
    except Exception:
        pass
    return 0


def _increment_crystallize_count(project_id, user_id):
    """Tăng messages_since_crystallize lên 1 (sau khi lưu tin nhắn V Work)."""
    try:
        services = init_services()
        if not services:
            return
        sb = services["supabase"]
        now = datetime.utcnow().isoformat()
        r = sb.table("chat_crystallize_state").select("messages_since_crystallize").eq(
            "story_id", project_id
        ).eq("user_id", str(user_id) or "").limit(1).execute()
        if r.data and len(r.data) > 0:
            cur = int(r.data[0].get("messages_since_crystallize", 0) or 0)
            sb.table("chat_crystallize_state").update({
                "messages_since_crystallize": cur + 1,
                "updated_at": now,
            }).eq("story_id", project_id).eq("user_id", str(user_id) or "").execute()
        else:
            sb.table("chat_crystallize_state").upsert({
                "story_id": project_id,
                "user_id": str(user_id) or "",
                "messages_since_crystallize": 1,
                "updated_at": now,
            }, on_conflict="story_id,user_id").execute()
    except Exception:
        pass


def _reset_crystallize_count(project_id, user_id):
    """Reset về 0 sau khi crystallize (tránh trùng)."""
    try:
        services = init_services()
        if not services:
            return
        now = datetime.utcnow().isoformat()
        services["supabase"].table("chat_crystallize_state").upsert({
            "story_id": project_id,
            "user_id": str(user_id) or "",
            "messages_since_crystallize": 0,
            "updated_at": now,
        }, on_conflict="story_id,user_id").execute()
    except Exception:
        pass


def _after_save_history_v_work(project_id, user_id, persona_role):
    """Sau khi lưu tin nhắn V Work: tăng counter, nếu >= 30 thì chạy crystallize (sẽ reset về 0)."""
    if not project_id or not user_id:
        return
    _increment_crystallize_count(project_id, user_id)
    if _get_crystallize_count(project_id, user_id) >= 30:
        threading.Thread(
            target=_auto_crystallize_background,
            args=(project_id, user_id, persona_role),
            daemon=True,
        ).start()


# --- V Home: lưu/load theo topic (không dùng chat_history) ---
V_HOME_CONTEXT_MESSAGES = 10


def _v_home_get_current_topic_start(user_id):
    """Lấy topic_start_at hiện tại của user. Nếu chưa có thì tạo mới (now). Trả về chuỗi ISO."""
    if not user_id:
        return datetime.utcnow().isoformat()
    try:
        services = init_services()
        if not services:
            return datetime.utcnow().isoformat()
        r = services["supabase"].table("v_home_current_topic").select("topic_start_at").eq(
            "user_id", str(user_id)
        ).limit(1).execute()
        if r.data and len(r.data) > 0:
            raw = r.data[0].get("topic_start_at")
            if raw is not None:
                return raw if isinstance(raw, str) else getattr(raw, "isoformat", lambda: str(raw))()
        now = datetime.utcnow().isoformat()
        services["supabase"].table("v_home_current_topic").upsert(
            {"user_id": str(user_id), "topic_start_at": now},
            on_conflict="user_id",
        ).execute()
        return now
    except Exception:
        return datetime.utcnow().isoformat()


def _v_home_load_messages(user_id):
    """Lấy tin nhắn thuộc topic hiện tại (để hiển thị và làm context)."""
    if not user_id:
        return []
    try:
        services = init_services()
        if not services:
            return []
        topic_start = _v_home_get_current_topic_start(user_id)
        r = (
            services["supabase"]
            .table("v_home_messages")
            .select("id, role, content, created_at, topic_start_at")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        out = []
        for m in (r.data or []):
            ts = m.get("topic_start_at")
            ts_str = ts if isinstance(ts, str) else (getattr(ts, "isoformat", lambda: str(ts))() if ts else "")
            if ts_str == topic_start:
                out.append(m)
        out.reverse()
        return out
    except Exception:
        return []


def _v_home_reset_topic(user_id):
    """Reset topic: đặt topic_start_at = now. Tin nhắn sau chỉ thuộc topic mới."""
    if not user_id:
        return
    try:
        services = init_services()
        if not services:
            return
        now = datetime.utcnow().isoformat()
        services["supabase"].table("v_home_current_topic").upsert(
            {"user_id": str(user_id), "topic_start_at": now},
            on_conflict="user_id",
        ).execute()
    except Exception:
        pass


def _v_home_save_message(user_id, role, content, topic_start_at):
    """Lưu 1 tin nhắn V Home (không ghi chat_history)."""
    if not user_id:
        return
    try:
        services = init_services()
        if not services:
            return
        services["supabase"].table("v_home_messages").insert({
            "user_id": str(user_id),
            "role": role,
            "content": content,
            "created_at": datetime.utcnow().isoformat(),
            "topic_start_at": topic_start_at,
        }).execute()
    except Exception:
        pass


def _auto_crystallize_background(project_id, user_id, persona_role):
    """Chạy ngầm: crystallize 25 tin (30 - 5) và lưu vào Bible [CHAT] (ngày-stt). Reset counter v7.1 về 0."""
    try:
        services = init_services()
        if not services:
            return
        supabase = services["supabase"]
        q = supabase.table("chat_history").select("id, role, content, created_at").eq("story_id", project_id)
        if user_id:
            q = q.eq("user_id", str(user_id))
        r = q.order("created_at", desc=True).limit(35).execute()
        data = list(r.data)[::-1] if r.data else []
        if len(data) < 25:
            return
        to_crystallize = data[:-5]
        chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in to_crystallize])
        summary = RuleMiningSystem.crystallize_session(to_crystallize, persona_role)
        if not summary or summary == "NO_INFO":
            return
        vec = AIService.get_embedding(summary)
        if not vec:
            return
        today = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            log_r = supabase.table("chat_crystallize_log").select("serial_in_day").eq(
                "story_id", project_id
            ).eq("user_id", str(user_id) or "").eq("crystallize_date", today).execute()
            serial = len(log_r.data) + 1 if log_r.data else 1
        except Exception:
            serial = 1
        entity_name = f"[CHAT] {today} chat-{serial}"
        payload = {
            "story_id": project_id,
            "entity_name": entity_name,
            "description": summary,
            "embedding": vec,
            "source_chapter": 0,
        }
        ins = supabase.table("story_bible").insert(payload).execute()
        bible_id = ins.data[0].get("id") if ins.data else None
        try:
            supabase.table("chat_crystallize_log").insert({
                "story_id": project_id,
                "user_id": str(user_id) if user_id else None,
                "crystallize_date": today,
                "serial_in_day": serial,
                "message_count": len(to_crystallize),
                "bible_entry_id": bible_id,
            }).execute()
        except Exception:
            pass
        _reset_crystallize_count(project_id, user_id)
        try:
            from ai_engine import suggest_relations
            suggestions = suggest_relations(summary, project_id)
            for s in (suggestions or []):
                if s.get("kind") == "relation":
                    try:
                        supabase.table("entity_relations").insert({
                            "source_entity_id": s["source_entity_id"],
                            "target_entity_id": s["target_entity_id"],
                            "relation_type": s.get("relation_type", "liên quan"),
                            "description": s.get("description", ""),
                            "story_id": project_id,
                        }).execute()
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception as e:
        print(f"auto_crystallize_background error: {e}")


def render_chat_tab(project_id, persona, chat_mode=None):
    """Tab Chat. chat_mode: 'v_work' (dự án, persona, router, crystallize) hoặc 'v_home' (chat tự do, không context dự án)."""
    if chat_mode is None:
        chat_mode = "v_work"
    is_v_home = chat_mode == "v_home"

    st.header("🏠 V Home" if is_v_home else "🔧 V Work")

    col_chat, col_memory = st.columns([3, 1])

    user = st.session_state.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_email = getattr(user, "email", None) if user else None
    can_write = bool(
        project_id
        and user_id
        and check_permission(str(user_id), user_email or "", project_id, "write")
    )
    can_request = bool(
        project_id
        and user_id
        and check_permission(str(user_id), user_email or "", project_id, "request_write")
    )

    with col_memory:
        st.write("### 🧠 Memory & Settings")
        if is_v_home:
            active_persona = {"icon": "🏠", "role": "Assistant", "core_instruction": "Bạn là trợ lý thân thiện. Trả lời ngắn gọn, hữu ích. Ngôn ngữ: ưu tiên Tiếng Việt.", "system_prompt": "", "max_tokens": 4000}
            st.session_state['enable_history'] = False
            st.caption("Chat tự do — không lưu vào DB dự án. Context = 10 tin cuối của topic.")
            if st.button("🔄 Reset topic", use_container_width=True, key=f"chat_btn_reset_topic_{chat_mode}", help="Bắt đầu topic mới: từ giờ chỉ đưa tin nhắn sau thời điểm này vào context."):
                _v_home_reset_topic(user_id)
                st.toast("Đã bắt đầu topic mới.")
                st.rerun()
        else:
            available = PersonaSystem.get_available_personas()
            default_key = st.session_state.get("persona", "Writer")
            idx = available.index(default_key) if default_key in available else 0
            selected_persona_key = st.selectbox(
                "Persona trả lời",
                available,
                index=idx,
                key=f"chat_persona_key_{chat_mode}",
                help="Chọn persona để AI trả lời theo phong cách này."
            )
            active_persona = PersonaSystem.get_persona(selected_persona_key)
            st.session_state['enable_history'] = True

            if st.button("🧹 Clear Screen", use_container_width=True, key=f"chat_btn_clear_{chat_mode}"):
                st.session_state['chat_cutoff'] = datetime.utcnow().isoformat()
                st.rerun()

            if st.button("🔄 Show All", use_container_width=True, key=f"chat_btn_show_all_{chat_mode}"):
                st.session_state['chat_cutoff'] = "1970-01-01"
                st.rerun()

        if not is_v_home:
            st.session_state['strict_mode'] = st.toggle(
                "🚫 Strict Mode",
                value=st.session_state.get('strict_mode', False),
                help="ON: AI only answers based on found data. No fabrication. (Temp = 0)",
                key=f"chat_toggle_strict_{chat_mode}",
            )
            st.session_state['use_v7_planner'] = st.toggle(
                "📐 V7 Planner",
                value=st.session_state.get('use_v7_planner', False),
                help="V sẽ tư duy để tìm câu trả lời tốt nhất.",
                key=f"chat_toggle_v7_{chat_mode}",
            )
            st.divider()
            st.write("### 🕰️ Context cho Router / Planner")
            st.session_state["history_depth"] = st.slider(
                "Số tin nhắn cũ đưa vào Router & V7 Planner",
                min_value=0,
                max_value=50,
                value=st.session_state.get("history_depth", 5),
                step=1,
                help="Bao nhiêu tin gần nhất được đưa vào Router và V7 Planner để chọn intent và lên kế hoạch. Trả lời cuối dựa trên context từ Bible/chương đã thu thập, không nhồi thêm lịch sử chat.",
                key=f"chat_history_depth_{chat_mode}",
            )
            crystallize_count = _get_crystallize_count(project_id, user_id) if project_id and user_id else 0
            st.caption(f"💎 Crystallize: **{crystallize_count} / 30** tin (sau 30 → tóm tắt & lưu Bible [CHAT], xem tại **Knowledge > Bible** hoặc **Memory**).")
        else:
            st.session_state["history_depth"] = st.session_state.get("history_depth", 5)

    @st.fragment
    def _chat_messages_fragment():
        if is_v_home:
            visible_msgs = _v_home_load_messages(user_id)
            for m in visible_msgs:
                role_icon = active_persona["icon"] if m["role"] == "model" else None
                with st.chat_message(m["role"], avatar=role_icon):
                    st.markdown(m.get("content", ""))
        else:
            try:
                services = init_services()
                supabase = services["supabase"]
                q = (
                    supabase.table("chat_history")
                    .select("*")
                    .eq("story_id", project_id)
                )
                if user_id:
                    q = q.eq("user_id", str(user_id))
                msgs_data = (
                    q.order("created_at", desc=True)
                    .limit(50)
                    .execute()
                )
                msgs = msgs_data.data[::-1] if msgs_data.data else []
                visible_msgs = [m for m in msgs if m["created_at"] > st.session_state.get("chat_cutoff", "1970-01-01")]
                for m in visible_msgs:
                    role_icon = active_persona["icon"] if m["role"] == "model" else None
                    with st.chat_message(m["role"], avatar=role_icon):
                        st.markdown(m["content"])
                        if m.get("metadata"):
                            with st.expander("📊 Details"):
                                st.json(m["metadata"], expanded=False)
            except Exception as e:
                st.error(f"Error loading history: {e}")
        history_depth = st.session_state.get("history_depth", 5)
        chat_input_key = "chat_input_v_home" if is_v_home else "chat_input_main"
        if prompt := st.chat_input(f"Ask {active_persona['icon']} AI Assistant...", key=chat_input_key):
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.spinner("Thinking..."):
                now_timestamp = datetime.utcnow().isoformat()
                v7_handled = False
                router_out = None
                free_chat_mode = is_v_home or st.session_state.get('free_chat_mode', False)

                # Số tin đưa vào Router/Planner theo slider (0 = không dùng lịch sử).
                depth = history_depth if not is_v_home else 0
                if depth > 0 and visible_msgs:
                    recent_history_text = "\n".join([
                        f"{m['role']}: {m['content']}"
                        for m in visible_msgs[-depth:]
                    ])
                else:
                    recent_history_text = "" if not is_v_home else "\n".join([
                        f"{m.get('role', 'user')}: {m.get('content', '')}"
                        for m in visible_msgs[-V_HOME_CONTEXT_MESSAGES:]
                    ])

                if free_chat_mode:
                    router_out = {"intent": "chat_casual", "target_files": [], "target_bible_entities": [], "rewritten_query": prompt, "chapter_range": None, "chapter_range_mode": None, "chapter_range_count": 5}
                    debug_notes = ["Intent: chat_casual", "🌐 Chat tự do"]
                else:
                    debug_notes = []
                    semantic_match = None
                    try:
                        svc = init_services()
                        if svc:
                            r = svc["supabase"].table("settings").select("value").eq("key", "semantic_intent_no_use").execute()
                            no_use = r.data and r.data[0] and int(r.data[0].get("value", 0)) == 1
                            if not no_use:
                                semantic_match = check_semantic_intent(prompt, project_id)
                    except Exception:
                        semantic_match = check_semantic_intent(prompt, project_id)
                    if semantic_match:
                        router_out = {"intent": "chat_casual", "target_files": [], "target_bible_entities": [], "rewritten_query": prompt, "chapter_range": None, "chapter_range_mode": None, "chapter_range_count": 5}
                        if semantic_match.get("related_data"):
                            router_out["_semantic_data"] = semantic_match["related_data"]
                        debug_notes.append(f"🎯 Semantic match {int(semantic_match.get('similarity',0)*100)}%")
                    elif not is_v_home and st.session_state.get('use_v7_planner', False):
                        plan_result = SmartAIRouter.get_plan_v7(prompt, recent_history_text, project_id)
                        plan = plan_result.get("plan") or []
                        first_intent = (plan[0].get("intent", "") if plan else "") or "chat_casual"
                        if first_intent == "ask_user_clarification":
                            clarification_question = (plan[0].get("args") or {}).get("clarification_question", "") or "Bạn có thể nói rõ hơn câu hỏi hoặc chủ đề bạn muốn hỏi?"
                            with st.chat_message("assistant", avatar=active_persona['icon']):
                                st.caption("🧠 V7 Planner — Cần làm rõ")
                                st.info(f"**Để trả lời chính xác, tôi cần bạn làm rõ:**\n\n{clarification_question}")
                                st.text_input("Bạn có thể gõ lại hoặc bổ sung tại đây (gửi bằng ô chat phía dưới):", key="clarification_followup", placeholder="Ví dụ: Tôi muốn hỏi về nhân vật A trong chương 3")
                            if st.session_state.get('enable_history', True):
                                try:
                                    services = init_services()
                                    supabase = services['supabase']
                                    supabase.table("chat_history").insert([
                                        {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "user", "content": prompt, "created_at": now_timestamp, "metadata": {"intent": first_intent, "v7_plan": plan_result}},
                                        {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "model", "content": f"[Cần làm rõ] {clarification_question}", "created_at": now_timestamp, "metadata": {"intent": first_intent}},
                                    ]).execute()
                                    if not is_v_home:
                                        _after_save_history_v_work(project_id, user_id, active_persona.get("role", ""))
                                except Exception:
                                    pass
                            v7_handled = True
                        else:
                            retries_used = 0
                            status_label = "V7 Multi-step"
                            with st.status(f"📐 {status_label}", expanded=True) as status:
                                st.write("🧠 Planning...")
                                if plan_result.get("analysis"):
                                    st.caption(plan_result["analysis"][:500] + ("..." if len(plan_result.get("analysis", "")) > 500 else ""))
                                cumulative_context = ""
                                sources = []
                                step_results = []
                                replan_events = []
                                try:
                                    st.write(f"⚙️ Executing {len(plan)} step(s)...")
                                    cumulative_context, sources, step_results, replan_events = execute_plan(
                                        plan,
                                        project_id,
                                        active_persona,
                                        prompt,
                                        st.session_state.get('strict_mode', False),
                                        st.session_state.get('current_arc_id'),
                                        dict(st.session_state),
                                        free_chat_mode=False,
                                        max_context_tokens=Config.CONTEXT_SIZE_TOKENS.get(st.session_state.get("context_size", "medium")),
                                        run_numerical_executor=True,
                                    )
                                    if replan_events:
                                        for ev in replan_events:
                                            st.caption(f"🔄 Re-plan (sau step {ev.get('step_id')}): {ev.get('reason', '')[:80]}... → {ev.get('action', '')}")
                                    st.write("📝 Generating draft...")
                                    system_content = (active_persona.get("system_prompt") or "") + "\n\n--- CONTEXT (Các bước đã thực thi) ---\n" + cumulative_context
                                    user_content = prompt
                                    draft_resp = AIService.call_openrouter(
                                        messages=[
                                            {"role": "system", "content": system_content},
                                            {"role": "user", "content": user_content},
                                        ],
                                        model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                                        temperature=0.0 if st.session_state.get('strict_mode') else 0.7,
                                        max_tokens=4096,
                                        stream=False,
                                    )
                                    draft_response = (draft_resp.choices[0].message.content or "").strip()
                                    st.write("🛡️ Verifying...")
                                    verification_required = plan_result.get("verification_required", True)

                                    def _llm_generate(system_content: str, user_content: str) -> str:
                                        r = AIService.call_openrouter(
                                            messages=[
                                                {"role": "system", "content": system_content},
                                                {"role": "user", "content": user_content},
                                            ],
                                            model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                                            temperature=0.0,
                                            max_tokens=4096,
                                            stream=False,
                                        )
                                        return (r.choices[0].message.content or "").strip()

                                    plan_for_verifier = [{"intent": r.get("intent", "chat_casual")} for r in step_results]
                                    final_response, retries_used = run_verification_loop(
                                        draft_response,
                                        cumulative_context,
                                        plan_for_verifier,
                                        step_results,
                                        _llm_generate,
                                        verification_required=verification_required,
                                    )
                                    if retries_used > 0:
                                        st.warning("⚠️ Detecting error, auto-correcting...")
                                    status.update(label=f"✅ {status_label} — Done", state="complete")
                                except Exception as ex:
                                    status.update(label=f"❌ {status_label} — Error", state="error")
                                    final_response = f"Lỗi khi chạy V7: {ex}"
                                    import traceback
                                    st.exception(ex)

                            with st.chat_message("assistant", avatar=active_persona['icon']):
                                # Stream hiển thị câu trả lời cuối (typewriter effect)
                                _placeholder = st.empty()
                                import time
                                _chunk = 25
                                for _i in range(0, len(final_response), _chunk):
                                    _placeholder.markdown(final_response[:_i + _chunk] + "▌")
                                    time.sleep(0.02)
                                _placeholder.markdown(final_response)
                                with st.expander("📊 V7 Details"):
                                    st.caption(f"Steps: {len(step_results)} | Verification retries: {retries_used}")
                                    if replan_events:
                                        st.caption("🔄 Re-plan: " + "; ".join([f"Step {e.get('step_id')} → {e.get('action')}" for e in replan_events]))
                                    st.json({
                                        "plan": plan_result.get("plan"),
                                        "verification_required": plan_result.get("verification_required"),
                                        "replan_events": replan_events,
                                    }, expanded=False)

                            if st.session_state.get('enable_history', True):
                                try:
                                    services = init_services()
                                    supabase = services['supabase']
                                    supabase.table("chat_history").insert([
                                        {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "user", "content": prompt, "created_at": now_timestamp, "metadata": {"v7": True, "plan": plan_result.get("plan")}},
                                        {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "model", "content": final_response, "created_at": now_timestamp, "metadata": {"v7": True, "verification_required": plan_result.get("verification_required")}},
                                    ]).execute()
                                    if not is_v_home:
                                        _after_save_history_v_work(project_id, user_id, active_persona.get("role", ""))
                                except Exception:
                                    pass
                            v7_handled = True
                    else:
                        router_out = SmartAIRouter.ai_router_pro_v2(prompt, recent_history_text, project_id)
                    if router_out is not None:
                        debug_notes = [f"Intent: {router_out.get('intent', 'chat_casual')}"] + debug_notes

                if not v7_handled:
                    intent = router_out.get('intent', 'chat_casual')
                    targets = router_out.get('target_files', [])
                    rewritten_query = router_out.get('rewritten_query', prompt)

                    # ask_user_clarification: dừng lại, hiện popup hỏi user thay vì gọi LLM
                    if intent == "ask_user_clarification":
                        clarification_question = router_out.get("clarification_question", "") or "Bạn có thể nói rõ hơn câu hỏi hoặc chủ đề bạn muốn hỏi?"
                        with st.chat_message("assistant", avatar=active_persona['icon']):
                            st.caption("🧠 Intent: ask_user_clarification — Cần làm rõ")
                            st.info(f"**Để trả lời chính xác, tôi cần bạn làm rõ:**\n\n{clarification_question}")
                            st.text_input("Bạn có thể gõ lại hoặc bổ sung tại đây (gửi bằng ô chat phía dưới):", key="clarification_followup", placeholder="Ví dụ: Tôi muốn hỏi về nhân vật A trong chương 3")
                        if st.session_state.get('enable_history', True):
                            try:
                                services = init_services()
                                supabase = services['supabase']
                                supabase.table("chat_history").insert([
                                    {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "user", "content": prompt, "created_at": now_timestamp, "metadata": {"intent": intent, "router_output": router_out}},
                                    {"story_id": project_id, "user_id": str(user_id) if user_id else None, "role": "model", "content": f"[Cần làm rõ] {clarification_question}", "created_at": now_timestamp, "metadata": {"intent": intent}},
                                ]).execute()
                                if not is_v_home:
                                    _after_save_history_v_work(project_id, user_id, active_persona.get("role", ""))
                            except Exception:
                                pass
                    else:
                        max_context_tokens = Config.CONTEXT_SIZE_TOKENS.get(st.session_state.get("context_size", "medium"))
                        exec_result = None
                        if intent == "numerical_calculation" and not free_chat_mode:
                            context_text, sources, context_tokens = ContextManager.build_context(
                                router_out, project_id, active_persona,
                                st.session_state.get('strict_mode', False),
                                current_arc_id=st.session_state.get('current_arc_id'),
                                session_state=dict(st.session_state),
                                max_context_tokens=max_context_tokens,
                            )
                            code_prompt = f"""User hỏi: "{prompt}"
Context có sẵn:
{context_text[:6000]}

Nhiệm vụ: Tạo code Python (pandas/numpy) để trả lời. Gán kết quả cuối vào biến result.
Chỉ trả về code trong block ```python ... ```, không giải thích."""
                            try:
                                code_resp = AIService.call_openrouter(
                                    messages=[{"role": "user", "content": code_prompt}],
                                    model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                                    temperature=0.1,
                                    max_tokens=2000,
                                )
                                raw = (code_resp.choices[0].message.content or "").strip()
                                import re
                                m = re.search(r'```(?:python)?\s*(.*?)```', raw, re.DOTALL)
                                code = m.group(1).strip() if m else raw
                                if code:
                                    val, err = PythonExecutor.execute(code, result_variable="result")
                                    if err:
                                        exec_result = f"(Executor lỗi: {err})"
                                    else:
                                        exec_result = str(val) if val is not None else "null"
                                        debug_notes.append("🧮 Python Executor OK")
                            except Exception as ex:
                                exec_result = f"(Lỗi: {ex})"
                            if exec_result:
                                context_text += f"\n\n--- KẾT QUẢ TÍNH TOÁN (Python Executor) ---\n{exec_result}"

                        if is_v_home:
                            context_text = "\n".join([
                                f"{m.get('role', 'user')}: {m.get('content', '')}"
                                for m in visible_msgs[-V_HOME_CONTEXT_MESSAGES:]
                            ])
                            sources = []
                        elif exec_result is None:
                            context_text, sources, context_tokens = ContextManager.build_context(
                                router_out,
                                project_id,
                                active_persona,
                                st.session_state.get('strict_mode', False),
                                current_arc_id=st.session_state.get('current_arc_id'),
                                session_state=dict(st.session_state),
                                free_chat_mode=free_chat_mode,
                                max_context_tokens=max_context_tokens,
                            )
                            if not free_chat_mode and router_out.get("_semantic_data"):
                                context_text = f"[SEMANTIC INTENT - Data]\n{router_out['_semantic_data']}\n\n{context_text}"
                                sources.append("🎯 Semantic Intent")

                        debug_notes.extend(sources)

                        final_prompt = f"CONTEXT:\n{context_text}\n\nUSER QUERY: {prompt}"

                        run_instruction = active_persona['core_instruction']
                        run_temperature = st.session_state.get('temperature', 0.7)

                        if st.session_state.get('strict_mode') and not free_chat_mode:
                            run_temperature = 0.0

                        messages = []
                        system_message = f"""{run_instruction}

            THÔNG TIN NGỮ CẢNH (CONTEXT):
            {context_text}

            HƯỚNG DẪN:
            - Trả lời dựa trên Context nếu có.
            - Hữu ích, súc tích, đi thẳng vào vấn đề.
            - Chế độ hiện tại: {active_persona['role']}
            - Ngôn ngữ: Ưu tiên Tiếng Việt (trừ khi User yêu cầu khác hoặc code).
            """

                        messages.append({"role": "system", "content": system_message})

                        # Trả lời chỉ dựa trên context đã thu thập (Bible, chương, timeline...); không nhồi lịch sử chat vào LLM.
                        messages.append({"role": "user", "content": prompt})

                        try:
                            model = st.session_state.get('selected_model', Config.DEFAULT_MODEL)

                            response = AIService.call_openrouter(
                                messages=messages,
                                model=model,
                                temperature=run_temperature,
                                max_tokens=active_persona.get('max_tokens', 4000),
                                stream=True
                            )

                            with st.chat_message("assistant", avatar=active_persona['icon']):
                                if debug_notes:
                                    st.caption(f"🧠 {', '.join(debug_notes)}")
                                if st.session_state.get('strict_mode'):
                                    st.caption("🔒 Strict Mode: ON")

                                full_response_text = ""
                                placeholder = st.empty()

                                for chunk in response:
                                    if chunk.choices[0].delta.content is not None:
                                        content = chunk.choices[0].delta.content
                                        full_response_text += content
                                        placeholder.markdown(full_response_text + "▌")

                                placeholder.markdown(full_response_text)

                            input_tokens = AIService.estimate_tokens(system_message + prompt)
                            output_tokens = AIService.estimate_tokens(full_response_text)
                            cost = AIService.calculate_cost(input_tokens, output_tokens, model)

                            if 'user' in st.session_state:
                                CostManager.update_budget(st.session_state.user.id, cost)

                            if full_response_text:
                                if is_v_home:
                                    topic_start = _v_home_get_current_topic_start(user_id)
                                    _v_home_save_message(user_id, "user", prompt, topic_start)
                                    _v_home_save_message(user_id, "model", full_response_text, topic_start)
                                elif st.session_state.get('enable_history', True):
                                    services = init_services()
                                    supabase = services['supabase']

                                    supabase.table("chat_history").insert([
                                        {
                                            "story_id": project_id,
                                            "user_id": str(user_id) if user_id else None,
                                            "role": "user",
                                            "content": prompt,
                                            "created_at": now_timestamp,
                                            "metadata": {
                                                "intent": intent,
                                                "router_output": router_out,
                                                "model": model,
                                                "temperature": run_temperature
                                            }
                                        },
                                        {
                                            "story_id": project_id,
                                            "user_id": str(user_id) if user_id else None,
                                            "role": "model",
                                            "content": full_response_text,
                                            "created_at": now_timestamp,
                                            "metadata": {
                                                "model": model,
                                                "cost": f"${cost:.6f}",
                                                "tokens": input_tokens + output_tokens
                                            }
                                        }
                                    ]).execute()

                                # update_data: lưu pending xác nhận trước khi ghi Bible/file (chỉ V Work)
                                if not is_v_home and intent == "update_data" and can_write:
                                    st.session_state["pending_update_confirm"] = {
                                        "project_id": project_id,
                                        "prompt": prompt,
                                        "response": full_response_text,
                                        "update_summary": router_out.get("update_summary", ""),
                                        "user_id": user_id,
                                    }

                                # V Work: tăng counter crystallize và trigger nếu >= 30 (reset về 0 sau crystallize)
                                if not is_v_home and can_write and user_id:
                                    _after_save_history_v_work(project_id, user_id, active_persona.get("role", ""))

                                # Rule mining (chỉ V Work)
                                if not is_v_home and can_write:
                                    new_rule = RuleMiningSystem.extract_rule_raw(prompt, full_response_text)
                                    if new_rule:
                                        st.session_state['pending_new_rule'] = new_rule
                                    # Offer add to Semantic Intent (nếu bật auto-create và không phải chat phiếm)
                                    try:
                                        r = init_services()["supabase"].table("settings").select("value").eq("key", "semantic_intent_no_auto_create").execute()
                                        no_auto = r.data and r.data[0] and int(r.data[0].get("value", 0)) == 1
                                    except Exception:
                                        no_auto = False
                                    if not no_auto and intent != "chat_casual":
                                        st.session_state["pending_semantic_add"] = {"prompt": prompt, "response": full_response_text, "context": context_text, "intent": intent}

                            elif not st.session_state.get('enable_history', True):
                                st.caption("👻 Anonymous mode: History not saved & Rule mining disabled.")

                        except Exception as e:
                            st.error(f"Generation error: {str(e)}")

    with col_chat:
        _chat_messages_fragment()

    # Offer add to Semantic Intent (chỉ V Work)
    if not is_v_home and "pending_semantic_add" in st.session_state and can_write:
        p = st.session_state["pending_semantic_add"]
        with st.expander("🎯 Thêm vào Semantic Intent?", expanded=True):
            st.caption("Câu hỏi vừa rồi không phải chat phiếm. Thêm làm mẫu để lần sau khớp nhanh?")
            st.write("**Câu hỏi:**", p.get("prompt", "")[:100])
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Thêm vào Semantic", key=f"chat_semantic_add_btn_{chat_mode}"):
                    def _add_semantic():
                        try:
                            svc = init_services()
                            if not svc:
                                return
                            sb = svc["supabase"]
                            vec = AIService.get_embedding(p.get("prompt", ""))
                            ctx = p.get("context", "") or ""
                            resp = p.get("response", "") or ""
                            related_data = (ctx.rstrip() + "\n\n--- Câu trả lời ---\n" + resp) if ctx else resp
                            payload = {"story_id": project_id, "question_sample": p.get("prompt", ""), "intent": "chat_casual", "related_data": related_data}
                            if vec:
                                payload["embedding"] = vec
                            try:
                                sb.table("semantic_intent").insert(payload).execute()
                            except Exception:
                                payload.pop("embedding", None)
                                sb.table("semantic_intent").insert(payload).execute()
                        except Exception:
                            pass
                    threading.Thread(target=_add_semantic, daemon=True).start()
                    del st.session_state["pending_semantic_add"]
                    st.toast("Đã thêm vào Semantic Intent (chạy ngầm).")
                    st.rerun()
            with col_b:
                if st.button("❌ Bỏ qua", key=f"chat_semantic_skip_btn_{chat_mode}"):
                    del st.session_state["pending_semantic_add"]
                    st.rerun()

    # update_data: Xác nhận cuối cùng trước khi ghi Bible / cập nhật (chỉ V Work)
    if not is_v_home and "pending_update_confirm" in st.session_state and can_write:
        pu = st.session_state["pending_update_confirm"]
        if pu.get("project_id") == project_id:
            with st.expander("✏️ Xác nhận thực hiện cập nhật?", expanded=True):
                st.caption("Bạn đã yêu cầu ghi nhớ / cập nhật dữ liệu. Chỉ thực hiện khi bạn xác nhận.")
                st.write("**Tóm tắt:**", pu.get("update_summary", "") or "(Theo nội dung AI trả lời)")
                st.write("**Nội dung sẽ ghi:**", (pu.get("response", "") or "")[:500])
                col_ok, col_no = st.columns(2)
                with col_ok:
                    if st.button("✅ Xác nhận thực hiện", key=f"update_confirm_ok_{chat_mode}"):
                        try:
                            services = init_services()
                            supabase = services["supabase"]
                            content_to_save = (pu.get("response", "") or pu.get("update_summary", "") or "").strip()
                            if content_to_save:
                                vec = AIService.get_embedding(content_to_save[:8000])
                                payload = {
                                    "story_id": project_id,
                                    "entity_name": f"[RULE] {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                    "description": content_to_save,
                                    "source_chapter": 0,
                                }
                                if vec:
                                    payload["embedding"] = vec
                                supabase.table("story_bible").insert(payload).execute()
                                st.toast("Đã ghi nhớ / cập nhật vào Bible.")
                            del st.session_state["pending_update_confirm"]
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi khi ghi: {e}")
                with col_no:
                    if st.button("❌ Hủy", key=f"update_confirm_no_{chat_mode}"):
                        del st.session_state["pending_update_confirm"]
                        st.rerun()

    # Rule Mining UI (chỉ V Work; V Home không nhận diện / add rule)
    if not is_v_home and 'pending_new_rule' in st.session_state and can_write:
        rule_content = st.session_state['pending_new_rule']

        with st.expander("🧐 AI discovered a new Rule!", expanded=True):
            st.caption("Rule lưu vào **Knowledge > Bible** (prefix [RULE]).")
            st.write(f"**Content:** {rule_content}")

            if st.session_state.get('rule_analysis') is None:
                with st.spinner("Checking for conflicts..."):
                    st.session_state['rule_analysis'] = RuleMiningSystem.analyze_rule_conflict(rule_content, project_id)

            analysis = st.session_state['rule_analysis']
            if analysis:
                st.info(f"AI Assessment: **{analysis.get('status', 'UNKNOWN')}** - {analysis.get('reason', 'N/A')}")
                if analysis['status'] == "CONFLICT":
                    st.warning(f"⚠️ Conflict with: {analysis['existing_rule_summary']}")
                elif analysis['status'] == "MERGE":
                    st.info(f"💡 Merge suggestion: {analysis['merged_content']}")
            else:
                st.error("Could not analyze rule conflict.")

            c1, c2, c3 = st.columns(3)

            if c1.button("✅ Save/Merge Rule", key=f"rule_save_btn_{chat_mode}"):
                final_content = analysis.get('merged_content') if analysis and analysis['status'] == "MERGE" else rule_content
                vec = AIService.get_embedding(final_content)

                services = init_services()
                supabase = services['supabase']

                payload = {
                    "entity_name": f"[RULE] {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "description": final_content,
                    "embedding": vec,
                    "source_chapter": 0,
                }
                try:
                    if can_write:
                        payload["story_id"] = project_id
                        supabase.table("story_bible").insert(payload).execute()
                        st.toast("Learned new rule!")
                    elif can_request:
                        pid = submit_pending_change(
                            story_id=project_id,
                            requested_by_email=user_email or "",
                            table_name="story_bible",
                            target_key={},
                            old_data={},
                            new_data=payload,
                        )
                        if pid:
                            st.toast("Đã gửi yêu cầu thêm RULE cho Owner duyệt.", icon="📤")
                        else:
                            st.error("Không gửi được yêu cầu (kiểm tra bảng pending_changes).")
                    else:
                        st.warning("Bạn không có quyền lưu hoặc gửi yêu cầu Rule.")
                except Exception as e:
                    st.error(f"Lỗi khi lưu RULE: {e}")

                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()

            if c2.button("✏️ Edit then Save", key=f"rule_edit_btn_{chat_mode}"):
                st.session_state['edit_rule_manual'] = rule_content

            if c3.button("❌ Ignore", key=f"rule_ignore_btn_{chat_mode}"):
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()

        if not is_v_home and 'edit_rule_manual' in st.session_state and can_write:
            edited = st.text_input("Edit rule:", value=st.session_state['edit_rule_manual'], key=f"edit_rule_input_{chat_mode}")
            if st.button("Save edited version", key=f"rule_save_edited_btn_{chat_mode}"):
                vec = AIService.get_embedding(edited)

                services = init_services()
                supabase = services['supabase']

                supabase.table("story_bible").insert({
                    "story_id": project_id,
                    "entity_name": "[RULE] Manual",
                    "description": edited,
                    "embedding": vec,
                    "source_chapter": 0
                }).execute()

                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                del st.session_state['edit_rule_manual']
                st.rerun()
