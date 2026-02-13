# views/relations_view.py - Quản lý quan hệ giữa các entity trong Bible
"""Tab Relations: Đề xuất quan hệ AI, danh sách quan hệ, xóa."""
import pandas as pd
import streamlit as st

from config import init_services
from ai_engine import suggest_relations
from utils.auth_manager import check_permission
from utils.cache_helpers import get_bible_list_cached, invalidate_cache_and_rerun


def render_relations_tab(project_id, persona):
    st.header("🔗 Relations")
    st.caption("Quan hệ giữa các thực thể trong Bible. AI gợi ý hoặc thêm/xóa thủ công.")

    if not project_id:
        st.info("📁 Chọn Project trước.")
        return

    st.session_state.setdefault("update_trigger", 0)
    services = init_services()
    if not services:
        st.warning("Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]
    bible_data_all = get_bible_list_cached(project_id, st.session_state.get("update_trigger", 0))
    id_to_name = {e["id"]: e.get("entity_name", "") for e in bible_data_all}

    # --- Đề xuất quan hệ mới: AI gợi ý ---
    with st.expander("🤖 Đề xuất quan hệ mới (AI)", expanded=bool(st.session_state.get("relation_suggestions"))):
        st.caption("Dán nội dung chương hoặc đoạn văn; AI sẽ so khớp với Bible và gợi ý quan hệ giữa thực thể hoặc gợi ý đặt parent.")
        relation_content = st.text_area(
            "Nội dung cần phân tích",
            value=st.session_state.get("relation_suggest_content", ""),
            height=120,
            placeholder="Dán đoạn/chương truyện có nhắc tên nhân vật, địa điểm, sự kiện...",
            key="relation_suggest_content_input",
            help="AI sẽ so khớp với Bible và gợi ý quan hệ hoặc đặt parent (nhân vật tiến hóa 1-n).",
        )
        if relation_content:
            st.session_state["relation_suggest_content"] = relation_content
        if st.button("🤖 Gợi ý quan hệ", key="relation_suggest_btn"):
            if relation_content and relation_content.strip():
                with st.spinner("AI đang phân tích..."):
                    suggestions = suggest_relations(relation_content.strip(), project_id)
                    st.session_state["relation_suggestions"] = suggestions
                if not suggestions:
                    st.info("Không tìm thấy đề xuất nào phù hợp.")
                else:
                    st.success(f"Tìm thấy {len(suggestions)} đề xuất.")
            else:
                st.warning("Nhập nội dung trước khi gợi ý.")

        pending = st.session_state.get("relation_suggestions") or []
        for i, item in enumerate(pending):
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
                        if st.button("✅ Xác nhận", key=f"rel_confirm_{i}"):
                            uid = getattr(st.session_state.get("user"), "id", None) or ""
                            uem = getattr(st.session_state.get("user"), "email", None) or ""
                            if check_permission(uid, uem, project_id, "write"):
                                try:
                                    payload = {
                                        "source_entity_id": item["source_entity_id"],
                                        "target_entity_id": item["target_entity_id"],
                                        "relation_type": item.get("relation_type", "liên quan"),
                                        "description": item.get("description", "") or "",
                                        "story_id": project_id,
                                    }
                                    supabase.table("entity_relations").insert(payload).execute()
                                    st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                    pending.pop(i)
                                    st.session_state["relation_suggestions"] = pending
                                    st.success("Đã lưu quan hệ.")
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"Lỗi: {ex}")
                            else:
                                st.warning("Chỉ Owner mới được thêm quan hệ.")
                    with c2:
                        if st.button("❌ Hủy", key=f"rel_reject_{i}"):
                            pending.pop(i)
                            st.session_state["relation_suggestions"] = pending
                            st.rerun()
                    st.markdown("---")
            else:
                # kind == "parent"
                ent_name = id_to_name.get(item.get("entity_id"), str(item.get("entity_id", "")))
                par_name = id_to_name.get(item.get("parent_entity_id"), str(item.get("parent_entity_id", "")))
                with st.container():
                    st.markdown(
                        f"**Đặt parent (1-n):** *{ent_name}* → gốc **{par_name}**  \n"
                        f"_{item.get('reason', '')}_"
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Xác nhận", key=f"parent_confirm_{i}"):
                            uid = getattr(st.session_state.get("user"), "id", None) or ""
                            uem = getattr(st.session_state.get("user"), "email", None) or ""
                            if check_permission(uid, uem, project_id, "write"):
                                try:
                                    supabase.table("story_bible").update({"parent_id": item["parent_entity_id"]}).eq("id", item["entity_id"]).execute()
                                    st.session_state["update_trigger"] = st.session_state.get("update_trigger", 0) + 1
                                    pending.pop(i)
                                    st.session_state["relation_suggestions"] = pending
                                    st.success("Đã đặt parent.")
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"Lỗi: {ex}")
                            else:
                                st.warning("Chỉ Owner mới được sửa.")
                    with c2:
                        if st.button("❌ Hủy", key=f"parent_reject_{i}"):
                            pending.pop(i)
                            st.session_state["relation_suggestions"] = pending
                            st.rerun()
                    st.markdown("---")

    # --- Tất cả quan hệ ---
    st.markdown("---")
    with st.expander("📋 Tất cả quan hệ", expanded=True):
        try:
            rel_res = supabase.table("entity_relations").select("*").eq("story_id", project_id).execute()
            all_rels = rel_res.data if rel_res and rel_res.data else []
        except Exception as e:
            st.error(f"Lỗi khi tải quan hệ: {e}")
            all_rels = []

        if not all_rels:
            st.info("Chưa có quan hệ nào trong Bible.")
        else:
            rows = []
            for r in all_rels:
                src_id = r.get("entity_id") or r.get("source_entity_id") or r.get("from_entity_id")
                tgt_id = r.get("target_entity_id") or r.get("to_entity_id")
                rtype = r.get("relation_type") or r.get("relation") or "—"
                rows.append(
                    {
                        "ID": r.get("id"),
                        "Source": id_to_name.get(src_id, f"ID {src_id}"),
                        "Target": id_to_name.get(tgt_id, f"ID {tgt_id}"),
                        "Type": rtype,
                    }
                )
            if rows:
                df_rels = pd.DataFrame(rows)
                st.dataframe(df_rels, use_container_width=True, hide_index=True)

            user_id = getattr(st.session_state.get("user"), "id", None) or ""
            user_email = getattr(st.session_state.get("user"), "email", None) or ""
            can_delete = check_permission(user_id, user_email, project_id, "delete")

            if not can_delete:
                st.caption("Bạn chỉ có quyền xem. Liên hệ Owner nếu muốn xóa quan hệ.")
            else:
                sel_ids = st.multiselect(
                    "Chọn quan hệ để xóa",
                    options=[row["ID"] for row in rows],
                    format_func=lambda rid: f"Relation #{rid}",
                    key="rel_multi_select",
                )
                col_del_rel, col_clear_rel = st.columns(2)
                with col_del_rel:
                    if sel_ids and st.button("🗑️ Xóa quan hệ đã chọn", use_container_width=True, key="rel_delete_selected"):
                        try:
                            supabase.table("entity_relations").delete().in_("id", sel_ids).execute()
                            st.success(f"Đã xóa {len(sel_ids)} quan hệ.")
                            invalidate_cache_and_rerun()
                        except Exception as ex:
                            st.error(f"Lỗi xóa: {ex}")
                with col_clear_rel:
                    confirm_clear_rel = st.checkbox(
                        "Tôi chắc chắn muốn xóa TẤT CẢ quan hệ",
                        key="rel_confirm_clear_all",
                    )
                    if st.button("💣 Xóa sạch tất cả quan hệ", type="secondary", use_container_width=True, key="rel_clear_all"):
                        if not confirm_clear_rel:
                            st.warning("Vui lòng tick xác nhận trước khi xóa toàn bộ quan hệ.")
                        else:
                            try:
                                supabase.table("entity_relations").delete().eq("story_id", project_id).execute()
                                st.success("Đã xóa sạch tất cả quan hệ.")
                                st.session_state["rel_confirm_clear_all"] = False
                                invalidate_cache_and_rerun()
                            except Exception as ex:
                                st.error(f"Lỗi xóa: {ex}")
