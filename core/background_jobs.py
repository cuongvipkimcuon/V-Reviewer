# core/background_jobs.py - Background jobs (Data Analyze + Chat). "Background Jobs" tab shows status.
"""Create/update/list jobs. Workers run in thread; completion is not posted to chat (see Background Jobs tab)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Lazy init_services trong worker để tránh circular / streamlit khi import.


def create_job(
    story_id: str,
    user_id: Optional[str],
    job_type: str,
    label: str,
    payload: Optional[Dict[str, Any]] = None,
    post_to_chat: bool = True,
) -> Optional[str]:
    """Tạo bản ghi job (status=pending). Trả về job_id hoặc None nếu lỗi."""
    try:
        from config import init_services
        services = init_services()
        if not services:
            return None
        r = services["supabase"].table("background_jobs").insert({
            "story_id": story_id,
            "user_id": user_id or "",
            "job_type": job_type,
            "label": label,
            "payload": payload or {},
            "status": "pending",
            "post_to_chat": post_to_chat,
        }).execute()
        if r.data and len(r.data) > 0:
            return r.data[0].get("id")
    except Exception:
        pass
    return None


def update_job(
    job_id: str,
    status: str,
    result_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    try:
        from config import init_services
        services = init_services()
        if not services:
            return
        payload = {"status": status}
        if status in ("completed", "failed"):
            payload["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        if status == "running":
            payload["started_at"] = datetime.now(tz=timezone.utc).isoformat()
        if result_summary is not None:
            payload["result_summary"] = result_summary
        if error_message is not None:
            payload["error_message"] = error_message[:2000]
        services["supabase"].table("background_jobs").update(payload).eq("id", job_id).execute()
    except Exception:
        pass


def list_jobs(
    story_id: str,
    status_filter: Optional[str] = None,
    limit: int = 80,
) -> List[Dict[str, Any]]:
    """Lấy danh sách job của dự án, mới nhất trước. status_filter: pending | running | completed | failed hoặc None (tất cả)."""
    try:
        from config import init_services
        services = init_services()
        if not services:
            return []
        q = services["supabase"].table("background_jobs").select("*").eq("story_id", story_id).order("created_at", desc=True).limit(limit)
        if status_filter:
            q = q.eq("status", status_filter)
        r = q.execute()
        return list(r.data or [])
    except Exception:
        return []


def _post_completion_to_chat(project_id: str, user_id: Optional[str], label: str, success: bool, result_summary: Optional[str], error_message: Optional[str]) -> None:
    """Ghi tin hoàn thành vào chat_history để V Work hiện toast (metadata data_operation_completion)."""
    try:
        from config import init_services
        services = init_services()
        if not services:
            return
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        now_display = datetime.now().strftime("%d/%m/%Y %H:%M")
        if success:
            content = f"✅ **{label}** — Hoàn thành. {result_summary or ''} Thời gian: {now_display}."
        else:
            content = f"⚠️ **{label}** — Không hoàn thành. {error_message or result_summary or 'Lỗi không xác định.'} Thời gian: {now_display}."
        services["supabase"].table("chat_history").insert({
            "story_id": project_id,
            "user_id": str(user_id) if user_id else None,
            "role": "model",
            "content": content,
            "created_at": now_iso,
            "metadata": {"data_operation_completion": True, "success": success},
        }).execute()
    except Exception:
        pass


def run_job_worker(job_id: str) -> None:
    """
    Chạy trong thread: lấy job, set status=running, gọi worker theo job_type, cập nhật completed/failed, nếu post_to_chat thì ghi chat.
    job_type: data_analyze_bible | data_analyze_relation | data_analyze_timeline | data_analyze_chunk | data_operation_batch.
    """
    from config import init_services
    services = init_services()
    if not services:
        return
    supabase = services["supabase"]
    try:
        r = supabase.table("background_jobs").select("*").eq("id", job_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return
        job = r.data[0]
        story_id = job.get("story_id")
        user_id = job.get("user_id") or None
        job_type = (job.get("job_type") or "").strip()
        label = (job.get("label") or "Tác vụ").strip()
        payload = job.get("payload") or {}
        post_to_chat = bool(job.get("post_to_chat", True))

        update_job(job_id, "running")

        if job_type == "data_analyze_bible":
            _worker_data_analyze_bible(job_id, story_id, user_id, label, payload, post_to_chat, supabase)
        elif job_type == "data_analyze_relation":
            _worker_data_analyze_relation(job_id, story_id, user_id, label, payload, post_to_chat, supabase)
        elif job_type == "data_analyze_timeline":
            _worker_data_analyze_timeline(job_id, story_id, user_id, label, payload, post_to_chat, supabase)
        elif job_type == "data_analyze_chunk":
            _worker_data_analyze_chunk(job_id, story_id, user_id, label, payload, post_to_chat, supabase)
        else:
            update_job(job_id, "failed", error_message=f"job_type không hỗ trợ: {job_type}")
            if post_to_chat:
                _post_completion_to_chat(story_id, user_id, label, False, None, f"job_type không hỗ trợ: {job_type}")
    except Exception as e:
        err = str(e)[:1000]
        update_job(job_id, "failed", error_message=err)
        try:
            r = supabase.table("background_jobs").select("story_id, user_id, label, post_to_chat").eq("id", job_id).limit(1).execute()
            if r.data and r.data[0].get("post_to_chat"):
                _post_completion_to_chat(
                    r.data[0].get("story_id"), r.data[0].get("user_id"), r.data[0].get("label", "Tác vụ"), False, None, err
                )
        except Exception:
            pass


def _worker_data_analyze_bible(
    job_id: str, project_id: str, user_id: Optional[str], label: str, payload: Dict, post_to_chat: bool, supabase,
) -> None:
    from config import Config
    from persona import PersonaSystem
    from views.data_analyze import _run_extract_on_content, _get_existing_bible_entity_names_for_chapter

    chap_num = int(payload.get("chapter_number", 0))
    persona_key = payload.get("persona_key", "Writer")
    exclude_existing = bool(payload.get("exclude_existing", False))

    ch_row = supabase.table("chapters").select("id, content, title").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
    if not ch_row.data:
        update_job(job_id, "failed", error_message="Không tìm thấy chương")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Không tìm thấy chương")
        return
    content = (ch_row.data[0].get("content") or "").strip()
    if not content:
        update_job(job_id, "failed", error_message="Chương không có nội dung")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Chương không có nội dung")
        return

    ext_persona = PersonaSystem.get_persona(persona_key) or {}
    if not exclude_existing:
        existing = supabase.table("story_bible").select("id").eq("story_id", project_id).eq("source_chapter", chap_num).execute()
        if existing.data:
            ids = [r["id"] for r in existing.data if r.get("id")]
            if ids:
                supabase.table("story_bible").delete().in_("id", ids).execute()
    unique_items = _run_extract_on_content(content, ext_persona, project_id, chap_num, exclude_existing=exclude_existing, supabase=supabase)
    if not unique_items:
        update_job(job_id, "completed", result_summary="Không tìm thấy thực thể mới.")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, True, "Không tìm thấy thực thể mới.", None)
        return
    allowed_keys = Config.get_allowed_prefix_keys_for_extract()
    rows_to_save = []
    for item in unique_items:
        desc = (item.get("description") or "").strip()
        raw_name = item.get("entity_name", "Unknown")
        raw_type_str = (item.get("type") or "OTHER").strip()
        prefix_key = Config.resolve_prefix_for_bible(raw_type_str)
        final_name = f"[{prefix_key}] {raw_name}" if not raw_name.startswith("[") else raw_name
        if desc:
            rows_to_save.append({"final_name": final_name, "description": desc})
    if not rows_to_save:
        update_job(job_id, "completed", result_summary="Không có mục nào hợp lệ để lưu.")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, True, "Không có mục nào hợp lệ.", None)
        return
    count = 0
    for row in rows_to_save:
        supabase.table("story_bible").insert({
            "story_id": project_id,
            "entity_name": row["final_name"],
            "description": row["description"],
            "source_chapter": chap_num,
        }).execute()
        count += 1
    summary = f"Đã lưu {count} mục Bible."
    update_job(job_id, "completed", result_summary=summary)
    if post_to_chat:
        _post_completion_to_chat(project_id, user_id, label, True, summary, None)


def _worker_data_analyze_relation(
    job_id: str, project_id: str, user_id: Optional[str], label: str, payload: Dict, post_to_chat: bool, supabase,
) -> None:
    from views.data_analyze import suggest_relations, _get_entity_ids_for_chapter

    chap_num = int(payload.get("chapter_number", 0))
    only_new = bool(payload.get("only_new", False))
    ch_row = supabase.table("chapters").select("id, content").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
    if not ch_row.data:
        update_job(job_id, "failed", error_message="Không tìm thấy chương")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Không tìm thấy chương")
        return
    content = (ch_row.data[0].get("content") or "").strip()
    if not content:
        update_job(job_id, "failed", error_message="Chương không có nội dung")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Chương không có nội dung")
        return
    entity_ids = set(_get_entity_ids_for_chapter(project_id, chap_num, supabase))
    existing_set = set()
    if only_new:
        rels_exist = supabase.table("entity_relations").select("source_entity_id, target_entity_id, relation_type").eq("story_id", project_id).execute()
        for r in (rels_exist.data or []):
            s, t = r.get("source_entity_id"), r.get("target_entity_id")
            if s and t:
                existing_set.add((s, t, (r.get("relation_type") or "").strip()))
    else:
        if entity_ids:
            rels_exist = supabase.table("entity_relations").select("id, source_entity_id, target_entity_id").eq("story_id", project_id).execute()
            ids_to_del = [r["id"] for r in (rels_exist.data or []) if r.get("id") and (r.get("source_entity_id") in entity_ids or r.get("target_entity_id") in entity_ids)]
            if ids_to_del:
                supabase.table("entity_relations").delete().in_("id", ids_to_del).execute()
    rels = suggest_relations(content, project_id)
    saved = 0
    for item in (rels or []):
        if only_new and item.get("kind") == "relation":
            s, t = item.get("source_entity_id"), item.get("target_entity_id")
            key = (s, t, (item.get("relation_type") or "").strip())
            if key in existing_set:
                continue
        try:
            if item.get("kind") == "relation":
                supabase.table("entity_relations").insert({
                    "source_entity_id": item["source_entity_id"],
                    "target_entity_id": item["target_entity_id"],
                    "relation_type": item.get("relation_type", "liên quan"),
                    "description": item.get("description", "") or "",
                    "story_id": project_id,
                }).execute()
                saved += 1
            else:
                supabase.table("story_bible").update({"parent_id": item["parent_entity_id"]}).eq("id", item["entity_id"]).execute()
                saved += 1
        except Exception:
            pass
    summary = f"Đã lưu {saved} quan hệ / parent."
    update_job(job_id, "completed", result_summary=summary)
    if post_to_chat:
        _post_completion_to_chat(project_id, user_id, label, True, summary, None)


def _worker_data_analyze_timeline(
    job_id: str, project_id: str, user_id: Optional[str], label: str, payload: Dict, post_to_chat: bool, supabase,
) -> None:
    from ai_engine import extract_timeline_events_from_content

    chap_num = int(payload.get("chapter_number", 0))
    chapter_label = payload.get("chapter_label", "") or f"Chương {chap_num}"
    ch_row = supabase.table("chapters").select("id, content").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
    if not ch_row.data:
        update_job(job_id, "failed", error_message="Không tìm thấy chương")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Không tìm thấy chương")
        return
    content = (ch_row.data[0].get("content") or "").strip()
    chapter_id = ch_row.data[0].get("id")
    if not content:
        update_job(job_id, "failed", error_message="Chương không có nội dung")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Chương không có nội dung")
        return
    old = supabase.table("timeline_events").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
    if old.data:
        ids = [r["id"] for r in old.data if r.get("id")]
        if ids:
            supabase.table("timeline_events").delete().in_("id", ids).execute()
    events = extract_timeline_events_from_content(content, chapter_label)
    saved = 0
    for ev in (events or []):
        try:
            supabase.table("timeline_events").insert({
                "story_id": project_id,
                "chapter_id": chapter_id,
                "event_order": ev.get("event_order", 0),
                "title": (ev.get("title") or "").strip() or "Sự kiện",
                "description": (ev.get("description") or "").strip(),
                "raw_date": (ev.get("raw_date") or "").strip(),
                "event_type": ev.get("event_type", "event"),
            }).execute()
            saved += 1
        except Exception:
            pass
    summary = f"Đã lưu {saved} sự kiện timeline."
    update_job(job_id, "completed", result_summary=summary)
    if post_to_chat:
        _post_completion_to_chat(project_id, user_id, label, True, summary, None)


def _worker_data_analyze_chunk(
    job_id: str, project_id: str, user_id: Optional[str], label: str, payload: Dict, post_to_chat: bool, supabase,
) -> None:
    from ai_engine import analyze_split_strategy, execute_split_logic

    chap_num = int(payload.get("chapter_number", 0))
    ch_row = supabase.table("chapters").select("id, content, arc_id").eq("story_id", project_id).eq("chapter_number", chap_num).limit(1).execute()
    if not ch_row.data:
        update_job(job_id, "failed", error_message="Không tìm thấy chương")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Không tìm thấy chương")
        return
    content = (ch_row.data[0].get("content") or "").strip()
    chapter_id = ch_row.data[0].get("id")
    arc_id = ch_row.data[0].get("arc_id")
    if not content:
        update_job(job_id, "failed", error_message="Chương không có nội dung")
        if post_to_chat:
            _post_completion_to_chat(project_id, user_id, label, False, None, "Chương không có nội dung")
        return
    strategy = analyze_split_strategy(content, file_type="story", context_hint="Đoạn văn có ý nghĩa")
    chunks_list = execute_split_logic(content, strategy.get("split_type", "by_length"), strategy.get("split_value", "2000"))
    if not chunks_list:
        chunks_list = execute_split_logic(content, "by_length", "2000")
    edited = [{"title": c.get("title", ""), "content": (c.get("content") or "").strip(), "order": c.get("order", i + 1)} for i, c in enumerate(chunks_list)]
    old = supabase.table("chunks").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
    if old.data:
        ids = [r["id"] for r in old.data if r.get("id")]
        if ids:
            supabase.table("chunks").delete().in_("id", ids).execute()
    saved = 0
    for idx, chk in enumerate(edited):
        txt = chk.get("content", "").strip()
        if txt:
            row = {
                "story_id": project_id,
                "chapter_id": chapter_id,
                "arc_id": arc_id,
                "content": txt,
                "raw_content": txt,
                "meta_json": {"source": "data_analyze", "chapter": chap_num, "title": chk.get("title", "")},
                "sort_order": chk.get("order", idx + 1),
            }
            supabase.table("chunks").insert(row).execute()
            saved += 1
    summary = f"Đã lưu {saved} chunks."
    update_job(job_id, "completed", result_summary=summary)
    if post_to_chat:
        _post_completion_to_chat(project_id, user_id, label, True, summary, None)


def run_embedding_backfill(project_id: str, bible_limit: int = 50, chunks_limit: int = 50) -> Dict[str, int]:
    """
    Tìm story_bible và chunks có embedding null, gọi API embedding batch, cập nhật lại DB.
    Trả về {"bible_updated": n, "chunks_updated": m}.
    """
    out = {"bible_updated": 0, "chunks_updated": 0}
    if not project_id:
        return out
    try:
        from config import init_services
        from ai_engine import AIService
        services = init_services()
        if not services:
            return out
        supabase = services["supabase"]
    except Exception:
        return out
    try:
        r = supabase.table("story_bible").select("id, description").eq("story_id", project_id).is_("embedding", "NULL").limit(bible_limit).execute()
        rows_bible = list(r.data or [])
        if rows_bible:
            texts_bible = [(row.get("description") or "").strip() or "" for row in rows_bible]
            vectors_bible = AIService.get_embeddings_batch(texts_bible) if hasattr(AIService, "get_embeddings_batch") else []
            for i, row in enumerate(rows_bible):
                if i < len(vectors_bible) and vectors_bible[i]:
                    try:
                        supabase.table("story_bible").update({"embedding": vectors_bible[i]}).eq("id", row["id"]).execute()
                        out["bible_updated"] += 1
                    except Exception:
                        pass
    except Exception:
        pass
    try:
        r = supabase.table("chunks").select("id, content").eq("story_id", project_id).is_("embedding", "NULL").limit(chunks_limit).execute()
        rows_chunks = list(r.data or [])
        if rows_chunks:
            texts_chunks = [(row.get("content") or "").strip() or "" for row in rows_chunks]
            vectors_chunks = AIService.get_embeddings_batch(texts_chunks) if hasattr(AIService, "get_embeddings_batch") else []
            for i, row in enumerate(rows_chunks):
                if i < len(vectors_chunks) and vectors_chunks[i]:
                    try:
                        supabase.table("chunks").update({"embedding": vectors_chunks[i]}).eq("id", row["id"]).execute()
                        out["chunks_updated"] += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return out
