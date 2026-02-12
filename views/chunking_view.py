# views/chunking_view.py - UI Chunking (Excel theo dòng, Word theo ngữ nghĩa) + Vector hóa
"""Chunking UI: Excel (by row), Word (semantic). Chunks được vector hóa và dùng reverse lookup trong flow chính."""
import streamlit as st
from datetime import datetime

from config import init_services
from ai_engine import AIService, suggest_relations
from utils.file_importer import UniversalLoader
from utils.auth_manager import check_permission


def _ensure_chunks_table(supabase):
    """Đảm bảo chunks table tồn tại (schema v6)."""
    try:
        supabase.table("chunks").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def render_chunking_tab(project_id):
    """Tab Chunking - Import Excel (theo dòng) và Word (theo ngữ nghĩa có gắn ngữ cảnh), vector hóa."""
    st.subheader("✂️ Chunking & Vector Store")
    st.caption("Excel: cắt theo dòng. Word: cắt theo đoạn ngữ nghĩa có ngữ cảnh. Chunks được vector hóa để search trong Chat.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    if not _ensure_chunks_table(supabase):
        st.warning("Bảng chunks chưa tồn tại. Chạy schema_v6_migration.sql trong Supabase.")
        return

    user = st.session_state.get("user")
    user_id = getattr(user, "id", None) if user else None
    user_email = getattr(user, "email", None) if user else None
    can_write = bool(
        project_id and user_id
        and check_permission(str(user_id), user_email or "", project_id, "write")
    )
    if not can_write:
        st.warning("Chỉ user có quyền ghi mới import chunk.")
        return

    current_arc_id = st.session_state.get("current_arc_id")
    can_delete = check_permission(str(user_id or ""), user_email or "", project_id, "delete")

    tab_excel, tab_word, tab_list = st.tabs(["📊 Excel (theo dòng)", "📄 Word (theo ngữ nghĩa)", "📋 Chunks đã lưu"])

    with tab_excel:
        st.markdown("#### Excel - Chunk theo dòng")
        st.caption("Mỗi dòng Excel = 1 chunk. Metadata: sheet_name, row_index, source_file.")
        try:
            uploaded = st.file_uploader("Chọn file Excel", type=["xlsx", "xls"], key="chunk_excel_upload")
            if uploaded:
                chunks, err = UniversalLoader.load_excel_as_chunks(uploaded)
                if err:
                    st.error(err)
                elif chunks:
                    st.success(f"Đã parse {len(chunks)} dòng thành chunks.")
                    preview = st.slider("Xem trước N chunk đầu", 1, min(20, len(chunks)), 5, key="excel_preview")
                    for i, c in enumerate(chunks[:preview]):
                        meta = c.get("meta_json") or {}
                        sm = meta.get("source_metadata", {})
                        with st.expander(f"Chunk {i+1}: {sm.get('sheet_name','')} row {sm.get('row_index','')}"):
                            st.text(c.get("content", "")[:500])
                    if st.button("💾 Import & Vector hóa (Excel)", type="primary", key="import_excel_chunks"):
                        with st.spinner("Đang tạo embedding và lưu chunks..."):
                            saved = 0
                            for i, c in enumerate(chunks):
                                content = c.get("content", "") or c.get("raw_content", "")
                                if not content.strip():
                                    continue
                                vec = AIService.get_embedding(content)
                                if vec:
                                    meta = c.get("meta_json") or {}
                                    meta["source_type"] = "excel_row"
                                    payload = {
                                        "story_id": project_id,
                                        "raw_content": content,
                                        "content": content,
                                        "meta_json": meta,
                                        "sort_order": i,
                                        "source_type": "excel_row",
                                    }
                                    try:
                                        payload["embedding"] = vec
                                    except Exception:
                                        pass
                                    if current_arc_id:
                                        payload["arc_id"] = current_arc_id
                                    try:
                                        supabase.table("chunks").insert(payload).execute()
                                        saved += 1
                                    except Exception as e:
                                        if "embedding" in str(e).lower() or "vector" in str(e).lower():
                                            payload.pop("embedding", None)
                                            try:
                                                supabase.table("chunks").insert(payload).execute()
                                                saved += 1
                                            except Exception:
                                                pass
                                        else:
                                            st.error(f"Lỗi chunk {i+1}: {e}")
                            st.success(f"Đã lưu {saved} chunks.")
                            st.rerun()
        except ImportError as e:
            st.error(f"Thiếu dependency: {e}")

    with tab_word:
        st.markdown("#### Word - Chunk theo ngữ nghĩa (có ngữ cảnh)")
        st.caption("AI tách theo đoạn văn có ý nghĩa, mỗi chunk gắn ngữ cảnh (heading/đoạn trước).")
        uploaded_word = st.file_uploader("Chọn file Word (.docx)", type=["docx"], key="chunk_word_upload")
        if uploaded_word:
            text, err = UniversalLoader.load(uploaded_word)
            if err:
                st.error(err)
            elif text:
                # Chunk theo paragraph có ngữ cảnh (đoạn trước + đoạn hiện tại)
                from ai_engine import analyze_split_strategy, execute_split_logic
                strategy = analyze_split_strategy(text, file_type="story", context_hint="Đoạn văn có ý nghĩa")
                semantic_chunks = execute_split_logic(text, strategy["split_type"], strategy["split_value"])
                if not semantic_chunks and text:
                    # Fallback: cắt theo độ dài 2000 ký tự có overlap ngữ cảnh
                    chunk_size = 2000
                    overlap = 200
                    semantic_chunks = []
                    start = 0
                    idx = 1
                    while start < len(text):
                        end = min(start + chunk_size, len(text))
                        part = text[start:end]
                        # Thêm ngữ cảnh: 100 ký tự trước
                        ctx_start = max(0, start - overlap)
                        context_prefix = text[ctx_start:start] if ctx_start < start else ""
                        full_content = (context_prefix + "\n\n[---]\n\n" + part) if context_prefix else part
                        semantic_chunks.append({
                            "title": f"Đoạn {idx}",
                            "content": full_content.strip(),
                            "order": idx
                        })
                        start = end - overlap
                        idx += 1

                if semantic_chunks:
                    st.success(f"Đã tách {len(semantic_chunks)} đoạn ngữ nghĩa.")
                    preview = st.slider("Xem trước N chunk", 1, min(10, len(semantic_chunks)), 3, key="word_preview")
                    for i, c in enumerate(semantic_chunks[:preview]):
                        with st.expander(f"Chunk {i+1}: {c.get('title','')}"):
                            st.text((c.get("content", "") or "")[:600])
                    if st.button("💾 Import & Vector hóa (Word)", type="primary", key="import_word_chunks"):
                        with st.spinner("Đang tạo embedding và lưu chunks..."):
                            saved = 0
                            for i, c in enumerate(semantic_chunks):
                                content = c.get("content", "") or ""
                                if not content.strip():
                                    continue
                                vec = AIService.get_embedding(content)
                                meta = {
                                    "source_metadata": {
                                        "source_file": getattr(uploaded_word, "name", "uploaded.docx"),
                                        "chunk_index": i + 1,
                                        "source_type": "word_semantic",
                                    },
                                    "source_type": "word_semantic",
                                }
                                payload = {
                                    "story_id": project_id,
                                    "raw_content": content,
                                    "content": content,
                                    "meta_json": meta,
                                    "sort_order": i,
                                    "source_type": "word_semantic",
                                }
                                try:
                                    payload["embedding"] = vec
                                except Exception:
                                    pass
                                if current_arc_id:
                                    payload["arc_id"] = current_arc_id
                                try:
                                    supabase.table("chunks").insert(payload).execute()
                                    saved += 1
                                except Exception as e:
                                    if "embedding" in str(e).lower():
                                        payload.pop("embedding", None)
                                        try:
                                            supabase.table("chunks").insert(payload).execute()
                                            saved += 1
                                        except Exception:
                                            pass
                                    else:
                                        st.error(f"Lỗi chunk {i+1}: {e}")
                            st.success(f"Đã lưu {saved} chunks Word.")
                            st.rerun()
            else:
                st.info("File rỗng hoặc không đọc được.")

    with tab_list:
        r = supabase.table("chunks").select("id, content, source_type, meta_json, arc_id").eq("story_id", project_id).order("sort_order").execute()
        chunks_list = r.data or []
        st.metric("Tổng chunks", len(chunks_list))
        for c in chunks_list:
            meta = c.get("meta_json") or {}
            sm = meta.get("source_metadata", meta) if isinstance(meta, dict) else {}
            label = sm.get("sheet_name", "") or sm.get("source_file", "") or c.get("source_type", "") or str(c.get("id", ""))[:8]
            with st.expander(f"Chunk: {label} — {c.get('content','')[:50]}...", expanded=False):
                st.text(c.get("content", "")[:500])
                if can_delete and st.button("🗑️ Xóa", key=f"chunk_del_{c.get('id')}"):
                    supabase.table("chunks").delete().eq("id", c["id"]).execute()
                    st.success("Đã xóa.")
                    st.rerun()
        st.markdown("---")
        with st.expander("💀 Danger Zone", expanded=False):
            st.markdown('<div class="danger-zone">', unsafe_allow_html=True)
            if can_delete and chunks_list:
                confirm = st.checkbox("Xóa sạch TẤT CẢ chunks", key="chunk_confirm_clear")
                if confirm and st.button("🗑️ Xóa sạch Chunks"):
                    supabase.table("chunks").delete().eq("story_id", project_id).execute()
                    st.success("Đã xóa sạch.")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
