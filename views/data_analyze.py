# views/data_analyze.py - Tab Data Analyze: chọn chương, Extract Bible / Relation / Chunking độc lập
import json
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import Config, init_services
from ai_engine import (
    AIService,
    HybridSearch,
    generate_chapter_metadata,
    analyze_split_strategy,
    execute_split_logic,
    suggest_relations,
)
from utils.auth_manager import check_permission
from utils.cache_helpers import get_chapters_cached, get_bible_list_cached, invalidate_cache_and_rerun
from persona import PersonaSystem


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

    st.caption(f"Nội dung chương: {len(content)} ký tự. Các thao tác bên dưới thực hiện độc lập.")

    # --- Section 1: Extract Bible ---
    st.markdown("---")
    st.subheader("📥 Extract Bible")
    personas_avail = PersonaSystem.get_available_personas()
    da_persona_key = st.selectbox("🎭 Persona cho Extract", personas_avail, key="da_persona_select")
    ext_persona = PersonaSystem.get_persona(da_persona_key)

    if st.session_state.get("da_extract_started") and st.session_state.get("da_extract_chapter_num") == chap_num:
        items = st.session_state.get("da_temp_extracted_data")
        if items is None:
            # Đang chạy extract lần đầu sau khi bấm "Bắt đầu phân tích"
            prog = st.progress(0, text="Đang phân tích cấu trúc...")
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
                prog.progress(int((i + 1) / len(chunks) * 90), text=f"Đang đọc phần {i+1}/{len(chunks)}...")
                ext_prompt = f"""
NỘI DUNG (Phần {i+1}/{len(chunks)}):
{chunk_content}

NHIỆM VỤ: {ext_persona.get('extractor_prompt', 'Trích xuất các thực thể quan trọng từ nội dung trên.')}

⛔️ YÊU CẦU: Trả về JSON với key "items". Trường "type" phải là đúng MỘT trong: {prefix_list_str}. "description": tóm tắt dưới 50 từ.
Nếu không tìm thấy: {{ "items": [] }}. Chỉ trả về JSON."""
                try:
                    resp = AIService.call_openrouter(
                        messages=[{"role": "user", "content": ext_prompt}],
                        model=st.session_state.get("selected_model", Config.DEFAULT_MODEL),
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
            st.session_state["da_temp_extracted_data"] = all_items
            st.session_state["da_bible_saved"] = False
            prog.progress(100)
            st.rerun()
        items = st.session_state.get("da_temp_extracted_data") or []
        if items:
            unique_items_dict = {}
            for item in items:
                name = item.get("entity_name", "").strip()
                if name:
                    if name not in unique_items_dict or len(item.get("description", "")) > len(unique_items_dict[name].get("description", "")):
                        unique_items_dict[name] = item
            unique_items = list(unique_items_dict.values())
            st.success(f"✅ Tìm thấy {len(unique_items)} thực thể.")
            with st.expander("Xem trước", expanded=True):
                df = pd.DataFrame(unique_items)
                if "entity_name" in df.columns:
                    st.dataframe(df[["entity_name", "type", "description"]], use_container_width=True, hide_index=True)
            if not st.session_state.get("da_bible_saved"):
                if st.button("✅ Xác nhận Bible", type="primary", key="da_confirm_bible"):
                    uid = getattr(st.session_state.get("user"), "id", None) or ""
                    uem = getattr(st.session_state.get("user"), "email", None) or ""
                    if not check_permission(uid, uem, project_id, "write"):
                        st.warning("Chỉ Owner mới được lưu Bible.")
                    else:
                        prog = st.progress(0, text="Đang chuẩn bị...")
                        rows_to_save = []
                        for item in unique_items:
                            desc = (item.get("description") or "").strip()
                            raw_name = item.get("entity_name", "Unknown")
                            raw_type_str = (item.get("type") or "OTHER").strip()
                            prefix_key = Config.resolve_prefix_for_bible(raw_type_str)
                            final_name = f"[{prefix_key}] {raw_name}" if not raw_name.startswith("[") else raw_name
                            if desc:
                                rows_to_save.append({"final_name": final_name, "description": desc})
                        total = len(rows_to_save)
                        count = 0
                        if total > 0:
                            prog.progress(10, text="Đang embedding hàng loạt...")
                            texts = [r["description"] for r in rows_to_save]
                            vectors = AIService.get_embeddings_batch(texts)
                            prog.progress(60, text="Đang lưu Bible...")
                            for i, row in enumerate(rows_to_save):
                                vec = vectors[i] if i < len(vectors) else None
                                if vec:
                                    supabase.table("story_bible").insert({
                                        "story_id": project_id,
                                        "entity_name": row["final_name"],
                                        "description": row["description"],
                                        "embedding": vec,
                                        "source_chapter": chap_num,
                                    }).execute()
                                    count += 1
                                prog.progress(60 + int((i + 1) / total * 40))
                            st.session_state["da_bible_saved"] = True
                            st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                        prog.progress(100)
                        st.success(f"Đã lưu {count} mục Bible.")
                        st.rerun()
            else:
                st.success("Đã lưu Bible cho chương này.")
            if st.button("🔄 Làm lại Extract", key="da_retry_extract"):
                st.session_state.pop("da_extract_started", None)
                st.session_state.pop("da_temp_extracted_data", None)
                st.session_state.pop("da_bible_saved", None)
                st.session_state.pop("da_temp_relation_suggestions", None)
                st.rerun()
    else:
        if st.button("▶️ Bắt đầu phân tích", type="primary", key="da_extract_start_btn"):
            st.session_state["da_extract_started"] = True
            st.session_state["da_extract_chapter_num"] = chap_num
            st.session_state["da_temp_extracted_data"] = None
            st.session_state["da_bible_saved"] = False
            st.rerun()

    # --- Section 2: Relation ---
    st.markdown("---")
    st.subheader("🔗 Relation")
    st.info("💡 Nên thực hiện Extract Bible trước để gợi ý relation chính xác.")
    rel_pending = st.session_state.get("da_temp_relation_suggestions") or []

    if st.button("🔄 Gợi ý quan hệ từ nội dung chương", key="da_suggest_relations"):
        with st.spinner("Đang phân tích..."):
            try:
                rels = suggest_relations(content, project_id)
                st.session_state["da_temp_relation_suggestions"] = rels or []
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if rel_pending:
        try:
            bible_entries = get_bible_list_cached(project_id, st.session_state.get("update_trigger", 0))
            id_to_name = {e["id"]: e.get("entity_name", "") for e in bible_entries}
        except Exception:
            id_to_name = {}
        batch_a, batch_b = st.columns(2)
        with batch_a:
            if st.button("✅ Xác nhận tất cả", type="primary", key="da_rel_confirm_all"):
                uid = getattr(st.session_state.get("user"), "id", None) or ""
                uem = getattr(st.session_state.get("user"), "email", None) or ""
                if check_permission(uid, uem, project_id, "write"):
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
                        except Exception:
                            pass
                    st.session_state["da_temp_relation_suggestions"] = []
                    st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                    st.rerun()
        with batch_b:
            if st.button("❌ Hủy tất cả", key="da_rel_reject_all"):
                st.session_state["da_temp_relation_suggestions"] = []
                st.rerun()
        for i, item in enumerate(rel_pending):
            if item.get("kind") == "relation":
                src = id_to_name.get(item.get("source_entity_id"), str(item.get("source_entity_id", "")))
                tgt = id_to_name.get(item.get("target_entity_id"), str(item.get("target_entity_id", "")))
                st.markdown(f"**{src}** — *{item.get('relation_type', '')}* — **{tgt}**")
            else:
                ent = id_to_name.get(item.get("entity_id"), str(item.get("entity_id", "")))
                par = id_to_name.get(item.get("parent_entity_id"), str(item.get("parent_entity_id", "")))
                st.markdown(f"Parent: *{ent}* → **{par}**")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅", key=f"da_rel_ok_{i}"):
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
                        rel_pending.pop(i)
                        st.session_state["da_temp_relation_suggestions"] = rel_pending
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))
            with c2:
                if st.button("❌", key=f"da_rel_no_{i}"):
                    rel_pending.pop(i)
                    st.session_state["da_temp_relation_suggestions"] = rel_pending
                    st.rerun()
            st.markdown("---")

    # --- Section 3: Chunking ---
    st.markdown("---")
    st.subheader("✂️ Chunking")
    temp_chunks = st.session_state.get("da_temp_chunks")
    if temp_chunks is None:
        if st.button("📄 Phân tích Chunk", key="da_chunk_analyze"):
            with st.spinner("Đang phân tích..."):
                strategy = analyze_split_strategy(content, file_type="story", context_hint="Đoạn văn có ý nghĩa")
                chunks_list = execute_split_logic(content, strategy.get("split_type", "by_length"), strategy.get("split_value", "2000"))
                if not chunks_list:
                    chunks_list = execute_split_logic(content, "by_length", "2000")
                st.session_state["da_temp_chunks"] = chunks_list
                st.rerun()
    else:
        edited = []
        for i, c in enumerate(temp_chunks):
            with st.expander(f"Chunk {i+1}: {c.get('title','')[:40]}...", expanded=(i < 2)):
                new_content = st.text_area("Nội dung", value=c.get("content", ""), height=120, key=f"da_chunk_edit_{i}")
                edited.append({"title": c.get("title", ""), "content": new_content or c.get("content", ""), "order": c.get("order", i + 1)})
        st.session_state["da_temp_chunks"] = edited
        if st.button("✅ Xác nhận & Lưu Chunks", type="primary", key="da_chunk_confirm"):
            uid = getattr(st.session_state.get("user"), "id", None) or ""
            uem = getattr(st.session_state.get("user"), "email", None) or ""
            if not check_permission(uid, uem, project_id, "write"):
                st.warning("Chỉ Owner mới được lưu chunks.")
            else:
                ch_row = supabase.table("chapters").select("id, arc_id").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
                chapter_id = ch_row.data[0]["id"] if ch_row.data else None
                arc_id = ch_row.data[0].get("arc_id") if ch_row.data else None
                prog = st.progress(0, text="Đang embedding hàng loạt...")
                texts_to_embed = [chk.get("content", "").strip() for chk in edited]
                vectors = AIService.get_embeddings_batch(texts_to_embed)
                prog.progress(50, text="Đang lưu...")
                saved = 0
                for idx, chk in enumerate(edited):
                    txt = chk.get("content", "").strip()
                    if txt:
                        vec = vectors[idx] if idx < len(vectors) else None
                        payload = {
                            "story_id": project_id,
                            "chapter_id": chapter_id,
                            "arc_id": arc_id,
                            "content": txt,
                            "raw_content": txt,
                            "meta_json": {"source": "data_analyze", "chapter": chap_num, "title": chk.get("title", "")},
                            "sort_order": chk.get("order", idx + 1),
                        }
                        if vec:
                            payload["embedding"] = vec
                        supabase.table("chunks").insert(payload).execute()
                        saved += 1
                    prog.progress(50 + int((idx + 1) / len(edited) * 50))
                st.session_state.pop("da_temp_chunks", None)
                st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                st.success(f"Đã lưu {saved} chunks.")
                st.rerun()
        if st.button("↩️ Hủy / Làm lại", key="da_chunk_cancel"):
            st.session_state.pop("da_temp_chunks", None)
            st.rerun()
