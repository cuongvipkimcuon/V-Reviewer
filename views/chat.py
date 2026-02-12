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
from persona import PersonaSystem
from utils.auth_manager import check_permission, submit_pending_change
from utils.python_executor import PythonExecutor


def _auto_crystallize_background(project_id, user_id, persona_role):
    """Chạy ngầm: crystallize 25 tin (30 - 5) và lưu vào Bible [CHAT] (ngày-stt)."""
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


def render_chat_tab(project_id, persona):
    """Tab Chat - AI Conversation với tính năng nâng cao. Persona có thể chọn lại trong tab."""
    st.header("💬 Smart AI Chat")

    col_chat, col_memory = st.columns([3, 1])

    # Thông tin user & quyền: dùng cho Rule Mining, Crystallize, quyền ghi/chờ duyệt
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
        available = PersonaSystem.get_available_personas()
        default_key = st.session_state.get("persona", "Writer")
        idx = available.index(default_key) if default_key in available else 0
        selected_persona_key = st.selectbox(
            "Persona trả lời",
            available,
            index=idx,
            key="chat_persona_key",
            help="Chọn persona để AI trả lời theo phong cách này."
        )
        active_persona = PersonaSystem.get_persona(selected_persona_key)

        if st.button("🧹 Clear Screen", use_container_width=True):
            st.session_state['chat_cutoff'] = datetime.utcnow().isoformat()
            st.rerun()

        if st.button("🔄 Show All", use_container_width=True):
            st.session_state['chat_cutoff'] = "1970-01-01"
            st.rerun()

        st.session_state['enable_history'] = st.toggle(
            "💾 Save Chat History",
            value=True,
            help="Turn off for anonymous chat (Not saved to DB, AI doesn't learn)"
        )

        st.session_state['strict_mode'] = st.toggle(
            "🚫 Strict Mode",
            value=False,
            help="ON: AI only answers based on found data. No fabrication. (Temp = 0)"
        )
        st.session_state['router_ignore_history'] = st.toggle(
            "⚡️ Router Ignore History",
            value=False,
            help="Bật cái này để Router chỉ phân tích câu hiện tại, không bị nhiễu bởi chat cũ."
        )
        st.divider()
        st.write("### 🕰️ Context Depth")
        st.session_state["history_depth"] = st.slider(
            "Chat History Limit",
            min_value=0,
            max_value=30,
            value=st.session_state.get("history_depth", 5),
            step=1,
            help="Số lượng tin nhắn cũ gửi kèm. Càng cao càng nhớ dai nhưng tốn tiền hơn.",
            key="chat_history_depth",
        )

        st.caption("💎 Auto Crystallize: Mỗi 30 tin nhắn, hệ thống tự tóm tắt & lưu Bible [CHAT] (ngày-stt).")

    @st.fragment
    def _chat_messages_fragment():
        try:
            services = init_services()
            supabase = services["supabase"]
            # Chat riêng tư: chỉ lấy lịch sử chat của chính user hiện tại
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
        if prompt := st.chat_input(f"Ask {active_persona['icon']} AI Assistant...", key="chat_input_main"):
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.spinner("Thinking..."):
                now_timestamp = datetime.utcnow().isoformat()

                if st.session_state.get('router_ignore_history'):
                    recent_history_text = "NO_HISTORY_AVAILABLE (User requested to ignore context)"
                else:
                    recent_history_text = "\n".join([
                        f"{m['role']}: {m['content']}"
                        for m in visible_msgs[-5:]
                    ])

                # Semantic Intent: nếu khớp >= ngưỡng thì dùng data trực tiếp (không cần intent)
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
                else:
                    router_out = SmartAIRouter.ai_router_pro_v2(prompt, recent_history_text, project_id)
                intent = router_out.get('intent', 'chat_casual')
                targets = router_out.get('target_files', [])
                rewritten_query = router_out.get('rewritten_query', prompt)

                debug_notes = [f"Intent: {intent}"]
                if st.session_state.get('router_ignore_history'):
                    debug_notes.append("⚡️ Router: Ignored History")

                exec_result = None
                if intent == "numerical_calculation":
                    context_text, sources, context_tokens = ContextManager.build_context(
                        router_out, project_id, active_persona,
                        st.session_state.get('strict_mode', False),
                        current_arc_id=st.session_state.get('current_arc_id'),
                        session_state=dict(st.session_state),
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

                if exec_result is None:
                    context_text, sources, context_tokens = ContextManager.build_context(
                        router_out,
                        project_id,
                        active_persona,
                        st.session_state.get('strict_mode', False),
                        current_arc_id=st.session_state.get('current_arc_id'),
                        session_state=dict(st.session_state),
                    )
                    if router_out.get("_semantic_data"):
                        context_text = f"[SEMANTIC INTENT - Data]\n{router_out['_semantic_data']}\n\n{context_text}"
                        sources.append("🎯 Semantic Intent")

                debug_notes.extend(sources)

                final_prompt = f"CONTEXT:\n{context_text}\n\nUSER QUERY: {prompt}"

                run_instruction = active_persona['core_instruction']
                run_temperature = st.session_state.get('temperature', 0.7)

                if st.session_state.get('strict_mode'):
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

                depth = history_depth
                if depth > 0:
                    past_chats = visible_msgs[-depth:]
                else:
                    past_chats = []

                for msg in past_chats:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

                if len(past_chats) > 5:
                    debug_notes.append(f"📚 Memory: Last {len(past_chats)} msgs")

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

                    if full_response_text and st.session_state.get('enable_history', True):
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

                        # Auto crystallize mỗi 30 tin (chạy ngầm)
                        if can_write and user_id:
                            try:
                                count_r = supabase.table("chat_history").select("id", count="exact").eq(
                                    "story_id", project_id
                                ).eq("user_id", str(user_id)).execute()
                                total = getattr(count_r, "count", 0) or len(count_r.data or [])
                                if total >= 30 and total % 30 == 0:
                                    threading.Thread(
                                        target=_auto_crystallize_background,
                                        args=(project_id, user_id, active_persona["role"]),
                                        daemon=True,
                                    ).start()
                            except Exception:
                                pass

                        # Rule mining
                        if can_write:
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

    # Offer add to Semantic Intent
    if "pending_semantic_add" in st.session_state and can_write:
        p = st.session_state["pending_semantic_add"]
        with st.expander("🎯 Thêm vào Semantic Intent?", expanded=True):
            st.caption("Câu hỏi vừa rồi không phải chat phiếm. Thêm làm mẫu để lần sau khớp nhanh?")
            st.write("**Câu hỏi:**", p.get("prompt", "")[:100])
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Thêm vào Semantic"):
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
                if st.button("❌ Bỏ qua"):
                    del st.session_state["pending_semantic_add"]
                    st.rerun()

    # Rule Mining UI
    if 'pending_new_rule' in st.session_state and can_write:
        rule_content = st.session_state['pending_new_rule']

        with st.expander("🧐 AI discovered a new Rule!", expanded=True):
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

            if c1.button("✅ Save/Merge Rule"):
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

            if c2.button("✏️ Edit then Save"):
                st.session_state['edit_rule_manual'] = rule_content

            if c3.button("❌ Ignore"):
                del st.session_state['pending_new_rule']
                del st.session_state['rule_analysis']
                st.rerun()

        if 'edit_rule_manual' in st.session_state and can_write:
            edited = st.text_input("Edit rule:", value=st.session_state['edit_rule_manual'])
            if st.button("Save edited version"):
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
