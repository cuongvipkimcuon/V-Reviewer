# core/data_operation_jobs.py - Chạy thao tác extract/update/delete Bible, Relation, Timeline, Chunking (ngầm) và gửi tin nhắn hoàn thành vào chat V Work.
"""Chạy trong thread sau khi user xác nhận. Ghi audit vào data_operation_log và tin nhắn hoàn thành vào chat_history."""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Tối đa 7 chương / lô để tránh tràn token khi fetch + xử lý.
MAX_CHAPTERS_PER_BATCH = 7

# Lazy imports inside run_data_operation để tránh circular / streamlit khi import top-level.


def run_data_operation(
    project_id: str,
    user_id: Optional[str],
    operation_type: str,
    target: str,
    chapter_number: int,
    user_request: str,
    post_completion_message: bool = True,
) -> None:
    """
    Thực thi thao tác dữ liệu (extract/update/delete × bible/relation/timeline/chunking) cho một chương.
    Chạy ngầm; khi xong ghi tin nhắn vào chat_history (trừ khi post_completion_message=False, dùng khi gọi từ batch).
    """
    from config import init_services, Config
    services = init_services()
    if not services:
        if post_completion_message:
            _post_completion_message(project_id, user_id, user_request, False, "Không kết nối được dịch vụ.")
        return
    supabase = services["supabase"]

    log_id = None
    try:
        try:
            r = supabase.table("data_operation_log").insert({
                "story_id": project_id,
                "user_id": user_id or "",
                "operation_type": operation_type,
                "target": target,
                "chapter_number": chapter_number,
                "user_request": (user_request or "")[:2000],
                "status": "running",
            }).execute()
            if r.data and len(r.data) > 0:
                log_id = r.data[0].get("id")
        except Exception:
            pass

        ch_row = supabase.table("chapters").select("id, content, title, arc_id").eq(
            "story_id", project_id
        ).eq("chapter_number", chapter_number).limit(1).execute()
        chapter = ch_row.data[0] if ch_row.data and len(ch_row.data) > 0 else None
        if not chapter:
            if post_completion_message:
                _post_completion_message(project_id, user_id, user_request, False, f"Không tìm thấy chương {chapter_number}.")
            _update_log_status(supabase, log_id, "failed", "Không tìm thấy chương")
            return

        chapter_id = chapter.get("id")
        content = (chapter.get("content") or "").strip()
        chapter_label = (chapter.get("title") or "").strip() or f"Chương {chapter_number}"

        if operation_type == "delete":
            _do_delete(supabase, project_id, target, chapter_number, chapter_id)
        elif operation_type in ("extract", "update"):
            if not content and target in ("bible", "relation", "timeline", "chunking"):
                if post_completion_message:
                    _post_completion_message(project_id, user_id, user_request, False, "Chương không có nội dung.")
                _update_log_status(supabase, log_id, "failed", "Chương không có nội dung")
                return
            if target == "bible":
                _do_extract_bible(supabase, project_id, chapter_number, content)
            elif target == "relation":
                _do_extract_relation(supabase, project_id, chapter_number, content)
            elif target == "timeline":
                _do_extract_timeline(supabase, project_id, chapter_id, chapter_number, chapter_label, content)
            elif target == "chunking":
                _do_extract_chunking(supabase, project_id, chapter_id, chapter.get("arc_id"), chapter_number, content)
            else:
                if post_completion_message:
                    _post_completion_message(project_id, user_id, user_request, False, f"Đối tượng không hỗ trợ: {target}")
                _update_log_status(supabase, log_id, "failed", f"target={target}")
                return
        else:
            if post_completion_message:
                _post_completion_message(project_id, user_id, user_request, False, f"Loại thao tác không hỗ trợ: {operation_type}")
            _update_log_status(supabase, log_id, "failed", f"operation_type={operation_type}")
            return

        _update_log_status(supabase, log_id, "completed")
        if post_completion_message:
            _post_completion_message(project_id, user_id, user_request, True, None)
    except Exception as e:
        err_msg = str(e)[:500]
        _update_log_status(supabase, log_id, "failed", err_msg)
        if post_completion_message:
            _post_completion_message(project_id, user_id, user_request, False, err_msg)
        raise


def run_data_operation_chunk(
    project_id: str,
    user_id: Optional[str],
    operation_type: str,
    target: str,
    chapter_numbers: List[int],
    user_request: str,
    post_completion_message: bool = False,
) -> List[str]:
    """
    Thực thi cùng một thao tác (op_type, target) cho nhiều chương trong một lô.
    Fetch tất cả chapter trong chapter_numbers bằng MỘT query, rồi xử lý từng chương (tránh tràn token: gọi với tối đa MAX_CHAPTERS_PER_BATCH chương).
    Returns: danh sách mô tả lỗi (rỗng nếu không lỗi).
    """
    if not chapter_numbers:
        return []
    from config import init_services
    services = init_services()
    if not services:
        if post_completion_message:
            _post_completion_message(project_id, user_id, user_request, False, "Không kết nối được dịch vụ.")
        return [f"batch {min(chapter_numbers)}-{max(chapter_numbers)}: không kết nối dịch vụ"]
    supabase = services["supabase"]
    failed: List[str] = []
    log_id = None
    batch_label = f"chương {min(chapter_numbers)}-{max(chapter_numbers)}" if len(chapter_numbers) > 1 else f"chương {chapter_numbers[0]}"
    try:
        try:
            r = supabase.table("data_operation_log").insert({
                "story_id": project_id,
                "user_id": user_id or "",
                "operation_type": operation_type,
                "target": target,
                "chapter_number": chapter_numbers[0],
                "user_request": (user_request or "")[:1800] + f" ({batch_label})",
                "status": "running",
            }).execute()
            if r.data and len(r.data) > 0:
                log_id = r.data[0].get("id")
        except Exception:
            pass

        ch_rows = supabase.table("chapters").select("id, content, title, arc_id, chapter_number").eq(
            "story_id", project_id
        ).in_("chapter_number", chapter_numbers).order("chapter_number").execute()
        chapters = (ch_rows.data or []) if ch_rows.data else []
        by_num = {int(c["chapter_number"]): c for c in chapters if c.get("chapter_number") is not None}

        for ch_num in chapter_numbers:
            chapter = by_num.get(ch_num)
            if not chapter:
                failed.append(f"{target} ch.{ch_num}: không tìm thấy chương")
                continue
            chapter_id = chapter.get("id")
            content = (chapter.get("content") or "").strip()
            chapter_label = (chapter.get("title") or "").strip() or f"Chương {ch_num}"
            arc_id = chapter.get("arc_id")
            try:
                if operation_type == "delete":
                    _do_delete(supabase, project_id, target, ch_num, chapter_id)
                elif operation_type in ("extract", "update"):
                    if not content and target in ("bible", "relation", "timeline", "chunking"):
                        failed.append(f"{target} ch.{ch_num}: chương không có nội dung")
                        continue
                    if target == "bible":
                        _do_extract_bible(supabase, project_id, ch_num, content)
                    elif target == "relation":
                        _do_extract_relation(supabase, project_id, ch_num, content)
                    elif target == "timeline":
                        _do_extract_timeline(supabase, project_id, chapter_id, ch_num, chapter_label, content)
                    elif target == "chunking":
                        _do_extract_chunking(supabase, project_id, chapter_id, arc_id, ch_num, content)
                    else:
                        failed.append(f"{target} ch.{ch_num}: đối tượng không hỗ trợ")
                else:
                    failed.append(f"ch.{ch_num}: loại thao tác không hỗ trợ {operation_type}")
            except Exception as e:
                failed.append(f"{target} ch.{ch_num}: {str(e)[:150]}")

        _update_log_status(supabase, log_id, "failed" if failed else "completed", "; ".join(failed[:3]) if failed else None)
        if post_completion_message and not failed:
            _post_completion_message(project_id, user_id, user_request, True, None)
        elif post_completion_message and failed:
            _post_completion_message(project_id, user_id, user_request, False, "; ".join(failed[:3]))
    except Exception as e:
        err_msg = str(e)[:500]
        _update_log_status(supabase, log_id, "failed", err_msg)
        failed.append(f"batch {batch_label}: {err_msg}")
    return failed


def _update_log_status(supabase, log_id, status: str, error_message: Optional[str] = None):
    if not log_id:
        return
    try:
        payload = {"status": status}
        if status in ("completed", "failed"):
            payload["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        if error_message:
            payload["error_message"] = error_message
        supabase.table("data_operation_log").update(payload).eq("id", log_id).execute()
    except Exception:
        pass


def _post_completion_message(project_id: str, user_id: Optional[str], user_request: str, success: bool, error_detail: Optional[str]):
    from config import init_services
    services = init_services()
    if not services:
        return
    supabase = services["supabase"]
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    now_display = datetime.now().strftime("%d/%m/%Y %H:%M")
    if success:
        content = f"✅ Đã thực hiện xong yêu cầu của bạn: **{user_request}**. Thời gian: {now_display}."
    else:
        content = f"⚠️ Không thể hoàn thành yêu cầu: **{user_request}**. {error_detail or 'Lỗi không xác định.'} Thời gian: {now_display}."
    try:
        supabase.table("chat_history").insert({
            "story_id": project_id,
            "user_id": str(user_id) if user_id else None,
            "role": "model",
            "content": content,
            "created_at": now_iso,
            "metadata": {"data_operation_completion": True, "success": success},
        }).execute()
    except Exception:
        pass


def _group_into_chunked_batches(steps: list, max_per_batch: int = MAX_CHAPTERS_PER_BATCH) -> List[dict]:
    """
    Gom steps thành các lô tối đa max_per_batch chương. Mỗi phần tử: {"operation_type", "target", "chapter_numbers": [1,2,...,7]}.
    Khoảng rộng chia tuần tự (lô 1, lô 2, ...).
    """
    batch_items: List[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        op_type = step.get("operation_type") or "extract"
        target = step.get("target") or "bible"
        ch_range = step.get("chapter_range")
        ch_num = step.get("chapter_number")
        if ch_range and isinstance(ch_range, (list, tuple)) and len(ch_range) >= 2:
            try:
                start, end = int(ch_range[0]), int(ch_range[1])
                start, end = min(start, end), max(start, end)
                nums = list(range(start, end + 1))
            except (ValueError, TypeError):
                nums = [int(ch_num)] if ch_num is not None else []
        elif ch_num is not None:
            nums = [int(ch_num)]
        else:
            continue
        for i in range(0, len(nums), max_per_batch):
            batch_items.append({
                "operation_type": op_type,
                "target": target,
                "chapter_numbers": nums[i : i + max_per_batch],
            })
    return batch_items


def _run_one_target_sequential(
    project_id: str,
    user_id: Optional[str],
    op_type: str,
    target: str,
    list_of_chapter_lists: List[List[int]],
    user_request: str,
) -> Tuple[int, List[str]]:
    """Chạy tuần tự các lô cho một (op_type, target). Returns (total_chapters_done, failed_messages)."""
    total = 0
    all_failed: List[str] = []
    for chapter_numbers in list_of_chapter_lists:
        total += len(chapter_numbers)
        failed = run_data_operation_chunk(
            project_id=project_id,
            user_id=user_id,
            operation_type=op_type,
            target=target,
            chapter_numbers=chapter_numbers,
            user_request=user_request,
            post_completion_message=False,
        )
        all_failed.extend(failed)
    return total, all_failed


def run_data_operations_batch(
    project_id: str,
    user_id: Optional[str],
    steps: list,
    user_request: str,
    job_id: Optional[str] = None,
) -> None:
    """
    Chạy thao tác (extract/update/delete × bible/relation/timeline/chunking) theo LÔ.
    If job_id is passed (from Chat), updates background_jobs for the Background Jobs tab.
    Vẫn ghi tin hoàn thành vào chat_history để V Work hiện toast.
    """
    if not steps:
        _post_completion_message(project_id, user_id, user_request, False, "Không có bước nào để thực hiện.")
        if job_id:
            try:
                from core.background_jobs import update_job
                update_job(job_id, "failed", error_message="Không có bước nào để thực hiện.")
            except Exception:
                pass
        return
    if job_id:
        try:
            from core.background_jobs import update_job
            update_job(job_id, "running")
        except Exception:
            pass
    batch_items = _group_into_chunked_batches(steps)
    if not batch_items:
        _post_completion_message(project_id, user_id, user_request, False, "Không có bước hợp lệ (cần chapter_number hoặc chapter_range).")
        if job_id:
            try:
                from core.background_jobs import update_job
                update_job(job_id, "failed", error_message="Không có bước hợp lệ (cần chapter_number hoặc chapter_range).")
            except Exception:
                pass
        return

    # Gom theo (op_type, target): mỗi key có danh sách các lô chapter_numbers
    grouped: dict = {}
    for item in batch_items:
        key = (item["operation_type"], item["target"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(item["chapter_numbers"])

    all_failed: List[str] = []
    total_ops = 0
    max_workers = min(4, len(grouped))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_one_target_sequential,
                project_id,
                user_id,
                op_type,
                target,
                list_of_chapter_lists,
                user_request,
            ): (op_type, target)
            for (op_type, target), list_of_chapter_lists in grouped.items()
        }
        for future in as_completed(futures):
            try:
                count, failed = future.result()
                total_ops += count
                all_failed.extend(failed)
            except Exception as e:
                op_type, target = futures[future]
                all_failed.append(f"{op_type} {target}: {str(e)[:200]}")

    from config import init_services
    services = init_services()
    if not services:
        if job_id:
            try:
                from core.background_jobs import update_job
                update_job(job_id, "failed", error_message="Không kết nối được dịch vụ.")
            except Exception:
                pass
        return
    if job_id:
        try:
            from core.background_jobs import update_job
            summary = f"{total_ops} thao tác" + (f", {len(all_failed)} lỗi" if all_failed else "")
            update_job(
                job_id,
                "failed" if all_failed and total_ops == 0 else "completed",
                result_summary=summary,
                error_message="; ".join(all_failed[:5]) if all_failed else None,
            )
        except Exception:
            pass


def _do_delete(supabase, project_id: str, target: str, chapter_number: int, chapter_id):
    if target == "bible":
        r = supabase.table("story_bible").select("id").eq("story_id", project_id).eq("source_chapter", chapter_number).execute()
        ids = [x["id"] for x in (r.data or []) if x.get("id")]
        if ids:
            supabase.table("story_bible").delete().in_("id", ids).execute()
    elif target == "relation":
        entity_ids = _get_entity_ids_for_chapter(supabase, project_id, chapter_number)
        if entity_ids:
            rels = supabase.table("entity_relations").select("id, source_entity_id, target_entity_id").eq("story_id", project_id).execute()
            ids_to_del = [r["id"] for r in (rels.data or []) if r.get("id") and (r.get("source_entity_id") in entity_ids or r.get("target_entity_id") in entity_ids)]
            if ids_to_del:
                supabase.table("entity_relations").delete().in_("id", ids_to_del).execute()
    elif target == "timeline" and chapter_id:
        r = supabase.table("timeline_events").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
        ids = [x["id"] for x in (r.data or []) if x.get("id")]
        if ids:
            supabase.table("timeline_events").delete().in_("id", ids).execute()
    elif target == "chunking" and chapter_id:
        r = supabase.table("chunks").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
        ids = [x["id"] for x in (r.data or []) if x.get("id")]
        if ids:
            supabase.table("chunks").delete().in_("id", ids).execute()


def _get_entity_ids_for_chapter(supabase, project_id: str, chap_num: int):
    try:
        r = supabase.table("story_bible").select("id").eq("story_id", project_id).eq("source_chapter", chap_num).execute()
        return [row["id"] for row in (r.data or []) if row.get("id")]
    except Exception:
        return []


def _do_extract_bible(supabase, project_id: str, chap_num: int, content: str):
    from views.data_analyze import _run_extract_on_content
    from persona import PersonaSystem
    from config import Config

    try:
        personas = PersonaSystem.get_available_personas()
        ext_persona = PersonaSystem.get_persona(personas[0] if personas else "Writer")
    except Exception:
        ext_persona = {"extractor_prompt": "Trích xuất các thực thể quan trọng từ nội dung trên (nhân vật, địa điểm, sự kiện, đồ vật)."}

    r = supabase.table("story_bible").select("id").eq("story_id", project_id).eq("source_chapter", chap_num).execute()
    ids = [x["id"] for x in (r.data or []) if x.get("id")]
    if ids:
        supabase.table("story_bible").delete().in_("id", ids).execute()

    items = _run_extract_on_content(content, ext_persona, project_id, chap_num, exclude_existing=False, supabase=supabase)
    if not items:
        return
    rows_to_save = []
    for item in items:
        desc = (item.get("description") or "").strip()
        raw_name = (item.get("entity_name") or "Unknown").strip()
        raw_type_str = (item.get("type") or "OTHER").strip()
        prefix_key = Config.resolve_prefix_for_bible(raw_type_str)
        final_name = f"[{prefix_key}] {raw_name}" if not raw_name.startswith("[") else raw_name
        if desc:
            rows_to_save.append({"final_name": final_name, "description": desc})
    if not rows_to_save:
        return
    for row in rows_to_save:
        payload = {
            "story_id": project_id,
            "entity_name": row["final_name"],
            "description": row["description"],
            "source_chapter": chap_num,
        }
        supabase.table("story_bible").insert(payload).execute()


def _do_extract_relation(supabase, project_id: str, chap_num: int, content: str):
    from ai_engine import suggest_relations

    entity_ids = _get_entity_ids_for_chapter(supabase, project_id, chap_num)
    if entity_ids:
        rels_exist = supabase.table("entity_relations").select("id, source_entity_id, target_entity_id").eq("story_id", project_id).execute()
        ids_to_del = [
            r["id"] for r in (rels_exist.data or [])
            if r.get("id") and (r.get("source_entity_id") in entity_ids or r.get("target_entity_id") in entity_ids)
        ]
        if ids_to_del:
            supabase.table("entity_relations").delete().in_("id", ids_to_del).execute()
    rels = suggest_relations(content, project_id)
    for item in (rels or []):
        if item.get("kind") == "relation":
            try:
                supabase.table("entity_relations").insert({
                    "source_entity_id": item["source_entity_id"],
                    "target_entity_id": item["target_entity_id"],
                    "relation_type": item.get("relation_type", "liên quan"),
                    "description": (item.get("description") or "") or "",
                    "story_id": project_id,
                }).execute()
            except Exception:
                pass
        elif item.get("kind") == "parent" and item.get("entity_id") and item.get("parent_entity_id"):
            try:
                supabase.table("story_bible").update({"parent_id": item["parent_entity_id"]}).eq("id", item["entity_id"]).execute()
            except Exception:
                pass


def _do_extract_timeline(supabase, project_id: str, chapter_id, chapter_number: int, chapter_label: str, content: str):
    from ai_engine import extract_timeline_events_from_content

    r = supabase.table("timeline_events").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
    ids = [x["id"] for x in (r.data or []) if x.get("id")]
    if ids:
        supabase.table("timeline_events").delete().in_("id", ids).execute()
    events = extract_timeline_events_from_content(content, chapter_label)
    for ev in (events or []):
        payload = {
            "story_id": project_id,
            "chapter_id": chapter_id,
            "event_order": ev.get("event_order", 0),
            "title": (ev.get("title") or "").strip() or "Sự kiện",
            "description": (ev.get("description") or "").strip(),
            "raw_date": (ev.get("raw_date") or "").strip(),
            "event_type": ev.get("event_type", "event"),
        }
        supabase.table("timeline_events").insert(payload).execute()


def _do_extract_chunking(supabase, project_id: str, chapter_id, arc_id, chap_num: int, content: str):
    from ai_engine import analyze_split_strategy, execute_split_logic

    r = supabase.table("chunks").select("id").eq("story_id", project_id).eq("chapter_id", chapter_id).execute()
    ids = [x["id"] for x in (r.data or []) if x.get("id")]
    if ids:
        supabase.table("chunks").delete().in_("id", ids).execute()
    strategy = analyze_split_strategy(content, file_type="story", context_hint="Đoạn văn có ý nghĩa")
    chunks_list = execute_split_logic(content, strategy.get("split_type", "by_length"), strategy.get("split_value", "2000"))
    if not chunks_list:
        chunks_list = execute_split_logic(content, "by_length", "2000")
    edited = [{"title": c.get("title", ""), "content": (c.get("content") or "").strip(), "order": c.get("order", i + 1)} for i, c in enumerate(chunks_list or [])]
    for idx, chk in enumerate(edited):
        txt = chk.get("content", "").strip()
        if not txt:
            continue
        payload = {
            "story_id": project_id,
            "chapter_id": chapter_id,
            "arc_id": arc_id,
            "content": txt,
            "raw_content": txt,
            "meta_json": {"source": "data_operation_jobs", "chapter": chap_num, "title": chk.get("title", "")},
            "sort_order": chk.get("order", idx + 1),
        }
        supabase.table("chunks").insert(payload).execute()
