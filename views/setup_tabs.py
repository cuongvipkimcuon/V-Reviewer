# Tab Setup: Quản lý Bible Prefix Config và Personas
import streamlit as st

from config import Config, init_services
from persona import PersonaSystem, PERSONAS
from utils.cache_helpers import invalidate_cache_and_rerun


def render_prefix_setup():
    """Quản lý bảng bible_prefix_config: tên tiền tố (độc nhất) + mô tả."""
    st.subheader("📋 Bible Prefix Config")
    st.caption("Các loại thực thể và mô tả để AI Router và Extract phân loại. RULE và CHAT là 2 dòng cơ sở (không dùng cho entity trích từ chương).")
    try:
        services = init_services()
        if not services:
            st.warning("Không kết nối được dịch vụ.")
            return
        supabase = services["supabase"]
        r = supabase.table("bible_prefix_config").select("id, prefix_key, description, sort_order").order("sort_order").execute()
        rows = r.data if r.data else []
    except Exception as e:
        st.warning(f"Bảng bible_prefix_config chưa tồn tại hoặc lỗi: {e}. Chạy schema_prefix_persona.sql trong Supabase.")
        return
    for row in rows:
        prefix_key = (row.get("prefix_key") or "").strip().upper()
        with st.expander(f"[{row.get('prefix_key', '')}] {row.get('description', '')[:50]}..."):
            st.text_input("Prefix key", value=row.get("prefix_key", ""), key=f"pk_{row.get('id')}", disabled=True)
            st.text_area("Mô tả", value=row.get("description", ""), key=f"desc_{row.get('id')}", height=80)
            st.number_input("Thứ tự", value=int(row.get("sort_order") or 0), key=f"ord_{row.get('id')}", min_value=0)
            col_upd, col_del = st.columns(2)
            with col_upd:
                if st.button("💾 Cập nhật", key=f"upd_{row.get('id')}"):
                    try:
                        supabase.table("bible_prefix_config").update(
                            {
                                "description": st.session_state.get(
                                    f"desc_{row.get('id')}", row.get("description")
                                ),
                                "sort_order": st.session_state.get(
                                    f"ord_{row.get('id')}", row.get("sort_order")
                                ),
                            }
                        ).eq("id", row["id"]).execute()
                        st.success("Đã cập nhật.")
                        invalidate_cache_and_rerun()
                    except Exception as ex:
                        st.error(str(ex))
            with col_del:
                # Không cho phép xóa hai tiền tố hệ thống: RULE và CHAT
                if prefix_key in ("RULE", "CHAT"):
                    st.info("Tiền tố hệ thống (RULE/CHAT) không thể xóa.")
                else:
                    if st.button("🗑️ Xóa tiền tố này", key=f"del_{row.get('id')}"):
                        try:
                            supabase.table("bible_prefix_config").delete().eq("id", row["id"]).execute()
                            st.success("Đã xóa tiền tố.")
                            invalidate_cache_and_rerun()
                        except Exception as ex:
                            st.error(str(ex))
    st.markdown("---")
    st.subheader("Thêm tiền tố mới")
    with st.form("add_prefix"):
        new_key = st.text_input("Prefix key (VD: CHARACTER, LOCATION)", placeholder="VIẾT_HOA_KO_DẤU")
        new_desc = st.text_area("Mô tả")
        new_order = st.number_input("Thứ tự", value=len(rows) + 1, min_value=0)
        if st.form_submit_button("Thêm"):
            if new_key:
                key_clean = str(new_key).strip().upper().replace(" ", "_")
                try:
                    supabase.table("bible_prefix_config").insert({
                        "prefix_key": key_clean,
                        "description": new_desc or "",
                        "sort_order": int(new_order),
                    }).execute()
                    st.success("Đã thêm.")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
            else:
                st.warning("Nhập prefix key.")


def render_persona_setup():
    """Quản lý bảng personas: list, sửa, tạo mới."""
    st.subheader("🎭 Personas")
    st.caption("Persona dùng cho Chat và Project. Load từ DB, fallback file mặc định.")
    try:
        services = init_services()
        if not services:
            st.warning("Không kết nối được dịch vụ.")
            return
        supabase = services["supabase"]
        r = supabase.table("personas").select("*").order("key").execute()
        rows = r.data if r.data else []
    except Exception as e:
        st.warning(f"Bảng personas chưa tồn tại hoặc lỗi: {e}. Chạy schema_prefix_persona.sql trong Supabase.")
        return
    if not rows:
        st.info("Chưa có persona trong DB. Các persona mặc định đang dùng từ file. Chạy schema_prefix_persona.sql để seed.")
        for k, v in PERSONAS.items():
            st.markdown(f"- **{k}**: {v.get('role', '')}")
        return
    for row in rows:
        with st.expander(f"{row.get('icon', '')} {row.get('key', '')} — {row.get('role', '')[:40]}..."):
            st.text_input(
                "Key",
                value=row.get("key", ""),
                key=f"pkey_{row.get('id')}",
                disabled=row.get("is_builtin"),
            )
            st.text_input("Icon", value=row.get("icon", ""), key=f"picon_{row.get('id')}")
            st.text_input("Role", value=row.get("role", ""), key=f"prole_{row.get('id')}")
            st.number_input(
                "Temperature",
                value=float(row.get("temperature") or 0.7),
                key=f"ptemp_{row.get('id')}",
                min_value=0.0,
                max_value=1.0,
                step=0.1,
            )
            st.number_input(
                "Max tokens",
                value=int(row.get("max_tokens") or 5000),
                key=f"ptok_{row.get('id')}",
                min_value=500,
            )
            st.text_area(
                "Core instruction",
                value=row.get("core_instruction", ""),
                key=f"pinst_{row.get('id')}",
                height=120,
            )
            st.text_area(
                "Review prompt",
                value=row.get("review_prompt", ""),
                key=f"prev_{row.get('id')}",
                height=80,
            )
            st.text_area(
                "Extractor prompt",
                value=row.get("extractor_prompt", ""),
                key=f"pext_{row.get('id')}",
                height=80,
            )
            col_pupd, col_pdel = st.columns(2)
            with col_pupd:
                if st.button("💾 Cập nhật", key=f"pupd_{row.get('id')}"):
                    try:
                        supabase.table("personas").update(
                            {
                                "icon": st.session_state.get(f"picon_{row.get('id')}"),
                                "role": st.session_state.get(f"prole_{row.get('id')}"),
                                "temperature": st.session_state.get(f"ptemp_{row.get('id')}"),
                                "max_tokens": st.session_state.get(f"ptok_{row.get('id')}"),
                                "core_instruction": st.session_state.get(f"pinst_{row.get('id')}"),
                                "review_prompt": st.session_state.get(f"prev_{row.get('id')}"),
                                "extractor_prompt": st.session_state.get(f"pext_{row.get('id')}"),
                            }
                        ).eq("id", row["id"]).execute()
                        st.success("Đã cập nhật.")
                        invalidate_cache_and_rerun()
                    except Exception as ex:
                        st.error(str(ex))
            with col_pdel:
                # Chỉ cho phép xóa persona do user tạo (không phải builtin)
                if not row.get("is_builtin"):
                    if st.button("🗑️ Xóa persona này", key=f"pdel_{row.get('id')}"):
                        try:
                            supabase.table("personas").delete().eq("id", row["id"]).execute()
                            st.success("Đã xóa persona.")
                            invalidate_cache_and_rerun()
                        except Exception as ex:
                            st.error(str(ex))
    st.markdown("---")
    st.subheader("Tạo persona mới")
    with st.form("add_persona"):
        nkey = st.text_input("Key (VD: Writer)", placeholder="Tên duy nhất")
        nicon = st.text_input("Icon", value="✍️")
        nrole = st.text_input("Role")
        ntemp = st.number_input("Temperature", value=0.7, min_value=0.0, max_value=1.0, step=0.1)
        ntok = st.number_input("Max tokens", value=5000, min_value=500)
        ninst = st.text_area("Core instruction", height=100)
        nrev = st.text_area("Review prompt", height=60)
        nextr = st.text_area("Extractor prompt", height=60)
        if st.form_submit_button("Thêm"):
            if nkey:
                try:
                    supabase.table("personas").insert({
                        "key": nkey.strip(),
                        "icon": nicon or "✍️",
                        "role": nrole or "",
                        "temperature": float(ntemp),
                        "max_tokens": int(ntok),
                        "core_instruction": ninst or "",
                        "review_prompt": nrev or "",
                        "extractor_prompt": nextr or "",
                        "is_builtin": False,
                    }).execute()
                    st.success("Đã thêm persona.")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
            else:
                st.warning("Nhập key.")


def render_setup_tab():
    """Tab Setup: Prefix Config + Personas."""
    st.header("⚙️ Setup")
    t1, t2 = st.tabs(["Bible Prefix", "Personas"])
    with t1:
        render_prefix_setup()
    with t2:
        render_persona_setup()
