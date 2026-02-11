from datetime import datetime

import streamlit as st

from config import Config, init_services, CostManager
from ai_engine import (
    AIService,
    ContextManager,
    SmartAIRouter,
    RuleMiningSystem,
)
from persona import PersonaSystem
from utils.auth_manager import check_permission, submit_pending_change


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

        with st.expander("💎 Crystallize Chat"):
            st.caption("Save key points to Bible.")
            crys_option = st.radio("Scope:", ["Last 20 messages", "Entire session"])
            memory_topic = st.text_input("Topic:", placeholder="e.g., Magic System")

            if st.button("✨ Crystallize"):
                try:
                    services = init_services()
                    supabase = services["supabase"]

                    limit = 20 if crys_option == "Last 20 messages" else 100
                    q = (
                        supabase.table("chat_history")
                        .select("*")
                        .eq("story_id", project_id)
                    )
                    # Chat riêng tư: chỉ lấy lịch sử của chính user hiện tại
                    if user_id:
                        q = q.eq("user_id", str(user_id))
                    chat_data = (
                        q.order("created_at", desc=True)
                        .limit(limit)
                        .execute()
                    )

                    if chat_data.data:
                        chat_data.data.reverse()
                        with st.spinner("Summarizing..."):
                            summary = RuleMiningSystem.crystallize_session(
                                chat_data.data, active_persona["role"]
                            )
                            if summary != "NO_INFO":
                                st.session_state["chat_crystallized_summary"] = summary
                                st.session_state["chat_crystallized_topic"] = (
                                    memory_topic
                                    if memory_topic
                                    else f"Chat {datetime.now().strftime('%d/%m')}"
                                )
                                st.success("Summary ready!")
                            else:
                                st.warning("No valuable information found.")
                    else:
                        st.info("Không có lịch sử chat nào để Crystallize cho user hiện tại.")
                except Exception as e:
                    st.error(f"Lỗi khi Crystallize: {e}")

        if "chat_crystallized_summary" in st.session_state:
            final_sum = st.text_area(
                "Edit summary:", value=st.session_state["chat_crystallized_summary"]
            )
            if st.button("💾 Save to Memory"):
                vec = AIService.get_embedding(final_sum)
                if vec:
                    try:
                        services = init_services()
                        supabase = services["supabase"]
                        payload = {
                            "entity_name": f"[CHAT] {st.session_state['chat_crystallized_topic']}",
                            "description": final_sum,
                            "embedding": vec,
                            "source_chapter": 0,
                        }
                        if can_write:
                            payload["story_id"] = project_id
                            supabase.table("story_bible").insert(payload).execute()
                            st.toast("Saved to memory!")
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
                                st.toast(
                                    "Đã gửi yêu cầu lưu CHAT vào Bible cho Owner duyệt.",
                                    icon="📤",
                                )
                            else:
                                st.error(
                                    "Không gửi được yêu cầu (kiểm tra bảng pending_changes)."
                                )
                        else:
                            st.warning("Bạn không có quyền lưu hoặc gửi yêu cầu.")
                    except Exception as e:
                        st.error(f"Lỗi khi lưu Memory: {e}")

                    del st.session_state["chat_crystallized_summary"]
                    st.rerun()

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

                router_out = SmartAIRouter.ai_router_pro_v2(prompt, recent_history_text, project_id)
                intent = router_out.get('intent', 'chat_casual')
                targets = router_out.get('target_files', [])
                rewritten_query = router_out.get('rewritten_query', prompt)

                debug_notes = [f"Intent: {intent}"]
                if st.session_state.get('router_ignore_history'):
                    debug_notes.append("⚡️ Router: Ignored History")

                context_text, sources, context_tokens = ContextManager.build_context(
                    router_out,
                    project_id,
                    active_persona,
                    st.session_state.get('strict_mode', False)
                )

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

                        # Rule mining chỉ bật cho Owner (hoặc user có quyền write)
                        if can_write:
                            new_rule = RuleMiningSystem.extract_rule_raw(prompt, full_response_text)
                            if new_rule:
                                st.session_state['pending_new_rule'] = new_rule

                    elif not st.session_state.get('enable_history', True):
                        st.caption("👻 Anonymous mode: History not saved & Rule mining disabled.")

                except Exception as e:
                    st.error(f"Generation error: {str(e)}")

    with col_chat:
        _chat_messages_fragment()

    # Rule Mining UI chỉ hiển thị nếu user có quyền write (Owner)
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
