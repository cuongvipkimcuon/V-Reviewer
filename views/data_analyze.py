# views/data_analyze.py - Tab Data Analyze: chọn chương, gửi tác vụ chạy ngầm (Extract Bible / Relation / Timeline / Chunk)
import json
import threading

import streamlit as st

from config import Config, init_services
from ai_engine import (
    AIService,
    analyze_split_strategy,
    execute_split_logic,
    suggest_relations,
    extract_timeline_events_from_content,
    _get_default_tool_model,
)
from utils.auth_manager import check_permission
from utils.cache_helpers import get_chapters_cached
from persona import PersonaSystem
from core.background_jobs import create_job, run_job_worker


def _get_existing_bible_entity_names_for_chapter(project_id, chap_num, supabase):
    """Lấy set entity_name (và tên không prefix) đã có trong Bible cho chương này."""
    try:
        r = supabase.table("story_bible").select("entity_name").eq(
            "story_id", project_id
        ).eq("source_chapter", chap_num).execute()
        names = set()
        for row in (r.data or []):
            en = (row.get("entity_name") or "").strip()
            if en:
                names.add(en)
                # Thêm phần sau prefix [XXX] để match khi extract trả về tên không prefix
                if en.startswith("[") and "]" in en:
                    rest = en[en.index("]") + 1:].strip()
                    if rest:
                        names.add(rest)
        return names
    except Exception:
        return set()


def _get_entity_ids_for_chapter(project_id, chap_num, supabase):
    """Lấy list id các entity Bible có source_chapter = chương này."""
    try:
        r = supabase.table("story_bible").select("id").eq(
            "story_id", project_id
        ).eq("source_chapter", chap_num).execute()
        return [row["id"] for row in (r.data or []) if row.get("id")]
    except Exception:
        return []


def _run_extract_on_content(content, ext_persona, project_id, chap_num, exclude_existing=False, supabase=None):
    """Chạy extract Bible trên content; nếu exclude_existing thì loại item trùng với Bible hiện có của chương."""
    from ai_engine import AIService
    strategy = analyze_split_strategy(content, file_type="story", context_hint="")
    parts = execute_split_logic(content, strategy.get("split_type", "by_length"), strategy.get("split_value", "50000"))
    if not parts:
        parts = execute_split_logic(content, "by_length", "50000")
    MAX_CHARS = 55000
    chunks = []
    for p in parts:
        c = (p.get("content") or "").strip()
        if not c:
            continue
        if len(c) <= MAX_CHARS:
            chunks.append(c)
        else:
            for s in execute_split_logic(c, "by_length", "50000"):
                sc = (s.get("content") or "").strip()
                if sc:
                    chunks.append(sc)
    all_items = []
    allowed_keys = Config.get_allowed_prefix_keys_for_extract()
    prefix_list_str = ", ".join(allowed_keys) + ", OTHER" if allowed_keys else "OTHER"
    for i, chunk_content in enumerate(chunks):
        ext_prompt = f"""
NỘI DUNG (Phần {i+1}/{len(chunks)}):
{chunk_content}

NHIỆM VỤ: {ext_persona.get('extractor_prompt', 'Trích xuất các thực thể quan trọng từ nội dung trên.')}

⛔️ YÊU CẦU: Trả về JSON với key "items". Trường "type" phải là đúng MỘT trong: {prefix_list_str}. "description": tóm tắt dưới 50 từ.
Nếu không tìm thấy: {{ "items": [] }}. Chỉ trả về JSON."""
        try:
            resp = AIService.call_openrouter(
                messages=[{"role": "user", "content": ext_prompt}],
                model=_get_default_tool_model(),
                temperature=0.0,
                max_tokens=16000,
                response_format={"type": "json_object"},
            )
            if resp and resp.choices:
                raw = resp.choices[0].message.content.strip()
                obj = json.loads(AIService.clean_json_text(raw))
                items_chunk = obj.get("items", []) if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
                all_items.extend(items_chunk)
        except Exception:
            pass
    if exclude_existing and supabase:
        existing = _get_existing_bible_entity_names_for_chapter(project_id, chap_num, supabase)
        def _norm(s):
            return (s or "").strip().lower()
        new_items = []
        for item in all_items:
            name = (item.get("entity_name") or "").strip()
            if not name:
                continue
            if _norm(name) in {_norm(n) for n in existing}:
                continue
            if name in existing:
                continue
            # Check without prefix
            if "]" in name and name.startswith("["):
                rest = name[name.index("]") + 1:].strip()
                if _norm(rest) in {_norm(n) for n in existing}:
                    continue
            new_items.append(item)
        return new_items
    unique_dict = {}
    for item in all_items:
        name = item.get("entity_name", "").strip()
        if name and (name not in unique_dict or len(item.get("description", "")) > len(unique_dict[name].get("description", ""))):
            unique_dict[name] = item
    return list(unique_dict.values())


def render_data_analyze_tab(project_id):
    if not project_id:
        st.info("📁 Vui lòng chọn Project ở thanh bên trái.")
        return

    st.session_state.setdefault("update_trigger", 0)
    file_list = get_chapters_cached(project_id, st.session_state.get("update_trigger", 0))
    file_options = {}
    for f in file_list:
        display_name = f"📄 #{f['chapter_number']}: {f.get('title') or f'Chapter {f['chapter_number']}'}"
        file_options[display_name] = f["chapter_number"]

    if not file_list:
        st.info("Chưa có chương nào. Tạo chương trong Workstation trước.")
        return

    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    selected_file = st.selectbox(
        "Chọn chương để phân tích",
        list(file_options.keys()),
        key="da_chapter_select",
    )
    chap_num = file_options.get(selected_file, 1)
    res = supabase.table("chapters").select("*").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
    selected_row = res.data[0] if res.data and len(res.data) > 0 else None
    content = (selected_row.get("content") or "").strip() if selected_row else ""

    if not content:
        st.warning("Chương này chưa có nội dung. Thêm nội dung trong Workstation.")
        st.stop()

    st.caption(f"Nội dung chương: {len(content)} ký tự.")

    _render_extract_bible_relations_chunking(
        project_id, content, chap_num, selected_row, file_options, selected_file, supabase
    )
    _render_timeline_section(project_id, content, chap_num, selected_row, supabase)

    st.session_state.setdefault("update_trigger", st.session_state.get("update_trigger", 0))


def _render_timeline_section(project_id, content, chap_num, selected_row, supabase):
    """Timeline: gửi job chạy ngầm; AI trích xuất và lưu trực tiếp. V Work thông báo khi xong."""
    st.markdown("---")
    st.subheader("📅 Timeline (trích xuất từ chương)")
    try:
        supabase.table("timeline_events").select("id").limit(1).execute()
    except Exception:
        st.warning("Bảng timeline_events chưa tồn tại. Chạy schema_v7_migration.sql trên Supabase để dùng tính năng này.")
        return
    chapter_label = selected_row.get("title") or f"Chương {chap_num}"
    st.caption(f"Chương: {chapter_label}. AI trích xuất sự kiện và lưu vào Timeline (xóa events cũ của chương). Chạy ngầm.")
    st.checkbox(
        "⚠️ Tôi hiểu: Trích xuất Timeline sẽ **xóa toàn bộ** timeline_events đã gắn với chương này trước khi lưu mới.",
        key="da_confirm_delete_timeline_chapter",
    )
    uid = getattr(st.session_state.get("user"), "id", None) or ""
    uem = getattr(st.session_state.get("user"), "email", None) or ""
    can_write = check_permission(uid, uem, project_id, "write")
    if st.session_state.get("da_confirm_delete_timeline_chapter") and can_write:
        if st.button("🤖 AI trích xuất timeline từ chương này", type="primary", key="da_timeline_extract_btn"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_timeline",
                label=f"Timeline chương {chap_num}",
                payload={"chapter_number": chap_num, "chapter_label": chapter_label},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                st.rerun()
            else:
                st.error("Không tạo được job.")


def _render_extract_bible_relations_chunking(project_id, content, chap_num, selected_row, file_options, selected_file, supabase):
    """Nội dung tab Extract Bible / Relations / Chunking (giữ nguyên logic cũ)."""
    # --- Section 1: Extract Bible ---
    st.markdown("---")
    st.subheader("📥 Extract Bible")
    personas_avail = PersonaSystem.get_available_personas()
    da_persona_key = st.selectbox("🎭 Persona cho Extract", personas_avail, key="da_persona_select")
    ext_persona = PersonaSystem.get_persona(da_persona_key)

    st.checkbox(
        "⚠️ Tôi hiểu: Bắt đầu phân tích sẽ **xóa toàn bộ** Bible entries đã gắn với chương này (source_chapter = chương đang chọn) trước khi chạy extract.",
        key="da_confirm_delete_bible_chapter",
    )
    uid = getattr(st.session_state.get("user"), "id", None) or ""
    uem = getattr(st.session_state.get("user"), "email", None) or ""
    can_write = check_permission(uid, uem, project_id, "write")
    if st.session_state.get("da_confirm_delete_bible_chapter") and can_write:
        if st.button("▶️ Bắt đầu phân tích", type="primary", key="da_extract_start_btn"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_bible",
                label=f"Extract Bible chương {chap_num}",
                payload={"chapter_number": chap_num, "persona_key": da_persona_key, "exclude_existing": False},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                st.rerun()
            else:
                st.error("Không tạo được job.")
    if can_write:
        if st.button("🔄 Cập nhật (chỉ gợi ý mới)", key="da_extract_update_btn"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_bible",
                label=f"Extract Bible chương {chap_num} (chỉ mới)",
                payload={"chapter_number": chap_num, "persona_key": da_persona_key, "exclude_existing": True},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.rerun()
            else:
                st.error("Không tạo được job.")
    if not can_write:
        st.warning("Chỉ thành viên có quyền ghi mới được thực hiện.")

    # --- Section 2: Relation ---
    st.markdown("---")
    st.subheader("🔗 Relation")
    st.info("💡 Run Extract Bible first for better relations. Jobs run in background; see Background Jobs tab.")
    st.checkbox(
        "⚠️ Tôi hiểu: Gợi ý quan hệ sẽ **xóa các quan hệ** giữa các thực thể thuộc chương này trước khi gợi ý lại.",
        key="da_confirm_delete_relation_chapter",
    )
    if st.session_state.get("da_confirm_delete_relation_chapter") and can_write:
        if st.button("🔄 Gợi ý quan hệ từ nội dung chương", key="da_suggest_relations"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_relation",
                label=f"Gợi ý quan hệ chương {chap_num}",
                payload={"chapter_number": chap_num, "only_new": False},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.rerun()
            else:
                st.error("Không tạo được job.")
    if can_write:
        if st.button("🔄 Cập nhật (chỉ gợi ý quan hệ mới)", key="da_relation_update_btn"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_relation",
                label=f"Cập nhật quan hệ chương {chap_num} (chỉ mới)",
                payload={"chapter_number": chap_num, "only_new": True},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.rerun()
            else:
                st.error("Không tạo được job.")

    # --- Section 3: Chunking ---
    st.markdown("---")
    st.subheader("✂️ Chunking")
    st.caption("Chunks từ chương được gắn chapter_id + arc_id, meta_json.source = data_analyze. Lưu mới sẽ xóa chunks cũ của chương. Chạy ngầm.")
    st.checkbox(
        "⚠️ Tôi hiểu: Phân tích Chunk sẽ **xóa toàn bộ** chunks đã gắn với chương này trước khi lưu mới.",
        key="da_confirm_delete_chunks_chapter",
    )
    if st.session_state.get("da_confirm_delete_chunks_chapter") and can_write:
        if st.button("📄 Phân tích Chunk", type="primary", key="da_chunk_analyze"):
            job_id = create_job(
                story_id=project_id,
                user_id=uid or None,
                job_type="data_analyze_chunk",
                label=f"Phân tích Chunk chương {chap_num}",
                payload={"chapter_number": chap_num},
                post_to_chat=False,
            )
            if job_id:
                threading.Thread(target=run_job_worker, args=(job_id,), daemon=True).start()
                st.toast("Queued. Check Background Jobs tab for status.")
                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                st.rerun()
            else:
                st.error("Không tạo được job.")
