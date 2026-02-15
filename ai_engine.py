# ai_engine.py - Router, Context, Rule Mining (AIService + context_helpers đã tách ra ai/)
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

import streamlit as st

from config import Config, init_services

from ai.service import AIService, _get_default_tool_model
from ai.context_helpers import get_mandatory_rules as _get_mandatory_rules, resolve_chapter_range as _resolve_chapter_range, get_entity_relations as _get_entity_relations
from ai.hybrid_search import HybridSearch, check_semantic_intent, search_chunks_vector
from ai.query_sql import VALID_QUERY_TARGETS, build_query_sql_context, infer_query_target
from ai.router import get_v7_reminder_message, is_multi_intent_request, is_multi_step_update_data_request, SmartAIRouter
from ai.evaluate import evaluate_step_outcome, replan_after_step
from ai.content import (
    suggest_relations,
    suggest_import_category,
    generate_arc_summary_from_chapters,
    generate_chapter_metadata,
    extract_timeline_events_from_content,
    get_file_sample,
    analyze_split_strategy,
    execute_split_logic,
)
from ai.rule_mining import RuleMiningSystem
from ai.utils import (
    cap_context_to_tokens,
    cap_chat_history_to_tokens,
    ROUTER_PLANNER_CHAT_HISTORY_MAX_TOKENS,
    get_chapter_list_for_router,
    parse_chapter_range_from_query,
    extract_prefix,
    get_prefix_key_from_entity_name,
    _get_prefix_section_order_and_labels,
    _filter_bible_by_chapter_range,
    format_bible_context_by_sections,
    get_bible_index,
    get_bible_entries,
    get_timeline_events,
)

try:
    from core.arc_service import ArcService
    from core.reverse_lookup import ReverseLookupAssembler
except ImportError:
    ArcService = None
    ReverseLookupAssembler = None


# ==========================================
# 📚 CONTEXT MANAGER (V5 + V6 Arc & Reverse Lookup)
# ==========================================
class ContextManager:
    """Quản lý context cho AI với khả năng kết hợp nhiều nguồn. V6: Arc scoping + Triangle assembler."""

    @staticmethod
    def _build_arc_scope_context(project_id: str, current_arc_id: Optional[str], session_state: Optional[Dict] = None) -> Tuple[str, int]:
        """
        V6 MODULE 1 & 3: Build [Past Arc Summaries] + [Current Arc] for Sequential/Standalone.
        Global Bible is still injected via get_mandatory_rules and search_bible below.
        Returns (text, estimated_tokens).
        """
        if not ArcService or not current_arc_id:
            return "", 0
        arc = ArcService.get_arc(current_arc_id)
        if not arc:
            return "", 0
        parts = []
        scope = ArcService.get_scope_for_search(project_id, current_arc_id)
        if scope.get("scope_type") == ArcService.ARC_TYPE_SEQUENTIAL and scope.get("arc_summaries"):
            parts.append("[PAST ARC SUMMARIES - Timeline Inheritance]")
            for a in scope["arc_summaries"]:
                parts.append("- ARC: %s\n  Summary: %s" % (a.get("name", ""), (a.get("summary") or "").strip() or "(none)"))
            parts.append("")
        parts.append("[MACRO CONTEXT - ARC: %s]" % (arc.get("name") or "Current"))
        parts.append("Summary: %s" % ((arc.get("summary") or "").strip() or "(none)"))
        text = "\n".join(parts)
        return text, AIService.estimate_tokens(text)

    @staticmethod
    def build_context_with_chunk_reverse_lookup(
        project_id: str,
        chunk_ids: List[str],
        current_arc_id: Optional[str],
        token_limit: int = 12000,
    ) -> Tuple[str, List[str], int]:
        """
        V6 MODULE 3: Assemble context from chunk IDs using Triangle (Macro/Meso/Micro).
        Optionally prepend arc scope. Returns (full_context, sources, total_tokens).
        """
        context_parts = []
        sources = []
        total_tokens = 0
        if ArcService and current_arc_id:
            arc_scope, t = ContextManager._build_arc_scope_context(project_id, current_arc_id, None)
            if arc_scope:
                context_parts.append(arc_scope)
                total_tokens += t
        if ReverseLookupAssembler and chunk_ids:
            assembled, chunk_sources = ReverseLookupAssembler.assemble_from_chunks(chunk_ids, token_limit=token_limit)
            if assembled:
                context_parts.append("[REVERSE LOOKUP - Micro to Macro Evidence]\n" + assembled)
                total_tokens += AIService.estimate_tokens(assembled)
                sources.extend(chunk_sources)
        return "\n\n".join(context_parts), sources, total_tokens

    @staticmethod
    def get_entity_relations(entity_id: Any, project_id: str) -> str:
        """Ủy quyền cho ai.context_helpers.get_entity_relations."""
        return _get_entity_relations(entity_id, project_id)

    # Giới hạn token khi load nhiều chương (ưu tiên summary nếu vượt)
    DEFAULT_CHAPTER_TOKEN_LIMIT = 60000

    @staticmethod
    def _resolve_chapter_range(
        project_id: str,
        chapter_range_mode: Optional[str],
        chapter_range_count: int,
        chapter_range: Optional[List[int]],
    ) -> Optional[Tuple[int, int]]:
        """Ủy quyền cho ai.context_helpers.resolve_chapter_range."""
        return _resolve_chapter_range(project_id, chapter_range_mode, chapter_range_count, chapter_range)

    @staticmethod
    def load_chapters_by_range(
        project_id: str,
        start: int,
        end: int,
        token_limit: int = 60000,
    ) -> Tuple[str, List[str]]:
        """Load chương theo khoảng chapter_number; có summary và art_style; nếu vượt token_limit thì ưu tiên summary cho chương cũ, full content cho chương đang bàn (cuối)."""
        try:
            services = init_services()
            if not services:
                return "", []
            supabase = services["supabase"]
            r = supabase.table("chapters").select("*").eq(
                "story_id", project_id
            ).gte("chapter_number", start).lte("chapter_number", end).order(
                "chapter_number"
            ).execute()
            rows = r.data if r.data else []
        except Exception as e:
            print(f"load_chapters_by_range error: {e}")
            return "", []

        full_text = ""
        loaded_sources = []
        total_tokens = 0
        focus_idx = len(rows) - 1 if rows else -1

        for i, item in enumerate(rows):
            title = item.get("title") or f"Chương {item.get('chapter_number', i+1)}"
            content = item.get("content") or ""
            summary = item.get("summary") or ""
            art_style = item.get("art_style") or ""
            use_full = (token_limit <= 0 or total_tokens < token_limit) or (i == focus_idx)
            block = f"\n\n=== 📄 {title} ===\n"
            if summary:
                block += f"[Summary]: {summary}\n"
            if art_style:
                block += f"[Art style]: {art_style}\n"
            if use_full and content:
                block += f"[Content]:\n{content}\n"
            elif summary and not use_full:
                block += f"(Chỉ tóm tắt do giới hạn token.)\n"
            full_text += block
            loaded_sources.append(f"📄 {title}")
            total_tokens += AIService.estimate_tokens(block)

        return full_text, loaded_sources

    @staticmethod
    def load_full_content(
        file_names: List[str],
        project_id: str,
        token_limit: int = 60000,
        focus_chapter_name: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        """Load nội dung file/chương; thêm summary và art_style; nếu vượt token_limit thì ưu tiên summary, full content cho chương focus."""
        if not file_names:
            return "", []

        try:
            services = init_services()
            supabase = services["supabase"]
        except Exception:
            return "", []

        full_text = ""
        loaded_sources = []
        total_tokens = 0
        rows_with_meta = []

        for name in file_names:
            try:
                res = supabase.table("chapters").select("*").eq(
                    "story_id", project_id
                ).ilike("title", f"%{name}%").execute()
            except Exception:
                res = type("Res", (), {"data": None})()

            if res.data and len(res.data) > 0:
                item = res.data[0]
                item["_name"] = name
                item["_is_focus"] = (focus_chapter_name and focus_chapter_name in (item.get("title") or ""))
                rows_with_meta.append(item)
            else:
                try:
                    res_bible = supabase.table("story_bible").select(
                        "entity_name, description"
                    ).eq("story_id", project_id).ilike("entity_name", f"%{name}%").execute()
                    if res_bible.data and len(res_bible.data) > 0:
                        item = res_bible.data[0]
                        full_text += f"\n\n=== ⚠️ BIBLE SUMMARY: {item.get('entity_name', name)} ===\n{item.get('description', '')}\n"
                        loaded_sources.append(f"🗂️ {item.get('entity_name', name)} (Summary)")
                except Exception:
                    pass

        for item in rows_with_meta:
            title = item.get("title") or f"Chương {item.get('chapter_number')}"
            content = item.get("content") or ""
            summary = item.get("summary") or ""
            art_style = item.get("art_style") or ""
            is_focus = item.get("_is_focus", False)
            use_full = token_limit <= 0 or total_tokens + AIService.estimate_tokens(content) <= token_limit or is_focus
            block = f"\n\n=== 📄 SOURCE FILE/CHAP: {title} ===\n"
            if summary:
                block += f"[Summary]: {summary}\n"
            if art_style:
                block += f"[Art style]: {art_style}\n"
            if use_full and content:
                block += f"[Content]:\n{content}\n"
            elif summary:
                block += "(Chỉ tóm tắt do giới hạn token.)\n"
            full_text += block
            loaded_sources.append(f"📄 {title}")
            total_tokens += AIService.estimate_tokens(block)

        return full_text, loaded_sources

    @staticmethod
    def get_mandatory_rules(project_id: str) -> str:
        """Ủy quyền cho ai.context_helpers.get_mandatory_rules."""
        return _get_mandatory_rules(project_id)

    @staticmethod
    def build_context(
        router_result: Dict,
        project_id: str,
        persona: Dict,
        strict_mode: bool = False,
        current_arc_id: Optional[str] = None,
        session_state: Optional[Dict] = None,
        free_chat_mode: bool = False,
        max_context_tokens: Optional[int] = None,
    ) -> Tuple[str, List[str], int]:
        """Xây dựng context từ router result. max_context_tokens: giới hạn độ dài (từ Settings Context Size); None = không giới hạn."""
        context_parts = []
        sources = []
        total_tokens = 0

        persona_text = f"🎭 PERSONA: {persona['role']}\n{persona['core_instruction']}\n"
        context_parts.append(persona_text)
        total_tokens += AIService.estimate_tokens(persona_text)

        if free_chat_mode:
            rules_text = ContextManager.get_mandatory_rules(project_id)
            if rules_text:
                context_parts.append(rules_text)
                total_tokens += AIService.estimate_tokens(rules_text)
            free_instruction = "[CHẾ ĐỘ CHAT TỰ DO / CHAT PHIẾM]\nTrả lời như chatbot thông thường, dựa trên kiến thức tổng quát. Không bắt buộc dựa vào dữ liệu dự án (Bible/chunk/file); có thể trả lời mọi chủ đề."
            context_parts.append(free_instruction)
            total_tokens += AIService.estimate_tokens(free_instruction)
            sources.append("🌐 Chat tự do")
            return "\n".join(context_parts), sources, total_tokens

        # V6 MODULE 1: Arc scope (Past Arc Summaries + Current Arc)
        if current_arc_id and ArcService:
            arc_scope, arc_tokens = ContextManager._build_arc_scope_context(project_id, current_arc_id, session_state)
            if arc_scope:
                context_parts.append(arc_scope)
                total_tokens += arc_tokens
                sources.append("📐 Arc Scope")

        if strict_mode:
            strict_text = """
            \n\n‼️ CHẾ ĐỘ NGHIÊM NGẶT (STRICT MODE) ĐANG BẬT:
            1. CHỈ trả lời dựa trên thông tin có trong [CONTEXT].
            2. TUYỆT ĐỐI KHÔNG bịa đặt hoặc dùng kiến thức bên ngoài để điền vào chỗ trống.
            3. Nếu không tìm thấy thông tin trong Context, hãy trả lời: "Dữ liệu dự án chưa có thông tin này."
            4. Nếu User hỏi về "lịch sử", "cốt truyện", hãy ưu tiên trích xuất từ [KNOWLEDGE BASE].
            5. Không từ chối trả lời các dữ liệu thực tế (fact) chỉ vì tính cách Persona.
            """
            context_parts.append(strict_text)
            total_tokens += AIService.estimate_tokens(strict_text)

        rules_text = ContextManager.get_mandatory_rules(project_id)
        if rules_text:
            context_parts.append(rules_text)
            total_tokens += AIService.estimate_tokens(rules_text)

        intent = router_result.get("intent", "chat_casual")
        target_files = router_result.get("target_files", [])
        target_bible_entities = router_result.get("target_bible_entities", [])
        chapter_range_mode = router_result.get("chapter_range_mode")
        chapter_range_count = router_result.get("chapter_range_count", 5)
        chapter_range = router_result.get("chapter_range")

        if intent == "read_full_content":
            full_text, source_names = "", []
            range_bounds = ContextManager._resolve_chapter_range(
                project_id, chapter_range_mode, chapter_range_count, chapter_range
            )
            if range_bounds is not None:
                full_text, source_names = ContextManager.load_chapters_by_range(
                    project_id, range_bounds[0], range_bounds[1],
                    token_limit=ContextManager.DEFAULT_CHAPTER_TOKEN_LIMIT,
                )
            if not full_text and target_files:
                full_text, source_names = ContextManager.load_full_content(
                    target_files, project_id,
                    token_limit=ContextManager.DEFAULT_CHAPTER_TOKEN_LIMIT,
                )
            if full_text:
                context_parts.append(f"\n--- TARGET CONTENT ---\n{full_text}")
                sources.extend(source_names)
                total_tokens += AIService.estimate_tokens(full_text)

        elif intent == "search_chunks":
            # Chunk vector search + reverse lookup (chunk -> chapter -> arc)
            chunk_ids = []
            query_for_chunk = (router_result.get("rewritten_query") or (router_result.get("target_files") or [""])[0] or "").strip()
            chunk_rows = search_chunks_vector(
                query_for_chunk or "nội dung",
                project_id,
                arc_id=current_arc_id,
                top_k=8,
            )
            if chunk_rows:
                chunk_ids = [str(c.get("id")) for c in chunk_rows if c.get("id")]
            if not chunk_ids and current_arc_id and query_for_chunk:
                chunk_rows = search_chunks_vector(query_for_chunk, project_id, arc_id=None, top_k=8)
                if chunk_rows:
                    chunk_ids = [str(c.get("id")) for c in chunk_rows if c.get("id")]
            if chunk_ids and ReverseLookupAssembler:
                chunk_ctx, chunk_sources, chunk_tokens = ContextManager.build_context_with_chunk_reverse_lookup(
                    project_id, chunk_ids, current_arc_id, token_limit=8000
                )
                if chunk_ctx:
                    context_parts.append(chunk_ctx)
                    total_tokens += chunk_tokens
                    sources.extend(chunk_sources)
                    sources.append("📦 Chunk + Reverse Lookup")
            # Fallback: khi không có chunk hoặc câu hỏi nhắc số chương cụ thể -> load nội dung chương theo số (chunk thường không chứa "chương 1" trong text)
            chapter_range_from_query = parse_chapter_range_from_query(query_for_chunk or router_result.get("rewritten_query") or "")
            if chapter_range_from_query and (not chunk_ids or not context_parts):
                full_text, source_names = ContextManager.load_chapters_by_range(
                    project_id, chapter_range_from_query[0], chapter_range_from_query[1],
                    token_limit=8000,
                )
                if full_text:
                    context_parts.append(f"\n--- 📄 NỘI DUNG CHƯƠNG (fallback theo số chương) ---\n{full_text}")
                    total_tokens += AIService.estimate_tokens(full_text)
                    sources.extend(source_names)
                    sources.append("📄 Chapter fallback")
            if not chunk_ids and not chapter_range_from_query:
                # Fallback: search bible
                intent = "search_bible"

        elif intent == "manage_timeline":
            range_bounds = ContextManager._resolve_chapter_range(
                project_id, chapter_range_mode, chapter_range_count, chapter_range
            )
            events = get_timeline_events(
                project_id,
                limit=30,
                chapter_range=range_bounds,
                arc_id=current_arc_id,
            )
            if events:
                lines = ["[TIMELINE EVENTS - Thứ tự sự kiện / mốc thời gian]"]
                for e in events:
                    order = e.get("event_order", 0)
                    title = e.get("title", "")
                    desc = (e.get("description") or "")[:500]
                    raw_date = e.get("raw_date", "")
                    etype = e.get("event_type", "event")
                    lines.append(f"- #{order} [{etype}] {title}" + (f" (Thời điểm: {raw_date})" if raw_date else "") + f"\n  {desc}")
                block = "\n".join(lines)
                context_parts.append(block)
                total_tokens += AIService.estimate_tokens(block)
                sources.append("📅 Timeline Events")
            else:
                context_parts.append("[TIMELINE] Chưa có dữ liệu timeline_events cho dự án này. Trả lời thông tin có trong Bible/chương nếu liên quan.")
                sources.append("📅 Timeline (empty)")

        elif intent == "web_search":
            try:
                from utils.web_search import web_search as do_web_search
                search_text = do_web_search(router_result.get("rewritten_query") or "", max_results=5)
            except Exception as ex:
                search_text = f"[WEB SEARCH] Lỗi: {ex}. Trả lời dựa trên kiến thức có sẵn."
            context_parts.append(search_text)
            total_tokens += AIService.estimate_tokens(search_text)
            sources.append("🌐 Web Search")

        elif intent == "ask_user_clarification":
            clarification_question = router_result.get("clarification_question", "") or "Bạn có thể nói rõ hơn câu hỏi hoặc chủ đề bạn muốn hỏi?"
            context_parts.append(f"[CẦN LÀM RÕ]\nHệ thống cần thêm thông tin: {clarification_question}\nTrả lời ngắn gọn, lịch sự yêu cầu user làm rõ theo gợi ý trên (không đoán bừa).")
            sources.append("❓ Clarification")

        elif intent == "update_data":
            op_type = router_result.get("data_operation_type") or ""
            op_target = router_result.get("data_operation_target") or ""
            if op_target in ("bible", "relation", "timeline", "chunking"):
                ch_range = router_result.get("chapter_range")
                ch_desc = f"chương {ch_range[0]}" if (ch_range and len(ch_range) >= 1) else "chương"
                context_parts.append(
                    f"[CẬP NHẬT DỮ LIỆU - CẦN XÁC NHẬN]\n"
                    f"User yêu cầu: {op_type} {op_target} cho {ch_desc}. "
                    "Thao tác này chỉ thực hiện sau khi user xác nhận. Trả lời ngắn gọn: nêu rõ thao tác và đối tượng cùng chương, nhắc user xác nhận (sẽ chạy ngầm và xem như đã chấp nhận)."
                )
                sources.append("📦 Update data (thao tác theo chương, pending confirm)")
            else:
                update_summary = router_result.get("update_summary", "") or "Ghi nhớ / cập nhật dữ liệu theo yêu cầu user."
                context_parts.append(f"[CẬP NHẬT DỮ LIỆU - CẦN XÁC NHẬN]\n{update_summary}\n\nThao tác này chỉ thực hiện sau khi user xác nhận. Trả lời tóm tắt nội dung sẽ được ghi và nhắc user xác nhận trước khi thực hiện.")
                sources.append("✏️ Update data (ghi nhớ quy tắc, pending confirm)")

        elif intent == "query_Sql":
            arc_id = (session_state or {}).get("current_arc_id")
            block, source_label = build_query_sql_context(router_result, project_id, arc_id=arc_id)
            if block:
                context_parts.append(block)
                total_tokens += AIService.estimate_tokens(block)
                sources.append(source_label)
            else:
                intent = "search_bible"

        if intent == "search_bible" or intent == "mixed_context":
            range_bounds_bible = ContextManager._resolve_chapter_range(
                project_id, chapter_range_mode, chapter_range_count, chapter_range
            )
            raw_inferred = router_result.get("inferred_prefixes") or []
            valid_keys = Config.get_valid_prefix_keys()
            inferred_prefixes = [
                p for p in raw_inferred
                if p and str(p).strip().upper().replace(" ", "_") in valid_keys
            ] if valid_keys else raw_inferred
            bible_context = ""
            for entity in target_bible_entities:
                raw_list = HybridSearch.smart_search_hybrid_raw(
                    entity, project_id, top_k=2, inferred_prefixes=inferred_prefixes
                )
                if range_bounds_bible:
                    raw_list = _filter_bible_by_chapter_range(raw_list, range_bounds_bible, max_items=10)
                if raw_list:
                    for item in raw_list:
                        try:
                            eid = item.get("id")
                            if eid is not None:
                                HybridSearch.update_lookup_stats(eid)
                        except Exception:
                            pass
                    main_id = raw_list[0].get("id") if raw_list else None
                    rel_block = ""
                    if main_id:
                        rel_text = ContextManager.get_entity_relations(main_id, project_id)
                        if rel_text:
                            rel_block = f"> [RELATION]:\n{rel_text}\n\n"
                    part = format_bible_context_by_sections(raw_list)
                    bible_context += f"\n--- {entity.upper()} ---\n{rel_block}{part}\n"

            if not bible_context and router_result.get("rewritten_query"):
                raw_list = HybridSearch.smart_search_hybrid_raw(
                    router_result["rewritten_query"],
                    project_id,
                    top_k=5,
                    inferred_prefixes=inferred_prefixes,
                )
                if range_bounds_bible:
                    raw_list = _filter_bible_by_chapter_range(raw_list, range_bounds_bible, max_items=12)
                if raw_list:
                    for item in raw_list:
                        try:
                            eid = item.get("id")
                            if eid is not None:
                                HybridSearch.update_lookup_stats(eid)
                        except Exception:
                            pass
                    main_id = raw_list[0].get("id") if raw_list else None
                    rel_block = ""
                    if main_id:
                        rel_text = ContextManager.get_entity_relations(main_id, project_id)
                        if rel_text:
                            rel_block = f"> [RELATION]:\n{rel_text}\n\n"
                    part = format_bible_context_by_sections(raw_list)
                    bible_context = f"\n--- KNOWLEDGE BASE ---\n{rel_block}{part}\n"

            if bible_context:
                context_parts.append(bible_context)
                total_tokens += AIService.estimate_tokens(bible_context)
                sources.append("📚 Bible Search")

            try:
                services = init_services()
                supabase = services['supabase']
                related_chapter_nums = set()

                if target_bible_entities:
                    for entity in target_bible_entities:
                        res = supabase.table("story_bible") \
                            .select("source_chapter") \
                            .eq("story_id", project_id) \
                            .ilike("entity_name", f"%{entity}%") \
                            .execute()

                        if res.data:
                            for row in res.data:
                                if row.get('source_chapter') and row['source_chapter'] > 0:
                                    related_chapter_nums.add(row['source_chapter'])

                if related_chapter_nums:
                    chap_res = supabase.table("chapters") \
                        .select("title") \
                        .eq("story_id", project_id) \
                        .in_("chapter_number", list(related_chapter_nums)) \
                        .execute()

                    if chap_res.data:
                        auto_files = [c['title'] for c in chap_res.data if c.get('title')]

                        if auto_files:
                            extra_text, extra_sources = ContextManager.load_full_content(auto_files, project_id)

                            if extra_text:
                                context_parts.append(f"\n--- 🕵️ AUTO-DETECTED CONTEXT (REVERSE LOOKUP) ---\n{extra_text}")
                                sources.extend([f"{s} (Auto)" for s in extra_sources])
                                total_tokens += AIService.estimate_tokens(extra_text)

            except Exception as e:
                print(f"Reverse lookup error: {e}")
                pass

            # search_bible mở rộng: khi user hỏi về timeline/sự kiện thì bổ sung dữ liệu timeline vào context
            _query_lower = (router_result.get("rewritten_query") or "").lower()
            _timeline_keywords = ("timeline", "sự kiện", "sự kiện nào", "mốc thời gian", "thứ tự", "diễn ra trước", "diễn ra sau", "sự kiện diễn ra")
            if intent == "search_bible" and any(k in _query_lower for k in _timeline_keywords):
                events = get_timeline_events(
                    project_id,
                    limit=20,
                    chapter_range=range_bounds_bible,
                    arc_id=current_arc_id,
                )
                if events:
                    lines = ["[TIMELINE EVENTS - Thứ tự sự kiện / mốc thời gian]"]
                    for e in events:
                        order = e.get("event_order", 0)
                        title = e.get("title", "")
                        desc = (e.get("description") or "")[:400]
                        raw_date = e.get("raw_date", "")
                        etype = e.get("event_type", "event")
                        lines.append(f"- #{order} [{etype}] {title}" + (f" (Thời điểm: {raw_date})" if raw_date else "") + f"\n  {desc}")
                    block = "\n".join(lines)
                    context_parts.append(block)
                    total_tokens += AIService.estimate_tokens(block)
                    sources.append("📅 Timeline Events")

        if intent == "mixed_context" and target_files:
            full_text, source_names = ContextManager.load_full_content(
                target_files, project_id,
                token_limit=ContextManager.DEFAULT_CHAPTER_TOKEN_LIMIT,
            )
            if full_text:
                context_parts.append(f"\n--- RELATED FILES ---\n{full_text}")
                sources.extend(source_names)
                total_tokens += AIService.estimate_tokens(full_text)

        # mixed_context: bổ sung timeline + chunks (Bible và file đã có ở trên); lọc mềm theo chapter_range/arc để hạn chế token.
        if intent == "mixed_context":
            range_bounds = ContextManager._resolve_chapter_range(
                project_id, chapter_range_mode, chapter_range_count, chapter_range
            )
            events = get_timeline_events(
                project_id,
                limit=20,
                chapter_range=range_bounds,
                arc_id=current_arc_id,
            )
            if events:
                lines = ["[TIMELINE EVENTS - Thứ tự sự kiện / mốc thời gian]"]
                for e in events:
                    order = e.get("event_order", 0)
                    title = e.get("title", "")
                    desc = (e.get("description") or "")[:400]
                    raw_date = e.get("raw_date", "")
                    etype = e.get("event_type", "event")
                    lines.append(f"- #{order} [{etype}] {title}" + (f" (Thời điểm: {raw_date})" if raw_date else "") + f"\n  {desc}")
                block = "\n".join(lines)
                context_parts.append(block)
                total_tokens += AIService.estimate_tokens(block)
                sources.append("📅 Timeline Events (mixed)")
            query_for_chunk = (router_result.get("rewritten_query") or "").strip() or "nội dung"
            chunk_rows = search_chunks_vector(query_for_chunk, project_id, arc_id=current_arc_id, top_k=5)
            if not chunk_rows and current_arc_id:
                chunk_rows = search_chunks_vector(query_for_chunk, project_id, arc_id=None, top_k=5)
            if chunk_rows and ReverseLookupAssembler:
                chunk_ids = [str(c.get("id")) for c in chunk_rows if c.get("id")]
                if chunk_ids:
                    chunk_ctx, chunk_sources, chunk_tokens = ContextManager.build_context_with_chunk_reverse_lookup(
                        project_id, chunk_ids, current_arc_id, token_limit=5000
                    )
                    if chunk_ctx:
                        context_parts.append(chunk_ctx)
                        total_tokens += chunk_tokens
                        sources.extend(chunk_sources)
                        sources.append("📦 Chunks (mixed)")

        context_str = "\n".join(context_parts)
        if max_context_tokens is not None and total_tokens > max_context_tokens:
            context_str, total_tokens = cap_context_to_tokens(context_str, max_context_tokens)
        return context_str, sources, total_tokens


