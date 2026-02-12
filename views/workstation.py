import json
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import Config, init_services
from ai_engine import AIService, HybridSearch, ContextManager, generate_chapter_metadata, analyze_split_strategy, execute_split_logic, suggest_relations
from utils.file_importer import UniversalLoader
from utils.auth_manager import check_permission, submit_pending_change
from utils.cache_helpers import get_chapters_cached, invalidate_cache_and_rerun
from persona import PersonaSystem


def render_workstation_tab(project_id, persona):
    """
    Tab Workstation - Cache chapter list, fragment cho khung soạn thảo để giảm rerun toàn trang.
    """
    # Custom CSS cho UI gọn và thoáng
    st.markdown("""
    <style>
    /* Giảm padding chật giữa các cột */
    div[data-testid="stHorizontalBlock"] > div { padding: 0 0.35rem; }
    /* Khoảng cách cho text area */
    div[data-testid="stVerticalBlock"] > div { padding-top: 0.5rem; }
    /* Expander gọn hơn */
    .streamlit-expanderHeader { font-size: 0.95rem; }
    </style>
    """, unsafe_allow_html=True)

    st.subheader("✍️ Writing Workstation")

    if not project_id:
        st.info("📁 Vui lòng chọn Project ở thanh bên trái.")
        return

    st.session_state.setdefault("update_trigger", 0)
    file_list = get_chapters_cached(project_id, st.session_state.get("update_trigger", 0))
    file_options = {}
    for f in file_list:
        display_name = f"📄 #{f['chapter_number']}: {f.get('title') or f'Chapter {f['chapter_number']}'}"
        file_options[display_name] = f["chapter_number"]

    @st.fragment
    def _editor_fragment():
        try:
            services = init_services()
        except Exception:
            services = None
        if not services:
            st.warning("Không kết nối được dịch vụ.")
            return
        supabase = services["supabase"]

        selected_file = st.selectbox(
            "Chọn chương",
            ["+ Tạo chương mới"] + list(file_options.keys()),
            label_visibility="collapsed",
            key="workstation_file_select",
        )

        chap_num = 0
        selected_chapter_row = None
        if selected_file == "+ Tạo chương mới":
            chap_num = len(file_list) + 1
            db_content = ""
            db_review = ""
            db_title = f"Chapter {chap_num}"
        else:
            chap_num = file_options.get(selected_file, 1)
            try:
                res = (
                    supabase.table("chapters")
                    .select("*")
                    .eq("story_id", project_id)
                    .eq("chapter_number", chap_num)
                    .limit(1)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    row = res.data[0]
                    selected_chapter_row = row
                    db_content = row.get("content") or ""
                    db_title = row.get("title") or f"Chapter {chap_num}"
                    db_review = row.get("review_content") or ""
                else:
                    db_content = ""
                    db_title = f"Chapter {chap_num}"
                    db_review = ""
            except Exception as e:
                st.error(f"Lỗi load: {e}")
                db_content = ""
                db_title = f"Chapter {chap_num}"
                db_review = ""

        # Arc & Persona cho Workstation
        try:
            from core.arc_service import ArcService
            arcs = ArcService.list_arcs(project_id, status="active") if project_id else []
        except Exception:
            arcs = []
        arc_options = ["(Không gán arc)"] + [a.get("name", "") for a in arcs]
        cur_arc_id = selected_chapter_row.get("arc_id") if selected_chapter_row else None
        default_arc_idx = 0
        if cur_arc_id and arcs:
            for i, a in enumerate(arcs):
                if str(a.get("id")) == str(cur_arc_id):
                    default_arc_idx = i + 1
                    break
        arc_idx = st.selectbox("📐 Arc chương này", range(len(arc_options)), index=default_arc_idx, format_func=lambda i: arc_options[i] if i < len(arc_options) else "", key="ws_chapter_arc")
        chapter_arc_id = arcs[arc_idx - 1]["id"] if arc_idx and arc_idx > 0 and arc_idx <= len(arcs) else None

        personas_avail = PersonaSystem.get_available_personas()
        ws_persona_key = st.selectbox("🎭 Persona cho Review & Extract", personas_avail, key="ws_persona_select")
        ws_persona = PersonaSystem.get_persona(ws_persona_key)

        # Toolbar: các nút action gọn trên 1 hàng
        btn_cols = st.columns([2, 1, 1, 1, 1, 1, 2])
        with btn_cols[0]:
            updated_str = "—"
            if selected_chapter_row:
                updated = selected_chapter_row.get("updated_at") or selected_chapter_row.get("created_at", "")
                if updated:
                    try:
                        if isinstance(updated, str):
                            dt_u = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                            updated_str = dt_u.strftime("%d/%m/%Y %H:%M")
                        else:
                            updated_str = str(updated)[:16]
                    except Exception:
                        updated_str = str(updated)[:16] if updated else "—"
            st.caption(f"📅 Cập nhật: {updated_str}")

        def _update_metadata_background(pid, num, content_text):
            try:
                meta = generate_chapter_metadata(content_text)
                if not meta:
                    return
                svc = init_services()
                if not svc:
                    return
                sb = svc["supabase"]
                payload = {}
                if meta.get("summary") is not None:
                    payload["summary"] = meta["summary"]
                if meta.get("art_style") is not None:
                    payload["art_style"] = meta["art_style"]
                if payload:
                    sb.table("chapters").update(payload).eq("story_id", pid).eq(
                        "chapter_number", num
                    ).execute()
            except Exception as e:
                print(f"Background metadata update error: {e}")

        with btn_cols[1]:
            if st.button("💾 Lưu", use_container_width=True, key="ws_save_btn"):
                current_content = st.session_state.get(f"file_content_{chap_num}", "")
                current_title = st.session_state.get(f"file_title_{chap_num}", db_title)
                if current_content:
                    user_id = getattr(st.session_state.get("user"), "id", None) or ""
                    user_email = getattr(st.session_state.get("user"), "email", None) or ""
                    can_write = check_permission(user_id, user_email, project_id, "write")
                    can_request = check_permission(user_id, user_email, project_id, "request_write")
                    try:
                        if can_write:
                            payload = {"story_id": project_id, "chapter_number": chap_num, "title": current_title, "content": current_content}
                            if chapter_arc_id:
                                payload["arc_id"] = chapter_arc_id
                            supabase.table("chapters").upsert(payload, on_conflict="story_id, chapter_number").execute()
                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                            st.toast("Đã lưu & Đang cập nhật metadata...", icon="💾")
                            st.session_state.current_file_content = current_content
                            thread = threading.Thread(
                                target=_update_metadata_background,
                                args=(project_id, chap_num, current_content),
                                daemon=True,
                            )
                            thread.start()
                            time.sleep(0.5)
                            st.rerun()
                        elif can_request:
                            pid = submit_pending_change(
                                story_id=project_id,
                                requested_by_email=user_email,
                                table_name="chapters",
                                target_key={"story_id": project_id, "chapter_number": chap_num},
                                old_data={"title": db_title, "content": db_content},
                                new_data={"title": current_title, "content": current_content},
                            )
                            if pid:
                                st.toast("Đã gửi yêu cầu chỉnh sửa đến Owner.", icon="📤")
                            else:
                                st.error("Không gửi được yêu cầu (kiểm tra bảng pending_changes).")
                        else:
                            st.warning("Bạn không có quyền ghi hoặc gửi yêu cầu sửa.")
                    except Exception as e:
                        st.error(f"Lỗi lưu: {e}")

        with btn_cols[2]:
            if st.button("🚀 Review", use_container_width=True, type="primary", key="ws_review_btn"):
                st.session_state["trigger_ai_review"] = True
                st.rerun()
        with btn_cols[3]:
            if st.button("📥 Extract", use_container_width=True, key="ws_extract_btn"):
                st.session_state["extract_bible_mode"] = True
                st.session_state["temp_extracted_data"] = None
                st.rerun()
        with btn_cols[4]:
            if st.button("📂 Import", use_container_width=True, key="ws_import_btn"):
                st.session_state["workstation_import_mode"] = True
                st.rerun()
        with btn_cols[5]:
            if chap_num and st.button("🗑️ Xóa", use_container_width=True, key="ws_delete_current"):
                uid = getattr(st.session_state.get("user"), "id", None) or ""
                uem = getattr(st.session_state.get("user"), "email", None) or ""
                if check_permission(uid, uem, project_id, "write"):
                    chap_arc_id = selected_chapter_row.get("arc_id") if selected_chapter_row else None
                    arc_archived = False
                    if chap_arc_id:
                        try:
                            from core.arc_service import ArcService
                            arc_row = ArcService.get_arc(chap_arc_id)
                            arc_archived = arc_row and arc_row.get("status") == "archived"
                        except Exception:
                            pass
                    if arc_archived:
                        st.warning("Chương thuộc Arc đã archive. Bỏ archive Arc trước khi xóa chương.")
                    else:
                        try:
                            supabase.table("chapters").delete().eq("story_id", project_id).eq("chapter_number", chap_num).execute()
                            st.success(f"Đã xóa chương #{chap_num}.")
                            st.cache_data.clear()
                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi xóa chương: {e}")
                else:
                    st.warning("Chỉ Owner mới được xóa chương.")
        with btn_cols[6]:
            confirm_clear_all = st.checkbox(
                "Xóa hết", key="ws_confirm_clear_all_top", help="Bật để kích hoạt nút xóa sạch.",
            )
            if confirm_clear_all and st.button("🔥 Xóa sạch", type="secondary", use_container_width=True, key="ws_clear_all_btn_top"):
                uid = getattr(st.session_state.get("user"), "id", None) or ""
                uem = getattr(st.session_state.get("user"), "email", None) or ""
                if check_permission(uid, uem, project_id, "write"):
                    try:
                        supabase.table("chapters").delete().eq("story_id", project_id).execute()
                        st.success("✅ Đã xóa sạch tất cả chương!")
                        # st.session_state["ws_confirm_clear_all_top"] = False
                        st.cache_data.clear()
                        st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi xóa sạch: {e}")
                else:
                    st.warning("Chỉ Owner mới được xóa sạch dự án.")

        # Tóm tắt & Art style trong expander thu gọn
        if selected_chapter_row:
            with st.expander("📋 Tóm tắt & Art style", expanded=False):
                sum_text = selected_chapter_row.get("summary") or "—"
                art_text = selected_chapter_row.get("art_style") or "—"
                col_s, col_a = st.columns(2)
                with col_s:
                    st.markdown("**Tóm tắt**")
                    st.write(sum_text if len(str(sum_text)) < 500 else str(sum_text)[:500] + "...")
                with col_a:
                    st.markdown("**Art style**")
                    st.write(art_text if len(str(art_text)) < 300 else str(art_text)[:300] + "...")

        st.divider()

        if st.session_state.get("workstation_import_mode"):
            st.markdown("---")
            st.subheader("📂 Import nội dung từ file")
            st.caption("Hỗ trợ: PDF, DOCX, XLSX, XLS, CSV, TXT, MD.")
            uploaded = st.file_uploader(
                "Chọn file",
                type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "md"],
                key="workstation_file_upload",
            )
            if uploaded:
                text, err = UniversalLoader.load(uploaded)
                if err:
                    st.error(err)
                elif text:
                    st.session_state["workstation_imported_text"] = text
                    # Lưu phần mở rộng để áp logic cắt: PDF không cắt, CSV/XLS dùng sheet/row
                    fname = getattr(uploaded, "name", "") or ""
                    ext = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    st.session_state["workstation_import_ext"] = ext
                    st.text_area(
                        "Nội dung đã đọc (xem trước)",
                        value=text[:50000],
                        height=200,
                        disabled=True,
                        key="import_preview",
                        help="Xem trước nội dung file đã parse. Dùng Thay thế/Thêm vào cuối hoặc ✂️ Cắt thông minh.",
                    )
                    st.caption(f"Tổng {len(text)} ký tự.")
                    import_ext = st.session_state.get("workstation_import_ext", "")
                    is_pdf = import_ext == ".pdf"
                    col_replace, col_append, col_cut, col_cancel = st.columns(4)
                    with col_replace:
                        if st.button("✅ Thay thế", type="primary", use_container_width=True, key="imp_replace", help="Thay nội dung chương hiện tại bằng file."):
                            st.session_state[f"file_content_{chap_num}"] = text
                            st.session_state["workstation_import_mode"] = False
                            st.session_state.pop("workstation_imported_text", None)
                            st.session_state.pop("workstation_split_preview", None)
                            st.session_state.pop("workstation_import_ext", None)
                            st.success("Đã thay thế. Nhớ bấm Save để lưu DB.")
                            st.rerun()
                    with col_append:
                        if st.button("➕ Thêm vào cuối", use_container_width=True, key="imp_append", help="Nối file vào cuối chương hiện tại."):
                            current = st.session_state.get(f"file_content_{chap_num}", db_content or "")
                            st.session_state[f"file_content_{chap_num}"] = (current.rstrip() + "\n\n" + text.lstrip()) if current else text
                            st.session_state["workstation_import_mode"] = False
                            st.session_state.pop("workstation_imported_text", None)
                            st.session_state.pop("workstation_split_preview", None)
                            st.session_state.pop("workstation_import_ext", None)
                            st.success("Đã thêm vào cuối. Nhớ bấm Save.")
                            st.rerun()
                    with col_cut:
                        if not is_pdf:
                            if st.button("✂️ Cắt", use_container_width=True, key="imp_smart_split", help="AI cắt theo chương/entity/sheet, đề xuất nhiều phần để lưu thành nhiều chương."):
                                st.session_state["workstation_split_mode"] = True
                                st.session_state["workstation_imported_text"] = text
                                st.rerun()
                        else:
                            st.caption("⚠️ PDF: không hỗ trợ cắt tự động.")
                    with col_cancel:
                        if st.button("❌ Hủy", use_container_width=True, key="imp_cancel"):
                            st.session_state["workstation_import_mode"] = False
                            st.session_state.pop("workstation_imported_text", None)
                            st.session_state.pop("workstation_split_preview", None)
                            st.session_state.pop("workstation_split_mode", None)
                            st.session_state.pop("workstation_import_ext", None)
                            st.rerun()

                    # --- Workflow Cắt thông minh: AI Suggest (nhẹ) -> Python Execute (mạnh) ---
                    text_for_split = st.session_state.get("workstation_imported_text") or text
                    if st.session_state.get("workstation_split_mode") and text_for_split:
                        st.markdown("---")
                        st.subheader("✂️ Cắt thông minh")
                        import_ext_split = st.session_state.get("workstation_import_ext", "")
                        # CSV/XLS mặc định excel_export (chia theo sheet/row); TXT/MD/DOCX mặc định story (chia theo từ khóa)
                        default_idx = 2 if import_ext_split in (".csv", ".xls", ".xlsx") else 0
                        st.caption("💡 Text: cắt theo từ khóa (nội dung nằm giữa 2 từ khóa). CSV/XLS: cắt theo Sheet hoặc số dòng.")
                        file_type_choice = st.radio(
                            "Loại nội dung",
                            ["story", "character_data", "excel_export"],
                            index=default_idx,
                            format_func=lambda x: {"story": "📖 Truyện (từ khóa)", "character_data": "👤 Nhân vật/Entity", "excel_export": "📊 Excel/CSV (sheet/số dòng)"}[x],
                            key="split_type_radio",
                            help="Text: nội dung nằm gọn giữa 2 từ khóa. CSV/XLS: chia theo sheet hoặc tọa độ (số dòng).",
                        )
                        context_hint = st.text_input("Gợi ý thêm (tùy chọn)", placeholder="VD: Mỗi chương bắt đầu bằng 'Chương N'", key="split_hint")
                        
                        # AI Analyzer: phân tích mẫu rải rác
                        if st.button("🤖 AI tìm quy luật phân cách", type="primary", key="split_analyze"):
                            with st.spinner("AI đang phân tích mẫu rải rác (80 đầu + 80 giữa + 80 cuối)..."):
                                strategy = analyze_split_strategy(text_for_split, file_type=file_type_choice, context_hint=context_hint)
                                st.session_state["workstation_split_strategy"] = strategy
                            st.success(f"Tìm thấy quy luật: **{strategy['split_type']}** = `{strategy['split_value']}`")
                        
                        strategy = st.session_state.get("workstation_split_strategy")
                        if strategy:
                            st.info(f"📋 Quy luật: **{strategy['split_type']}** → Pattern/Keyword: `{strategy['split_value']}`")
                            if st.button("👀 Xem trước 5 đoạn cắt đầu tiên", key="split_preview_btn"):
                                with st.spinner("Python đang dùng Regex quét toàn bộ file..."):
                                    preview_splits = execute_split_logic(text_for_split, strategy["split_type"], strategy["split_value"], debug=True)
                                    st.session_state["workstation_split_preview"] = preview_splits
                                if preview_splits:
                                    st.success(f"✅ Tìm thấy **{len(preview_splits)}** phần. Xem preview bên dưới.")
                                else:
                                    st.error("❌ Không tìm thấy dấu hiệu phân chia chương. Vui lòng kiểm tra lại định dạng hoặc thử keyword/pattern khác.")
                            
                            preview = st.session_state.get("workstation_split_preview")
                            if preview:
                                st.caption("📋 **Safety Check:** Xem trước 5 đoạn cắt đầu tiên — nếu ổn, bấm **Xác nhận cắt** để lưu toàn bộ.")
                                for i, part in enumerate(preview[:5]):
                                    with st.expander(f"📄 {i+1}. {part.get('title', '')[:50]}... ({len(part.get('content', ''))} ký tự)"):
                                        st.text_area("Nội dung", value=part.get("content", "")[:2000] + ("..." if len(part.get("content", "")) > 2000 else ""), height=100, key=f"split_preview_{i}", disabled=True)
                                if len(preview) > 5:
                                    st.caption(f"⚠️ ... và {len(preview) - 5} phần khác sẽ được cắt tương tự.")
                                
                                if st.button("✅ Xác nhận cắt", type="primary", key="split_confirm"):
                                    try:
                                        svc = init_services()
                                        if not svc:
                                            st.error("Không kết nối được dịch vụ.")
                                        else:
                                            supabase = svc["supabase"]
                                            r = supabase.table("chapters").select("chapter_number").eq("story_id", project_id).order("chapter_number", desc=True).limit(1).execute()
                                            start_num = (r.data[0]["chapter_number"] + 1) if r.data else 1
                                            
                                            progress_bar = st.progress(0)
                                            status_text = st.empty()
                                            total = len(preview)
                                            
                                            for i, part in enumerate(preview):
                                                status_text.text(f"Đang lưu phần {i+1}/{total}: {part.get('title', '')[:30]}...")
                                                supabase.table("chapters").insert({
                                                    "story_id": project_id,
                                                    "chapter_number": start_num + i,
                                                    "title": part.get("title", f"Chương {start_num + i}"),
                                                    "content": part.get("content", ""),
                                                }).execute()
                                                progress_bar.progress((i + 1) / total)
                                            
                                            status_text.empty()
                                            progress_bar.empty()
                                            st.success(f"✅ Đã tạo {len(preview)} chương (số {start_num} → {start_num + len(preview) - 1}).")
                                            st.session_state["workstation_import_mode"] = False
                                            st.session_state.pop("workstation_imported_text", None)
                                            st.session_state.pop("workstation_split_preview", None)
                                            st.session_state.pop("workstation_split_strategy", None)
                                            st.session_state.pop("workstation_split_mode", None)
                                            st.session_state.pop("workstation_import_ext", None)
                                            invalidate_cache_and_rerun()
                                    except Exception as e:
                                        st.error(f"Lỗi lưu: {e}")
                        
                        if st.session_state.get("workstation_split_mode") and st.button("↩️ Quay lại", key="split_back"):
                            st.session_state.pop("workstation_split_preview", None)
                            st.session_state.pop("workstation_split_strategy", None)
                            st.session_state["workstation_split_mode"] = False
                            st.rerun()
            else:
                if st.button("Đóng Import", key="workstation_import_close"):
                    st.session_state["workstation_import_mode"] = False
                    st.session_state.pop("workstation_imported_text", None)
                    st.rerun()

        file_title = st.text_input(
            "Tiêu đề chương",
            value=db_title,
            key=f"file_title_{chap_num}",
            label_visibility="collapsed",
            placeholder="Nhập tên chương...",
        )
        has_review = bool(db_review) or st.session_state.get("trigger_ai_review")
        if has_review:
            col_editor, col_review = st.columns([3, 2])
        else:
            col_editor = st.container()
        with col_editor:
            content = st.text_area(
                "Nội dung chính",
                value=db_content,
                height=650,
                key=f"file_content_{chap_num}",
                label_visibility="collapsed",
                placeholder="Viết nội dung của bạn tại đây...",
            )
            if content:
                st.caption(f"📝 {len(content.split())} từ | {len(content)} ký tự")
        if has_review:
            with col_review:
                if st.session_state.get("trigger_ai_review"):
                    with st.spinner("AI đang đọc & đối chiếu Bible..."):
                        try:
                            context = HybridSearch.smart_search_hybrid(content[:1000], project_id)
                            rules = ContextManager.get_mandatory_rules(project_id)
                            review_prompt = f"""
                    LUẬT DỰ ÁN: {rules}
                    THÔNG TIN TỪ BIBLE (Context): {context}
                    NỘI DUNG CẦN REVIEW:
                    {content}
                    NHIỆM VỤ: {ws_persona.get('review_prompt', 'Review nội dung này')}
                    YÊU CẦU:
                    1. Chỉ ra điểm mạnh/yếu.
                    2. Phát hiện lỗi logic (plot hole) hoặc lỗi code so với Context.
                    3. Đề xuất cải thiện cụ thể.
                    4. Trả về định dạng Markdown đẹp mắt (Bullet points).
                    5. Ngôn ngữ: TIẾNG VIỆT.
                    """
                            response = AIService.call_openrouter(
                                messages=[{"role": "user", "content": review_prompt}],
                                model=st.session_state.get("selected_model", Config.DEFAULT_MODEL),
                                temperature=0.5,
                            )
                            if response and response.choices:
                                new_review = response.choices[0].message.content
                                supabase.table("chapters").update({"review_content": new_review}).eq(
                                    "story_id", project_id
                                ).eq("chapter_number", chap_num).execute()
                                st.session_state["trigger_ai_review"] = False
                                st.toast("Review hoàn tất!", icon="🤖")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi Review: {e}")
                            st.session_state["trigger_ai_review"] = False
                with st.expander("🤖 AI Editor Notes", expanded=True):
                    if db_review:
                        st.markdown(db_review)
                        if st.button("🗑️ Xóa Review", key="del_rev", use_container_width=True):
                            supabase.table("chapters").update({"review_content": ""}).eq(
                                "story_id", project_id
                            ).eq("chapter_number", chap_num).execute()
                            st.rerun()
                    else:
                        st.info("Chưa có nhận xét nào.")

    _editor_fragment()

    if st.session_state.get("extract_bible_mode"):
        sel = st.session_state.get("workstation_file_select", "+ Tạo chương mới")
        if sel == "+ Tạo chương mới":
            _chap = len(file_list) + 1
        else:
            _chap = file_options.get(sel, 1)
        content = st.session_state.get(f"file_content_{_chap}", "")
        if content:
            services = init_services()
            supabase = services["supabase"]
            st.markdown("---")
            with st.container():
                st.subheader("📚 Trích xuất Bible (Smart Mode - Tự do)")

                has_data = st.session_state.get('temp_extracted_data') is not None

                if not has_data:
                    st.info("💡 Extract: (1) Tóm tắt + Art style → lưu chapters, (2) Bible → xác nhận, (3) Relation → xác nhận.")

                    if st.button("▶️ Bắt đầu phân tích", type="primary", key="extract_start"):
                        my_bar = st.progress(0, text="Đang khởi động bộ não...")

                        def _save_metadata_async(pid, num, content_text):
                            try:
                                meta = generate_chapter_metadata(content_text)
                                if meta:
                                    svc = init_services()
                                    if svc:
                                        sb = svc["supabase"]
                                        payload = {}
                                        if meta.get("summary") is not None:
                                            payload["summary"] = meta["summary"]
                                        if meta.get("art_style") is not None:
                                            payload["art_style"] = meta["art_style"]
                                        if payload:
                                            sb.table("chapters").update(payload).eq("story_id", pid).eq("chapter_number", num).execute()
                            except Exception:
                                pass

                        # (1) Async: tóm tắt + art_style lưu vào chapters
                        thread = threading.Thread(target=_save_metadata_async, args=(project_id, _chap, content), daemon=True)
                        thread.start()

                        def chunk_text(text, chunk_size=64000):
                            return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

                        chunks = chunk_text(content)
                        total_chunks = len(chunks)
                        all_extracted_items = []

                        try:
                            for i, chunk_content in enumerate(chunks):
                                my_bar.progress(int((i / total_chunks) * 90), text=f"Đang đọc hiểu phần {i+1}/{total_chunks}...")

                                ext_persona = PersonaSystem.get_persona(st.session_state.get("ws_persona_select", "Writer"))
                                allowed_keys = Config.get_allowed_prefix_keys_for_extract()
                                prefix_list_str = ", ".join(allowed_keys) + ", OTHER" if allowed_keys else "OTHER"
                                ext_prompt = f"""
                            NỘI DUNG (Phần {i+1}/{total_chunks}):
                            {chunk_content}

                            NHIỆM VỤ: {ext_persona.get('extractor_prompt', 'Trích xuất các thực thể quan trọng từ nội dung trên.')}

                            ⛔️ YÊU CẦU ĐỊNH DẠNG (JSON BẮT BUỘC):
                            1. Trả về một JSON Object duy nhất chứa key "items".
                            2. KHÔNG viết lời dẫn, KHÔNG dùng markdown code block.
                            3. Trường "type": phải là đúng MỘT trong các key sau (viết IN HOA, không dấu ngoặc): {prefix_list_str}. Nếu không khớp loại nào thì dùng OTHER.
                            4. "description": Tóm tắt ngắn gọn vai trò/đặc điểm (dưới 50 từ).

                            ⚠️ QUAN TRỌNG:
                                - Nếu không tìm thấy thực thể nào, hãy trả về danh sách rỗng: {{ "items": [] }}
                                - TUYỆT ĐỐI KHÔNG COPY VÍ DỤ MẪU BÊN DƯỚI VÀO KẾT QUẢ.

                            VÍ DỤ CẤU TRÚC (CHỈ ĐỂ THAM KHẢO FORMAT, KHÔNG ĐƯỢC CHÉP):
                        {{
                            "items": [
                                {{ "entity_name": "Tên_Thực_Thể", "type": "CHARACTER", "description": "Mô_tả_ngắn..." }}
                                    ]
                        }}
                            """

                                response = AIService.call_openrouter(
                                    messages=[{"role": "user", "content": ext_prompt}],
                                    model=st.session_state.get('selected_model', Config.DEFAULT_MODEL),
                                    temperature=0.0,
                                    max_tokens=16000,
                                    response_format={"type": "json_object"}
                                )

                                if response and response.choices:
                                    raw_text = response.choices[0].message.content.strip()
                                    try:
                                        json_obj = json.loads(raw_text)
                                        chunk_items = []
                                        if "items" in json_obj:
                                            chunk_items = json_obj["items"]
                                        elif isinstance(json_obj, list):
                                            chunk_items = json_obj
                                        if chunk_items:
                                            all_extracted_items.extend(chunk_items)
                                    except Exception:
                                        clean_json = AIService.clean_json_text(raw_text)
                                        try:
                                            parsed = json.loads(clean_json)
                                            if isinstance(parsed, dict):
                                                all_extracted_items.extend(parsed.get('items', []))
                                            elif isinstance(parsed, list):
                                                all_extracted_items.extend(parsed)
                                        except Exception:
                                            pass

                            my_bar.progress(100, text="Hoàn tất! Đang tổng hợp...")
                            time.sleep(0.5)
                            my_bar.empty()
                            st.session_state['temp_extracted_data'] = all_extracted_items
                            st.session_state['extract_chapter_num'] = _chap
                            st.session_state['extract_content'] = content
                            st.session_state['extract_bible_saved'] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi hệ thống: {e}")

                    if st.button("Hủy bỏ", key="extract_cancel"):
                        st.session_state['extract_bible_mode'] = False
                        st.rerun()

                else:
                    items = st.session_state['temp_extracted_data']
                    if not items:
                        st.warning("⚠️ Không tìm thấy thực thể nào trong nội dung này.")
                        if st.button("Thử lại / Quét lại", key="extract_retry"):
                            st.session_state['temp_extracted_data'] = None
                            st.rerun()
                        if st.button("Đóng", key="extract_close"):
                            st.session_state['extract_bible_mode'] = False
                            st.session_state['temp_extracted_data'] = None
                            st.rerun()
                    else:
                        unique_items_dict = {}
                        for item in items:
                            name = item.get('entity_name', '').strip()
                            if name:
                                if name not in unique_items_dict:
                                    unique_items_dict[name] = item
                                else:
                                    if len(item.get('description', '')) > len(unique_items_dict[name].get('description', '')):
                                        unique_items_dict[name] = item
                        unique_items = list(unique_items_dict.values())
                        df_preview = pd.DataFrame(unique_items)
                        st.success(f"✅ Tìm thấy {len(unique_items)} thực thể độc nhất!")
                        with st.expander("👀 Xem trước & Kiểm tra dữ liệu", expanded=True):
                            if 'entity_name' in df_preview.columns:
                                st.dataframe(df_preview[['entity_name', 'type', 'description']], use_container_width=True)
                            else:
                                st.dataframe(df_preview, use_container_width=True)
                        bible_saved = st.session_state.get('extract_bible_saved', False)

                        if not bible_saved:
                            st.caption("**Bước 1:** Xác nhận Bible để lưu, sau đó hệ thống sẽ gợi ý Relation.")
                            c_save, c_cancel = st.columns([1, 1])
                            with c_save:
                                if st.button("✅ Xác nhận Bible", type="primary", use_container_width=True, key="extract_confirm_bible"):
                                    uid = getattr(st.session_state.get("user"), "id", None) or ""
                                    uem = getattr(st.session_state.get("user"), "email", None) or ""
                                    if not check_permission(uid, uem, project_id, "write"):
                                        st.warning("Chỉ Owner mới được lưu Bible.")
                                    else:
                                        count = 0
                                        prog = st.progress(0)
                                        total = len(unique_items)
                                        _chap_num = st.session_state.get('extract_chapter_num', 0)
                                        for idx, item in enumerate(unique_items):
                                            desc = item.get('description', '')
                                            raw_name = item.get('entity_name', 'Unknown')
                                            raw_type_str = item.get('type', 'OTHER').strip()
                                            prefix_key = Config.resolve_prefix_for_bible(raw_type_str)
                                            final_name = f"[{prefix_key}] {raw_name}" if not raw_name.startswith("[") else raw_name
                                            if desc:
                                                vec = AIService.get_embedding(desc)
                                                if vec:
                                                    supabase.table("story_bible").insert({
                                                        "story_id": project_id,
                                                        "entity_name": final_name,
                                                        "description": desc,
                                                        "embedding": vec,
                                                        "source_chapter": _chap_num,
                                                    }).execute()
                                                    count += 1
                                            prog.progress(int((idx + 1) / total * 100))
                                        st.session_state['extract_bible_saved'] = True
                                        st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                        # (2) Chạy suggest_relations để gợi ý quan hệ
                                        extract_content = st.session_state.get('extract_content', '')
                                        if extract_content:
                                            try:
                                                rels = suggest_relations(extract_content.strip(), project_id)
                                                st.session_state['temp_relation_suggestions'] = rels or []
                                            except Exception:
                                                st.session_state['temp_relation_suggestions'] = []
                                        else:
                                            st.session_state['temp_relation_suggestions'] = []
                                        st.success(f"Đã lưu {count} mục Bible! Tiếp theo: xác nhận Relation bên dưới.")
                                        st.rerun()
                            with c_cancel:
                                if st.button("Hủy bỏ / Làm lại", use_container_width=True, key="extract_cancel2"):
                                    st.session_state['extract_bible_mode'] = False
                                    st.session_state['temp_extracted_data'] = None
                                    st.session_state.pop('extract_chapter_num', None)
                                    st.session_state.pop('extract_content', None)
                                    st.session_state.pop('extract_bible_saved', None)
                                    st.session_state.pop('temp_relation_suggestions', None)
                                    st.rerun()
                        else:
                            # Bước 2: Xác nhận Relation
                            rel_pending = st.session_state.get('temp_relation_suggestions') or []
                            try:
                                from utils.cache_helpers import get_bible_list_cached
                                bible_entries = get_bible_list_cached(project_id, st.session_state.get("update_trigger", 0))
                                id_to_name = {e["id"]: e.get("entity_name", "") for e in bible_entries}
                            except Exception:
                                id_to_name = {}
                            if rel_pending:
                                st.caption("**Bước 2:** Xác nhận quan hệ giữa các thực thể, sau đó bấm Hoàn tất.")
                                batch_a, batch_b = st.columns(2)
                                with batch_a:
                                    if st.button("✅ Xác nhận tất cả", type="primary", key="ext_rel_confirm_all"):
                                        uid = getattr(st.session_state.get("user"), "id", None) or ""
                                        uem = getattr(st.session_state.get("user"), "email", None) or ""
                                        if check_permission(uid, uem, project_id, "write"):
                                            errs = []
                                            for item in list(rel_pending):
                                                try:
                                                    if item.get("kind") == "relation":
                                                        supabase.table("entity_relations").insert({
                                                            "source_entity_id": item["source_entity_id"],
                                                            "target_entity_id": item["target_entity_id"],
                                                            "relation_type": item.get("relation_type", "liên quan"),
                                                            "description": item.get("description", "") or "",
                                                            "story_id": project_id,
                                                        }).execute()
                                                    else:
                                                        supabase.table("story_bible").update({"parent_id": item["parent_entity_id"]}).eq("id", item["entity_id"]).execute()
                                                except Exception as ex:
                                                    errs.append(str(ex))
                                            st.session_state["temp_relation_suggestions"] = []
                                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                            if errs:
                                                st.warning("Đã lưu nhưng một số lỗi: " + "; ".join(errs[:3]))
                                            st.rerun()
                                        else:
                                            st.warning("Chỉ Owner mới được xác nhận.")
                                with batch_b:
                                    if st.button("❌ Hủy tất cả", key="ext_rel_reject_all"):
                                        st.session_state["temp_relation_suggestions"] = []
                                        st.rerun()
                                st.markdown("---")
                                for i, item in enumerate(rel_pending):
                                    if item.get("kind") == "relation":
                                        src_name = id_to_name.get(item.get("source_entity_id"), str(item.get("source_entity_id", "")))
                                        tgt_name = id_to_name.get(item.get("target_entity_id"), str(item.get("target_entity_id", "")))
                                        with st.container():
                                            st.markdown(
                                                f"**{src_name}** — *{item.get('relation_type', '')}* — **{tgt_name}**  \n"
                                                f"_{item.get('description', '')}_"
                                            )
                                            c1, c2 = st.columns(2)
                                            with c1:
                                                if st.button("✅ Xác nhận", key=f"ext_rel_confirm_{i}"):
                                                    uid = getattr(st.session_state.get("user"), "id", None) or ""
                                                    uem = getattr(st.session_state.get("user"), "email", None) or ""
                                                    if check_permission(uid, uem, project_id, "write"):
                                                        try:
                                                            supabase.table("entity_relations").insert({
                                                                "source_entity_id": item["source_entity_id"],
                                                                "target_entity_id": item["target_entity_id"],
                                                                "relation_type": item.get("relation_type", "liên quan"),
                                                                "description": item.get("description", "") or "",
                                                                "story_id": project_id,
                                                            }).execute()
                                                            rel_pending.pop(i)
                                                            st.session_state['temp_relation_suggestions'] = rel_pending
                                                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                                            st.rerun()
                                                        except Exception as ex:
                                                            st.error(f"Lỗi: {ex}")
                                            with c2:
                                                if st.button("❌ Hủy", key=f"ext_rel_reject_{i}"):
                                                    rel_pending.pop(i)
                                                    st.session_state['temp_relation_suggestions'] = rel_pending
                                                    st.rerun()
                                            st.markdown("---")
                                    else:
                                        ent_name = id_to_name.get(item.get("entity_id"), str(item.get("entity_id", "")))
                                        par_name = id_to_name.get(item.get("parent_entity_id"), str(item.get("parent_entity_id", "")))
                                        with st.container():
                                            st.markdown(
                                                f"**Đặt parent (1-n):** *{ent_name}* → gốc **{par_name}**  \n"
                                                f"_{item.get('reason', '')}_"
                                            )
                                            c1, c2 = st.columns(2)
                                            with c1:
                                                if st.button("✅ Xác nhận", key=f"ext_parent_confirm_{i}"):
                                                    uid = getattr(st.session_state.get("user"), "id", None) or ""
                                                    uem = getattr(st.session_state.get("user"), "email", None) or ""
                                                    if check_permission(uid, uem, project_id, "write"):
                                                        try:
                                                            supabase.table("story_bible").update({"parent_id": item["parent_entity_id"]}).eq("id", item["entity_id"]).execute()
                                                            rel_pending.pop(i)
                                                            st.session_state['temp_relation_suggestions'] = rel_pending
                                                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                                            st.rerun()
                                                        except Exception as ex:
                                                            st.error(f"Lỗi: {ex}")
                                            with c2:
                                                if st.button("❌ Hủy", key=f"ext_parent_reject_{i}"):
                                                    rel_pending.pop(i)
                                                    st.session_state['temp_relation_suggestions'] = rel_pending
                                                    st.rerun()
                                            st.markdown("---")
                            if not rel_pending:
                                st.info("Không có đề xuất quan hệ nào, hoặc bạn đã xác nhận/hủy hết.")

                            # Bước 3: Chunking nội dung chương
                            extract_content = st.session_state.get('extract_content', '')
                            _chap_num = st.session_state.get('extract_chapter_num', 0)
                            temp_chunks = st.session_state.get('temp_extract_chunks')
                            chunking_done = st.session_state.get('extract_chunking_done', False)

                            if extract_content and not chunking_done:
                                st.markdown("---")
                                st.caption("**Bước 3:** Chunk nội dung chương đang extract → chỉnh sửa & xác nhận → lưu chunks.")
                                if temp_chunks is None:
                                    if st.button("📄 Phân tích Chunk", key="extract_chunk_analyze"):
                                        with st.spinner("Đang phân tích chiến lược chunk..."):
                                            strategy = analyze_split_strategy(extract_content, file_type="story", context_hint="Đoạn văn có ý nghĩa")
                                            chunks_list = execute_split_logic(extract_content, strategy["split_type"], strategy["split_value"])
                                            if chunks_list:
                                                st.session_state['temp_extract_chunks'] = chunks_list
                                                st.rerun()
                                            else:
                                                st.warning("Không tách được chunk. Thử chiến lược mặc định.")
                                                st.session_state['temp_extract_chunks'] = execute_split_logic(extract_content, "by_length", "2000")
                                                st.rerun()
                                else:
                                    edited = []
                                    for i, c in enumerate(temp_chunks):
                                        with st.expander(f"Chunk {i+1}: {c.get('title','')[:40]}...", expanded=(i < 2)):
                                            new_content = st.text_area("Nội dung", value=c.get("content", ""), height=120, key=f"ext_chunk_edit_{i}")
                                            edited.append({"title": c.get("title",""), "content": new_content or c.get("content",""), "order": c.get("order", i+1)})
                                    st.session_state['temp_extract_chunks'] = edited
                                    col_ok, col_skip = st.columns(2)
                                    with col_ok:
                                        if st.button("✅ Xác nhận & Lưu Chunks", type="primary", key="extract_chunk_confirm"):
                                            uid = getattr(st.session_state.get("user"), "id", None) or ""
                                            uem = getattr(st.session_state.get("user"), "email", None) or ""
                                            if not check_permission(uid, uem, project_id, "write"):
                                                st.warning("Chỉ Owner mới được lưu chunks.")
                                            else:
                                                ch_row = supabase.table("chapters").select("id, arc_id").eq("story_id", project_id).eq("chapter_number", _chap_num).limit(1).execute()
                                                chapter_id = ch_row.data[0]["id"] if ch_row.data else None
                                                arc_id = ch_row.data[0].get("arc_id") if ch_row.data else None
                                                prog = st.progress(0)
                                                saved = 0
                                                for idx, chk in enumerate(edited):
                                                    txt = chk.get("content", "").strip()
                                                    if txt:
                                                        vec = AIService.get_embedding(txt)
                                                        payload = {
                                                            "story_id": project_id,
                                                            "chapter_id": chapter_id,
                                                            "arc_id": arc_id,
                                                            "content": txt,
                                                            "raw_content": txt,
                                                            "meta_json": {"source": "extract_bible", "chapter": _chap_num, "title": chk.get("title","")},
                                                            "sort_order": chk.get("order", idx+1),
                                                        }
                                                        if vec:
                                                            payload["embedding"] = vec
                                                        supabase.table("chunks").insert(payload).execute()
                                                        saved += 1
                                                    prog.progress(int((idx+1)/len(edited)*100))
                                                st.session_state['extract_chunking_done'] = True
                                                st.session_state.pop('temp_extract_chunks', None)
                                                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                                st.success(f"Đã lưu {saved} chunks. Bấm Hoàn tất để đóng.")
                                                st.rerun()
                                    with col_skip:
                                        if st.button("⏭️ Bỏ qua Chunking", key="extract_chunk_skip"):
                                            st.session_state['extract_chunking_done'] = True
                                            st.session_state.pop('temp_extract_chunks', None)
                                            st.rerun()

                            if st.button("✅ Hoàn tất Extract", type="primary", key="extract_finish"):
                                st.session_state['extract_bible_mode'] = False
                                st.session_state['temp_extracted_data'] = None
                                st.session_state.pop('extract_chapter_num', None)
                                st.session_state.pop('extract_content', None)
                                st.session_state.pop('extract_bible_saved', None)
                                st.session_state.pop('temp_relation_suggestions', None)
                                st.session_state.pop('temp_extract_chunks', None)
                                st.session_state.pop('extract_chunking_done', None)
                                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                invalidate_cache_and_rerun()
        else:
            st.warning("⚠️ Chương hiện tại chưa có nội dung. Nhập nội dung và bấm Save trước khi Extract.")
            if st.button("Đóng Extract", key="extract_close_empty"):
                st.session_state['extract_bible_mode'] = False
                st.rerun()
