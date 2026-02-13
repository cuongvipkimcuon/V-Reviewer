# ai_engine.py - AI Service, Router, Context, Rule Mining
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

import streamlit as st
from openai import OpenAI

from config import Config, init_services

try:
    from core.arc_service import ArcService
    from core.reverse_lookup import ReverseLookupAssembler
except ImportError:
    ArcService = None
    ReverseLookupAssembler = None


# ==========================================
# 🤖 AI SERVICE
# ==========================================
class AIService:
    """Dịch vụ AI sử dụng OpenAI client cho OpenRouter với các tính năng nâng cao"""

    @staticmethod
    @st.cache_data(ttl=3600)
    def get_available_models():
        """Lấy danh sách model có sẵn từ OpenRouter"""
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY
            )
            return Config.AVAILABLE_MODELS
        except Exception:
            return Config.AVAILABLE_MODELS

    @staticmethod
    def call_openrouter(
        messages: List[Dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 8000,
        stream: bool = False,
        response_format: Optional[Dict] = None
    ) -> Any:
        """Gọi OpenRouter API sử dụng OpenAI client"""
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": "https://v-universe.streamlit.app",
                    "X-Title": "V-Universe AI Hub"
                }
            )

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                response_format=response_format
            )

            return response
        except Exception as e:
            raise Exception(f"OpenRouter API error: {str(e)}")

    @staticmethod
    def get_embedding(text: str) -> Optional[List[float]]:
        """Lấy embedding từ OpenRouter"""
        if not text or not isinstance(text, str) or not text.strip():
            return None

        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY
            )

            response = client.embeddings.create(
                model=Config.EMBEDDING_MODEL,
                input=text
            )

            return response.data[0].embedding
        except Exception as e:
            print(f"Embedding error: {e}")
            return None

    @staticmethod
    def get_embeddings_batch(texts: List[str], batch_size: int = 100) -> List[Optional[List[float]]]:
        """Lấy embedding hàng loạt (nhiều text trong ít request). Trả về list cùng thứ tự với texts; phần tử lỗi là None."""
        if not texts:
            return []
        out: List[Optional[List[float]]] = [None] * len(texts)
        valid_indices: List[int] = []
        valid_texts: List[str] = []
        for i, t in enumerate(texts):
            if t and isinstance(t, str) and t.strip():
                valid_indices.append(i)
                valid_texts.append(t.strip())
        if not valid_texts:
            return out
        try:
            client = OpenAI(
                base_url=Config.OPENROUTER_BASE_URL,
                api_key=Config.OPENROUTER_API_KEY
            )
            for start in range(0, len(valid_texts), batch_size):
                chunk = valid_texts[start:start + batch_size]
                chunk_indices = valid_indices[start:start + batch_size]
                response = client.embeddings.create(
                    model=Config.EMBEDDING_MODEL,
                    input=chunk
                )
                for j, emb_obj in enumerate(response.data):
                    idx = chunk_indices[j] if j < len(chunk_indices) else start + j
                    if idx < len(out) and emb_obj.embedding is not None:
                        out[idx] = emb_obj.embedding
        except Exception as e:
            print(f"Embedding batch error: {e}")
        return out

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Ước tính số token"""
        if not text:
            return 0
        return len(text) // 4

    @staticmethod
    def calculate_cost(
        input_tokens: int,
        output_tokens: int,
        model: str
    ) -> float:
        """Tính chi phí cho request"""
        model_costs = Config.MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})

        input_cost = (input_tokens / 1_000_000) * model_costs["input"]
        output_cost = (output_tokens / 1_000_000) * model_costs["output"]

        return round(input_cost + output_cost, 6)

    @staticmethod
    def clean_json_text(text):
        """Làm sạch markdown (```json ... ```) trước khi parse"""
        if not text:
            return "{}"
        text = text.replace("```json", "").replace("```", "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != 0:
            return text[start:end]
        return text


def cap_context_to_tokens(text: str, max_tokens: int) -> Tuple[str, int]:
    """Kiểm tra và cắt context sao cho không vượt quá max_tokens. Cắt từ cuối để giữ phần đầu (persona, rules...)."""
    if not text or max_tokens <= 0:
        return text or "", AIService.estimate_tokens(text or "")
    est = AIService.estimate_tokens(text)
    if est <= max_tokens:
        return text, est
    # Ước tính: estimate_tokens = len//4, nên target_chars ≈ max_tokens * 4
    target_chars = max_tokens * 4
    out = text[:target_chars] if len(text) > target_chars else text
    est = AIService.estimate_tokens(out)
    while est > max_tokens and len(out) > 500:
        out = out[:-500]
        est = AIService.estimate_tokens(out)
    return out, est


# ==========================================
# 🔍 HYBRID SEARCH SYSTEM (V5 - Re-ranking + lookup stats)
# ==========================================
# Trọng số re-rank: VectorSim * 0.7 + RecencyBonus * 0.1 + ImportanceBias * 0.2
VECTOR_WEIGHT = 0.7
RECENCY_WEIGHT = 0.1
IMPORTANCE_WEIGHT = 0.2
RECENCY_BONUS_HOURS = 24


def _safe_float(value: Any, default: float = 0.5) -> float:
    """Lấy số thực an toàn từ record (defensive)."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _recency_bonus(last_lookup_at: Any) -> float:
    """RecencyBonus: 1.0 nếu last_lookup_at trong vòng 24h, else 0.0."""
    if last_lookup_at is None:
        return 0.0
    try:
        if isinstance(last_lookup_at, str):
            dt = datetime.fromisoformat(last_lookup_at.replace("Z", "+00:00"))
        else:
            dt = last_lookup_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        return 1.0 if delta <= timedelta(hours=RECENCY_BONUS_HOURS) else 0.0
    except Exception:
        return 0.0


def _rerank_by_score(rows: List[Dict], top_k: int) -> List[Dict]:
    """Tính Final Score và sắp xếp lại: (VectorSim*0.7) + (RecencyBonus*0.1) + (ImportanceBias*0.2)."""
    for item in rows:
        vector_sim = _safe_float(item.get("similarity") or item.get("score"), 0.5)
        vector_sim = max(0.0, min(1.0, vector_sim))
        recency = _recency_bonus(item.get("last_lookup_at"))
        importance = _safe_float(item.get("importance_bias"), 0.5)
        importance = max(0.0, min(1.0, importance))
        item["_final_score"] = (vector_sim * VECTOR_WEIGHT) + (recency * RECENCY_WEIGHT) + (importance * IMPORTANCE_WEIGHT)
    sorted_rows = sorted(rows, key=lambda x: x.get("_final_score", 0.0), reverse=True)
    for item in sorted_rows:
        item.pop("_final_score", None)
    return sorted_rows[:top_k]


def _rerank_by_score_with_breakdown(rows: List[Dict], top_k: int) -> List[Dict]:
    """Giống _rerank_by_score nhưng giữ lại score_vector, score_recency, score_bias, score_final để hiển thị."""
    for item in rows:
        vector_sim = _safe_float(item.get("similarity") or item.get("score"), 0.5)
        vector_sim = max(0.0, min(1.0, vector_sim))
        recency = _recency_bonus(item.get("last_lookup_at"))
        importance = _safe_float(item.get("importance_bias"), 0.5)
        importance = max(0.0, min(1.0, importance))
        item["score_vector"] = round(vector_sim * VECTOR_WEIGHT, 4)
        item["score_recency"] = round(recency * RECENCY_WEIGHT, 4)
        item["score_bias"] = round(importance * IMPORTANCE_WEIGHT, 4)
        item["score_final"] = round(
            item["score_vector"] + item["score_recency"] + item["score_bias"], 4
        )
    sorted_rows = sorted(rows, key=lambda x: x.get("score_final", 0.0), reverse=True)
    return sorted_rows[:top_k]


class HybridSearch:
    """Hệ thống tìm kiếm kết hợp vector và từ khóa (V5: re-ranking, lookup_count, last_lookup_at)"""

    @staticmethod
    def smart_search_hybrid_raw(
        query_text: str,
        project_id: str,
        top_k: int = 10,
        inferred_prefixes: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Tìm kiếm hybrid trả về raw data; re-rank trong Python. Nếu inferred_prefixes có giá trị thì dùng prefix-aware rerank."""
        try:
            services = init_services()
            supabase = services["supabase"]
            query_vec = AIService.get_embedding(query_text)
            candidate_limit = max(top_k * 3, 30)

            if query_vec:
                try:
                    response = supabase.rpc("hybrid_search", {
                        "query_text": query_text,
                        "query_embedding": query_vec,
                        "match_threshold": 0.3,
                        "match_count": candidate_limit,
                        "story_id_input": project_id,
                    }).execute()
                    raw_list = response.data if response.data else []
                except Exception:
                    raw_list = []
                if not raw_list:
                    try:
                        response = supabase.table("story_bible").select("*").eq(
                            "story_id", project_id
                        ).or_(f"entity_name.ilike.%{query_text}%,description.ilike.%{query_text}%").limit(
                            candidate_limit
                        ).execute()
                        raw_list = response.data if response.data else []
                        for item in raw_list:
                            item["similarity"] = 0.5
                    except Exception:
                        raw_list = []
            else:
                try:
                    response = supabase.table("story_bible").select("*").eq(
                        "story_id", project_id
                    ).or_(f"entity_name.ilike.%{query_text}%,description.ilike.%{query_text}%").limit(
                        candidate_limit
                    ).execute()
                    raw_list = response.data if response.data else []
                    for item in raw_list:
                        item["similarity"] = 0.5
                except Exception:
                    raw_list = []

            if not raw_list:
                return []

            if inferred_prefixes:
                reranked = _rerank_by_score_with_prefix(raw_list, top_k, inferred_prefixes)
            else:
                reranked = _rerank_by_score(raw_list, top_k)
            return reranked

        except Exception as e:
            print(f"Search error: {e}")
            return []

    @staticmethod
    def smart_search_hybrid_raw_with_scores(query_text: str, project_id: str, top_k: int = 10) -> List[Dict]:
        """Giống smart_search_hybrid_raw nhưng mỗi item có thêm score_vector, score_recency, score_bias, score_final."""
        try:
            services = init_services()
            supabase = services["supabase"]
            query_vec = AIService.get_embedding(query_text)
            candidate_limit = max(top_k * 3, 30)
            if query_vec:
                try:
                    response = supabase.rpc("hybrid_search", {
                        "query_text": query_text,
                        "query_embedding": query_vec,
                        "match_threshold": 0.3,
                        "match_count": candidate_limit,
                        "story_id_input": project_id,
                    }).execute()
                    raw_list = response.data if response.data else []
                except Exception:
                    raw_list = []
                if not raw_list:
                    try:
                        response = supabase.table("story_bible").select("*").eq(
                            "story_id", project_id
                        ).or_(f"entity_name.ilike.%{query_text}%,description.ilike.%{query_text}%").limit(
                            candidate_limit
                        ).execute()
                        raw_list = response.data if response.data else []
                        for item in raw_list:
                            item["similarity"] = 0.5
                    except Exception:
                        raw_list = []
            else:
                try:
                    response = supabase.table("story_bible").select("*").eq(
                        "story_id", project_id
                    ).or_(f"entity_name.ilike.%{query_text}%,description.ilike.%{query_text}%").limit(
                        candidate_limit
                    ).execute()
                    raw_list = response.data if response.data else []
                    for item in raw_list:
                        item["similarity"] = 0.5
                except Exception:
                    raw_list = []
            if not raw_list:
                return []
            return _rerank_by_score_with_breakdown(raw_list, top_k)
        except Exception as e:
            print(f"Search error: {e}")
            return []

    @staticmethod
    def update_lookup_stats(entity_id: Any) -> None:
        """Tăng lookup_count += 1 và cập nhật last_lookup_at = now() cho record vừa được tìm thấy. Defensive: không crash nếu cột chưa có."""
        if entity_id is None:
            return
        try:
            services = init_services()
            if not services:
                return
            supabase = services["supabase"]
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                row = supabase.table("story_bible").select("lookup_count").eq("id", entity_id).execute()
                current = 0
                if row.data and len(row.data) > 0:
                    current = _safe_float(row.data[0].get("lookup_count"), 0.0)
                new_count = int(current) + 1
                supabase.table("story_bible").update({
                    "lookup_count": new_count,
                    "last_lookup_at": now_iso,
                }).eq("id", entity_id).execute()
            except Exception:
                pass
        except Exception as e:
            print(f"update_lookup_stats error: {e}")

    @staticmethod
    def smart_search_hybrid(query_text: str, project_id: str, top_k: int = 10) -> str:
        """Wrapper trả về string context (giữ tương thích)."""
        raw_data = HybridSearch.smart_search_hybrid_raw(query_text, project_id, top_k)
        results = []
        if raw_data:
            for item in raw_data:
                name = item.get("entity_name") or ""
                desc = item.get("description") or ""
                results.append(f"- [{name}]: {desc}")
        return "\n".join(results) if results else ""


# ==========================================
# 🎯 SEMANTIC INTENT (trước Router - khớp thì bỏ qua Router)
# ==========================================
def check_semantic_intent(
    query_text: str,
    project_id: str,
    threshold: float = 0.90,
) -> Optional[Dict]:
    """So sánh vector câu hỏi với semantic_intent. Nếu khớp >= threshold thì trả về row (related_data chính), else None. Không cần intent."""
    if not query_text or not project_id:
        return None
    try:
        services = init_services()
        if not services:
            return None
        supabase = services["supabase"]
        try:
            supabase.table("semantic_intent").select("id").limit(1).execute()
        except Exception:
            return None
        try:
            r = supabase.table("settings").select("value").eq("key", "semantic_intent_threshold").execute()
            if r.data and r.data[0]:
                t = r.data[0].get("value")
                threshold = max(0.85, min(1.0, float(t) / 100.0)) if t is not None else threshold
        except Exception:
            pass
        query_vec = AIService.get_embedding(query_text)
        if not query_vec:
            return None
        rows = supabase.table("semantic_intent").select("id, question_sample, intent, related_data, embedding").eq("story_id", project_id).execute()
        data = rows.data or []
        best_match = None
        best_sim = 0.0
        for row in data:
            emb = row.get("embedding")
            if emb is None:
                continue
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    continue
            try:
                import math
                dot = sum(a * b for a, b in zip(query_vec, emb))
                na = math.sqrt(sum(a * a for a in query_vec))
                nb = math.sqrt(sum(b * b for b in emb))
                sim = dot / (na * nb) if na and nb else 0
                sim = (sim + 1) / 2
                if sim >= threshold and sim > best_sim:
                    best_sim = sim
                    best_match = {**row, "similarity": sim}
            except Exception:
                pass
        return best_match
    except Exception as e:
        print(f"check_semantic_intent error: {e}")
        return None


# ==========================================
# 📦 CHUNK SEARCH (vector + text, reverse lookup)
# ==========================================
def search_chunks_vector(
    query_text: str,
    project_id: str,
    arc_id: Optional[str] = None,
    top_k: int = 10,
) -> List[Dict]:
    """Tìm chunks theo vector (nếu có embedding) hoặc text fallback. Trả về list chunk rows. Nếu có arc_id mà không có kết quả thì thử lại không lọc arc."""
    try:
        services = init_services()
        if not services:
            return []
        supabase = services["supabase"]
        query_vec = AIService.get_embedding(query_text)
        q = supabase.table("chunks").select("id, chapter_id, arc_id, content, raw_content, meta_json, story_id").eq("story_id", project_id)
        if arc_id:
            q = q.eq("arc_id", arc_id)
        if query_vec:
            try:
                r = supabase.rpc("hybrid_chunk_search", {
                    "query_text": query_text,
                    "query_embedding": query_vec,
                    "story_id_input": project_id,
                    "match_threshold": 0.3,
                    "match_count": top_k,
                }).execute()
                rows = list(r.data) if r.data else []
                if arc_id and not rows and query_text and query_text.strip():
                    rows = search_chunks_vector(query_text, project_id, arc_id=None, top_k=top_k)
                return rows
            except Exception:
                pass
        if query_text and query_text.strip():
            pattern = "%" + str(query_text).strip() + "%"
            r = q.ilike("content", pattern).limit(top_k).execute()
            rows = list(r.data) if r.data else []
            if arc_id and not rows:
                rows = search_chunks_vector(query_text, project_id, arc_id=None, top_k=top_k)
            return rows
        return []
    except Exception as e:
        print(f"search_chunks_vector error: {e}")
        return []


# ==========================================
# 🧭 SMART AI ROUTER SYSTEM
# ==========================================


def extract_prefix(name: str) -> Tuple[str, str]:
    """
    Bóc tách tiền tố: tìm nội dung trong [...] ở đầu chuỗi.
    VD: "[VŨ KHÍ] Kiếm Thiên" -> ("VŨ KHÍ", "Kiếm Thiên"). Defensive: lỗi -> ("", name gốc).
    """
    if not name or not isinstance(name, str):
        return "", (name or "")
    s = name.strip()
    if not s:
        return "", name
    try:
        if s.startswith("["):
            idx = s.find("]")
            if idx > 0:
                prefix = s[1:idx].strip()
                rest = s[idx + 1:].strip()
                return prefix, rest if rest else s
        return "", s
    except Exception:
        return "", s


def _estimate_tokens(text: str) -> int:
    """Ước lượng số token (~4 ký tự/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# Trọng số khi re-rank có prefix: vector 0.55, recency 0.1, bias 0.2, prefix 0.15
PREFIX_WEIGHT = 0.15
VECTOR_WEIGHT_WITH_PREFIX = 0.55
RECENCY_WEIGHT_UNCHANGED = 0.1
IMPORTANCE_WEIGHT_UNCHANGED = 0.2


def get_prefix_key_from_entity_name(entity_name: str) -> str:
    """Lấy prefix_key (viết HOA, không ngoặc) từ entity_name. VD: '[CHARACTER] John' -> 'CHARACTER'."""
    if not entity_name or not isinstance(entity_name, str):
        return "OTHER"
    prefix, _ = extract_prefix(entity_name.strip())
    return (prefix or "OTHER").strip().upper().replace(" ", "_") or "OTHER"


def _rerank_by_score_with_prefix(
    rows: List[Dict],
    top_k: int,
    inferred_prefixes: Optional[List[str]] = None,
) -> List[Dict]:
    """Re-rank với bonus cho entry có prefix nằm trong inferred_prefixes. Dùng khi Router trả về inferred_prefixes."""
    if not inferred_prefixes:
        return _rerank_by_score(rows, top_k)
    normalized_inferred = {str(p).strip().upper().replace(" ", "_") for p in inferred_prefixes if p}
    for item in rows:
        vector_sim = _safe_float(item.get("similarity") or item.get("score"), 0.5)
        vector_sim = max(0.0, min(1.0, vector_sim))
        recency = _recency_bonus(item.get("last_lookup_at"))
        importance = _safe_float(item.get("importance_bias"), 0.5)
        importance = max(0.0, min(1.0, importance))
        pk = get_prefix_key_from_entity_name(item.get("entity_name") or "")
        prefix_bonus = 1.0 if pk in normalized_inferred else 0.0
        item["_final_score"] = (
            (vector_sim * VECTOR_WEIGHT_WITH_PREFIX)
            + (recency * RECENCY_WEIGHT_UNCHANGED)
            + (importance * IMPORTANCE_WEIGHT_UNCHANGED)
            + (prefix_bonus * PREFIX_WEIGHT)
        )
    sorted_rows = sorted(rows, key=lambda x: x.get("_final_score", 0.0), reverse=True)
    for item in sorted_rows:
        item.pop("_final_score", None)
    return sorted_rows[:top_k]


def _get_prefix_section_order_and_labels() -> Tuple[List[str], Dict[str, str]]:
    """Lấy thứ tự và nhãn section từ DB (Config.get_prefix_setup()). Trả về (order, label_map)."""
    setup = Config.get_prefix_setup()
    order = []
    labels: Dict[str, str] = {}
    for p in setup:
        pk = (p.get("prefix_key") or "").strip().upper().replace(" ", "_")
        if pk:
            order.append(pk)
            labels[pk] = pk
    return order, labels


def format_bible_context_by_sections(raw_list: List[Dict]) -> str:
    """Gom kết quả Bible theo section theo prefix; thứ tự và nhãn lấy từ DB (get_prefix_setup)."""
    if not raw_list:
        return ""
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for item in raw_list:
        pk = get_prefix_key_from_entity_name(item.get("entity_name") or "")
        grouped[pk].append(item)
    order, labels = _get_prefix_section_order_and_labels()
    seen = set(order)
    for pk in grouped:
        if pk not in seen:
            order.append(pk)
            if pk not in labels:
                labels[pk] = pk
    sections = []
    for pk in order:
        items = grouped.get(pk, [])
        if not items:
            continue
        label = labels.get(pk, pk)
        block = "\n".join(
            f"- [{e.get('entity_name', '')}]: {e.get('description', '')}"
            for e in items
        )
        sections.append(f"\n--- {label} ---\n{block}")
    return "\n".join(sections).strip()


def get_bible_index(story_id: str, max_tokens: int = 2000) -> str:
    """
    Danh sách thô cho Router: mỗi dòng "Entity: [LOẠI] Tên" (giữ nguyên format [PREFIX] Name).
    Top 100 theo (lookup_count + importance_bias). Có parent_id thì gợi ý thực thể gốc.
    """
    if not story_id:
        return ""
    try:
        services = init_services()
        if not services:
            return ""
        supabase = services["supabase"]
        try:
            rows = (
                supabase.table("story_bible")
                .select("entity_name, lookup_count, importance_bias, parent_id")
                .eq("story_id", story_id)
                .execute()
            )
        except Exception:
            try:
                rows = (
                    supabase.table("story_bible")
                    .select("entity_name, lookup_count, importance_bias")
                    .eq("story_id", story_id)
                    .execute()
                )
            except Exception:
                return ""
        data = list(rows.data) if rows.data else []
        for r in data:
            r.setdefault("parent_id", None)
        def _score(r):
            try:
                lk = int(r.get("lookup_count") or 0)
                bi = r.get("importance_bias")
                b = float(bi) if bi is not None else 0.0
                return lk + b
            except (TypeError, ValueError):
                return 0
        data.sort(key=_score, reverse=True)
        top100 = data[:100]
        parent_ids = [r["parent_id"] for r in top100 if r.get("parent_id")]
        parent_names: Dict[Any, str] = {}
        if parent_ids:
            try:
                ids = list(set(str(pid) for pid in parent_ids if pid is not None))
                if ids:
                    pr = supabase.table("story_bible").select("id, entity_name").in_("id", ids).execute()
                    if pr.data:
                        for row in pr.data:
                            try:
                                _, disp = extract_prefix(row.get("entity_name") or "")
                                parent_names[row.get("id")] = disp.strip() or "(gốc)"
                            except Exception:
                                parent_names[row.get("id")] = (row.get("entity_name") or "").strip() or "(gốc)"
            except Exception:
                pass
        lines = []
        for r in top100:
            name = r.get("entity_name")
            if not name:
                continue
            line = f"Entity: {name}"
            pid = r.get("parent_id")
            if pid is not None and parent_names.get(pid):
                line += f" (gốc: {parent_names[pid]})"
            lines.append(line)
        out = "\n".join(lines) if lines else ""
        if _estimate_tokens(out) > max_tokens:
            out = out[: max(100, max_tokens * 4)]
        return out
    except Exception as e:
        print(f"get_bible_index error: {e}")
        return ""


def get_bible_entries(story_id: str) -> List[Dict[str, Any]]:
    """Trả về danh sách entity trong Bible của story: [{id, entity_name}, ...]. Để resolve tên -> id khi đề xuất quan hệ."""
    if not story_id:
        return []
    try:
        services = init_services()
        if not services:
            return []
        services = init_services()
        supabase = services["supabase"] if services else None
        if not supabase:
            return []
        r = (
            supabase
            .table("story_bible")
            .select("id, entity_name")
            .eq("story_id", story_id)
            .execute()
        )
        return list(r.data) if r.data else []
    except Exception:
        return []


def suggest_relations(content: str, story_id: str) -> List[Dict[str, Any]]:
    """
    AI quét nội dung (chương/đoạn) và so khớp với bible_index để đề xuất:
    - Quan hệ giữa hai thực thể: Source, Target, Relation_Type, Reason -> trả về kind="relation".
    - Nhân vật tiến hóa (1-n): thực thể mới cùng gốc -> gợi ý parent_id, kind="parent".
    Output: list of {
      "kind": "relation" | "parent",
      "source_entity_id", "target_entity_id", "relation_type", "description" (reason), "story_id"  (cho relation),
      hoặc "entity_id", "parent_entity_id", "reason" (cho parent).
    }
    """
    if not content or not content.strip() or not story_id:
        return []
    entries = get_bible_entries(story_id)
    if not entries:
        return []
    name_to_id = {}
    for e in entries:
        name = (e.get("entity_name") or "").strip()
        if name:
            name_to_id[name] = e.get("id")
    index_text = "\n".join([f"- {e.get('entity_name', '')}" for e in entries[:150]])
    prompt = f"""Bạn là trợ lý phân tích văn bản. Cho NỘI DUNG và DANH SÁCH THỰC THỂ (Bible) của một truyện.

DANH SÁCH THỰC THỂ (chính xác từ Bible):
{index_text}

NỘI DUNG (đoạn/chương cần phân tích):
---
{content[:15000]}
---

Nhiệm vụ:
1) QUAN HỆ: Tìm các cặp thực thể có tương tác/liên quan trong nội dung (ví dụ: A là bạn của B, X phản bội Y). Với mỗi cặp, trả về source (tên đúng như trong danh sách), target, relation_type (ngắn gọn: bạn, kẻ thù, đồng đội, yêu, cha-con...), reason (lý do ngắn).
2) NHÂN VẬT TIẾN HÓA (1-n): Nếu trong nội dung có thực thể mới mà thực chất là "phiên bản khác" của một thực thể đã có (VD: "Cường lúc nhỏ" / "Cường lúc lớn", cùng một nhân vật ở hai giai đoạn), KHÔNG tạo quan hệ rời rạc mà gợi ý đặt parent: entity (tên thực thể con/biến thể) và parent (tên thực thể gốc trong danh sách), kèm reason.

Trả về ĐÚNG một JSON object với hai key:
- "relations": [ {{ "source": "<tên trong danh sách>", "target": "<tên trong danh sách>", "relation_type": "...", "reason": "..." }} ]
- "parent_suggestions": [ {{ "entity": "<tên con/biến thể trong danh sách>", "parent": "<tên gốc trong danh sách>", "reason": "..." }} ]

Chỉ dùng tên có trong DANH SÁCH THỰC THỂ. Nếu không có gì phù hợp, trả về "relations": [] và "parent_suggestions": [].
Chỉ trả về JSON, không giải thích thêm."""

    try:
        response = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=Config.ROUTER_MODEL,
            temperature=0.2,
            max_tokens=2000,
        )
        text = (response.choices[0].message.content or "").strip()
        text = re.sub(r"^```\w*\n?", "", text).strip()
        text = re.sub(r"\n?```\s*$", "", text).strip()
        data = json.loads(text)
        relations_in = data.get("relations") or []
        parent_in = data.get("parent_suggestions") or []

        def resolve_name(name: str) -> Optional[Any]:
            n = (name or "").strip()
            if n in name_to_id:
                return name_to_id[n]
            for k, vid in name_to_id.items():
                if n in k or k in n:
                    return vid
            return None

        out = []
        for r in relations_in:
            src_id = resolve_name(r.get("source") or "")
            tgt_id = resolve_name(r.get("target") or "")
            if src_id and tgt_id and src_id != tgt_id:
                out.append({
                    "kind": "relation",
                    "source_entity_id": src_id,
                    "target_entity_id": tgt_id,
                    "relation_type": (r.get("relation_type") or "liên quan").strip(),
                    "description": (r.get("reason") or "").strip(),
                    "story_id": story_id,
                })
        for p in parent_in:
            child_id = resolve_name(p.get("entity") or "")
            parent_id = resolve_name(p.get("parent") or "")
            if child_id and parent_id and child_id != parent_id:
                out.append({
                    "kind": "parent",
                    "entity_id": child_id,
                    "parent_entity_id": parent_id,
                    "reason": (p.get("reason") or "").strip(),
                })
        return out
    except Exception as e:
        print(f"suggest_relations error: {e}")
        return []


class SmartAIRouter:
    """Bộ định tuyến AI thông minh với hybrid search và bible index"""

    @staticmethod
    def ai_router_pro_v2(user_prompt: str, chat_history_text: str, project_id: str = None) -> Dict:
        """Router V2: Phân tích Intent và Target Files, có inject bible_index để nhận diện ý định."""
        rules_context = ""
        bible_index = ""
        prefix_setup_str = ""
        if project_id:
            rules_context = ContextManager.get_mandatory_rules(project_id)
            bible_index = get_bible_index(project_id, max_tokens=2000)
        try:
            prefix_setup = Config.get_prefix_setup()
            if prefix_setup:
                prefix_setup_str = "\n".join(
                    f"- [{p.get('prefix_key', '')}]: {p.get('description', '')}" for p in prefix_setup
                )
            else:
                prefix_setup_str = "(Chưa cấu hình loại thực thể trong Bible Prefix / bảng bible_prefix_config.)"
        except Exception:
            prefix_setup_str = "(Chưa cấu hình loại thực thể trong Bible Prefix.)"

        router_prompt = f"""
        Đóng vai Điều Phối Viên Dự Án (Project Coordinator).
        
        ⚠️ QUY TẮC BẮT BUỘC:
        {rules_context}

        BẢNG MÔ TẢ CÁC LOẠI THỰC THỂ (do người dùng cung cấp):
        {prefix_setup_str}

        DANH SÁCH THỰC THỂ TRONG STORY BIBLE (mỗi dòng: Entity: [LOẠI] Tên):
        {bible_index if bible_index else "(Chưa có dữ liệu)"}

        YÊU CẦU ĐIỀU HƯỚNG: Dựa vào bảng mô tả các loại thực thể. Nếu user hỏi về thực thể (nhân vật, địa điểm...) -> search_bible. Nếu user hỏi theo từng đoạn, từng phần, nội dung chi tiết trong chương/file đã chunk (Data Analyze / Excel/Word chunk) -> search_chunks. Nếu user hỏi diễn biến, sự kiện theo thời gian hoặc nội dung chương đầy đủ -> read_full_content hoặc chapter_range. Chỉ ưu tiên search_chapters khi user hỏi rõ về diễn biến, sự kiện theo thời gian hoặc nội dung chương cụ thể.

        LỊCH SỬ CHAT:
        {chat_history_text}
        
        INPUT CỦA USER: "{user_prompt}"
        
        NHIỆM VỤ: Phân tích intent, target files VÀ nhận diện PHẠM VI CHƯƠNG (Chapter Range) nếu user đề cập.

        PHÂN LOẠI INTENT:
        1. "numerical_calculation": User hỏi về SỐ LIỆU, tính toán, thống kê (tổng, trung bình, đếm, %, doanh thu, chi phí...) -> Ưu tiên Python Executor với Pandas/NumPy.
        2. "read_full_content": User muốn Sửa, Review, Viết tiếp, Kiểm tra code/văn, hoặc nhắc đến tên file cụ thể -> Cần đọc NGUYÊN VĂN FILE.
        3. "search_chunks": User hỏi thông tin chi tiết theo từng đoạn/phần; dữ liệu đã chunk (Excel theo dòng, Word/theo chương từ Data Analyze); cần trích đoạn cụ thể, nội dung từng phần, hoặc tìm trong các chunk đã vector hóa -> Tra chunks (vector + reverse lookup chapter/arc). Ưu tiên search_chunks khi câu hỏi cần trích đoạn cụ thể hoặc dữ liệu đã được chunk.
        4. "search_bible": User hỏi thông tin chung, Lore, cốt truyện, quy định, khái niệm, hoặc nhắc tên nhân vật/thực thể có trong danh sách Bible trên -> Tra cứu Bible (search_bible / get_entity_relations).
        5. "chat_casual": Chào hỏi, khen chê, nói chuyện phiếm không cần dữ liệu dự án.
        6. "mixed_context": Cần cả nội dung file VÀ kiến thức Bible.

        inferred_prefixes: Khi intent là search_bible hoặc mixed_context, điền mảng prefix_key (từ BẢNG MÔ TẢ trên) tương ứng loại thực thể user đang hỏi. VD: hỏi nhân vật -> ["CHARACTER"]; hỏi địa điểm -> ["LOCATION"]; hỏi lore + nhân vật -> ["LORE", "CHARACTER"]. Viết HOA, không ngoặc. Nếu không xác định được -> [].

        NHẬN DIỆN PHẠM VI CHƯƠNG (chapter_range):
        - Nếu user nói "chương đầu", "mấy chương đầu", "đầu truyện" -> đặt "chapter_range_mode": "first", "chapter_range_count": 5 (hoặc số user nói nếu rõ).
        - Nếu user nói "mới nhất", "chương mới", "mấy chương cuối" -> đặt "chapter_range_mode": "latest", "chapter_range_count": 5 (hoặc số user nói nếu rõ).
        - Nếu user nói cụ thể "từ chương 5 đến 10", "chương 5 đến 10" -> đặt "chapter_range": [5, 10], "chapter_range_mode": "range".
        - Nếu không liên quan phạm vi chương -> để "chapter_range": null, "chapter_range_mode": null.

        OUTPUT (JSON ONLY):
        {{
            "intent": "numerical_calculation" | "read_full_content" | "search_chunks" | "search_bible" | "chat_casual" | "mixed_context",
            "target_files": ["tên file 1", "tên file 2"],
            "target_bible_entities": ["tên thực thể 1", "tên thực thể 2"],
            "inferred_prefixes": ["CHARACTER", "LOCATION"],
            "reason": "Lý do ngắn gọn bằng tiếng Việt",
            "rewritten_query": "Viết lại câu hỏi của user cho rõ nghĩa hơn để search database",
            "chapter_range": [start, end] hoặc null,
            "chapter_range_mode": "first" | "latest" | "range" | null,
            "chapter_range_count": 5
        }}
        """

        messages = [
            {"role": "system", "content": "Bạn là AI Router thông minh. Chỉ trả về JSON."},
            {"role": "user", "content": router_prompt}
        ]

        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)

            result = json.loads(content)

            result.setdefault("target_files", [])
            result.setdefault("target_bible_entities", [])
            result.setdefault("inferred_prefixes", [])
            result.setdefault("rewritten_query", user_prompt)
            result.setdefault("chapter_range", None)
            result.setdefault("chapter_range_mode", None)
            result.setdefault("chapter_range_count", 5)
            if not isinstance(result.get("inferred_prefixes"), list):
                result["inferred_prefixes"] = []
            # Chỉ giữ inferred_prefixes có trong DB (get_valid_prefix_keys)
            valid_keys = Config.get_valid_prefix_keys()
            if valid_keys:
                result["inferred_prefixes"] = [
                    p for p in result["inferred_prefixes"]
                    if p and str(p).strip().upper().replace(" ", "_") in valid_keys
                ]

            return result

        except Exception as e:
            print(f"Router error: {e}")
            return {
                "intent": "chat_casual",
                "target_files": [],
                "target_bible_entities": [],
                "inferred_prefixes": [],
                "reason": f"Router error: {e}",
                "rewritten_query": user_prompt,
                "chapter_range": None,
                "chapter_range_mode": None,
                "chapter_range_count": 5,
            }


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
        """Lấy quan hệ của entity: từ bảng entity_relations (nếu có) và các biến thể (parent_id) từ story_bible. Trả về chuỗi dạng '> [RELATION]: ...'. Defensive: không crash nếu bảng/ cột chưa có."""
        lines = []
        try:
            services = init_services()
            if not services:
                return ""
            supabase = services["supabase"]

            try:
                rel_res = supabase.table("entity_relations").select("*").or_(
                    f"source_entity_id.eq.{entity_id},target_entity_id.eq.{entity_id}"
                ).execute()
            except Exception:
                try:
                    rel_res = supabase.table("entity_relations").select("*").or_(
                        f"entity_id.eq.{entity_id},target_entity_id.eq.{entity_id}"
                    ).execute()
                except Exception:
                    rel_res = None
            if rel_res:
                if rel_res.data:
                    id_to_name = {}
                    for r in rel_res.data:
                        eid = r.get("entity_id") or r.get("source_entity_id") or r.get("from_entity_id")
                        tid = r.get("target_entity_id") or r.get("to_entity_id")
                        if eid and eid not in id_to_name:
                            id_to_name[eid] = None
                        if tid and tid not in id_to_name:
                            id_to_name[tid] = None
                    if id_to_name:
                        sb = supabase.table("story_bible").select("id, entity_name").eq(
                            "story_id", project_id
                        ).in_("id", list(id_to_name.keys())).execute()
                        if sb.data:
                            for row in sb.data:
                                id_to_name[row.get("id")] = row.get("entity_name") or ""
                    for r in rel_res.data:
                        rel_type = r.get("relation_type") or r.get("relation") or "liên quan"
                        eid = r.get("entity_id") or r.get("source_entity_id") or r.get("from_entity_id")
                        tid = r.get("target_entity_id") or r.get("to_entity_id")
                        name_a = id_to_name.get(eid) if eid else ""
                        name_b = id_to_name.get(tid) if tid else ""
                        if name_a or name_b:
                            lines.append(f"> [RELATION]: {name_a or 'Entity'} là {rel_type} của {name_b or 'Entity'}.")

            try:
                variants = supabase.table("story_bible").select("entity_name, description").eq(
                    "story_id", project_id
                ).eq("parent_id", entity_id).execute()
                if variants.data:
                    for v in variants.data:
                        name = v.get("entity_name") or ""
                        desc = (v.get("description") or "")[:200]
                        if name:
                            lines.append(f"> [RELATION]: Biến thể: {name} — {desc}...")
            except Exception:
                pass
        except Exception as e:
            print(f"get_entity_relations error: {e}")
        return "\n".join(lines) if lines else ""

    # Giới hạn token khi load nhiều chương (ưu tiên summary nếu vượt)
    DEFAULT_CHAPTER_TOKEN_LIMIT = 60000

    @staticmethod
    def _resolve_chapter_range(
        project_id: str,
        chapter_range_mode: Optional[str],
        chapter_range_count: int,
        chapter_range: Optional[List[int]],
    ) -> Optional[Tuple[int, int]]:
        """Trả về (start, end) chapter_number từ router. first/latest query DB; range dùng trực tiếp."""
        try:
            services = init_services()
            if not services:
                return None
            supabase = services["supabase"]
            count = max(1, min(50, int(chapter_range_count) if chapter_range_count else 5))

            if chapter_range_mode == "range" and chapter_range and len(chapter_range) >= 2:
                return (int(chapter_range[0]), int(chapter_range[1]))

            if chapter_range_mode == "first":
                r = supabase.table("chapters").select("chapter_number").eq(
                    "story_id", project_id
                ).order("chapter_number").limit(1).execute()
                if r.data and len(r.data) > 0:
                    start = int(r.data[0].get("chapter_number", 1))
                    return (start, start + count - 1)
                return (1, count)

            if chapter_range_mode == "latest":
                r = supabase.table("chapters").select("chapter_number").eq(
                    "story_id", project_id
                ).order("chapter_number", desc=True).limit(1).execute()
                if r.data and len(r.data) > 0:
                    end = int(r.data[0].get("chapter_number", 1))
                    start = max(1, end - count + 1)
                    return (start, end)
                return (1, count)

        except Exception as e:
            print(f"_resolve_chapter_range error: {e}")
        return None

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
        """Lấy tất cả các luật (RULE) bắt buộc"""
        try:
            services = init_services()
            supabase = services['supabase']

            res = supabase.table("story_bible") \
                .select("description") \
                .eq("story_id", project_id) \
                .ilike("entity_name", "%[RULE]%") \
                .execute()

            if res.data:
                rules_text = "\n".join([f"- {r['description']}" for r in res.data])
                return f"\n🔥 --- MANDATORY RULES ---\n{rules_text}\n"
            return ""
        except Exception as e:
            print(f"Error getting rules: {e}")
            return ""

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
            if not chunk_ids:
                # Fallback: search bible
                intent = "search_bible"

        if intent == "search_bible" or intent == "mixed_context":
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

        if intent == "mixed_context" and target_files:
            full_text, source_names = ContextManager.load_full_content(
                target_files, project_id,
                token_limit=ContextManager.DEFAULT_CHAPTER_TOKEN_LIMIT,
            )
            if full_text:
                context_parts.append(f"\n--- RELATED FILES ---\n{full_text}")
                sources.extend(source_names)
                total_tokens += AIService.estimate_tokens(full_text)

        context_str = "\n".join(context_parts)
        if max_context_tokens is not None and total_tokens > max_context_tokens:
            context_str, total_tokens = cap_context_to_tokens(context_str, max_context_tokens)
        return context_str, sources, total_tokens


# ==========================================
# 📝 AUTO-SUMMARY / CHAPTER METADATA (V5)
# ==========================================
def suggest_import_category(text: str) -> str:
    """Gợi ý prefix/category cho nội dung import (dùng LLM nhẹ). Dùng prefix từ DB (get_prefixes), trả về [OTHER] nếu không khớp."""
    if not text or len(text.strip()) < 20:
        return "[OTHER]"
    try:
        model = getattr(Config, "METADATA_MODEL", None) or "google/gemini-2.5-flash"
        prefixes = Config.get_prefixes()
        if not prefixes:
            return "[OTHER]"
        if "[OTHER]" not in prefixes:
            prefixes = list(prefixes) + ["[OTHER]"]
        prompt = f"""Phân loại nội dung sau vào ĐÚNG MỘT trong các loại (chỉ trả về chuỗi loại, không giải thích):
{', '.join(prefixes)}

NỘI DUNG (rút gọn):
{text[:1500]}

Trả về đúng một chuỗi, ví dụ: [CHARACTER] hoặc [RULE]."""
        resp = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=50,
        )
        raw = (resp.choices[0].message.content or "").strip()
        for p in prefixes:
            if p in raw or (p.strip("[]") and p.strip("[]").lower() in raw.lower()):
                return p
        return "[OTHER]"
    except Exception as e:
        print(f"suggest_import_category error: {e}")
        return "[OTHER]"


def generate_arc_summary_from_chapters(chapter_summaries: List[Dict[str, Any]], arc_name: str = "") -> Optional[str]:
    """Từ danh sách tóm tắt chương, AI tạo tóm tắt ngắn cho Arc. Trả về str hoặc None nếu lỗi."""
    if not chapter_summaries or not isinstance(chapter_summaries, list):
        return None
    parts = []
    for i, ch in enumerate(chapter_summaries):
        num = ch.get("chapter_number") or ch.get("num") or (i + 1)
        summ = ch.get("summary") or ch.get("description") or ""
        if summ:
            parts.append(f"Chương {num}: {summ}")
    if not parts:
        return None
    combined = "\n".join(parts)
    try:
        model = getattr(Config, "METADATA_MODEL", None) or "google/gemini-2.5-flash"
        prompt = f"""Các tóm tắt chương thuộc Arc '{arc_name or 'Unnamed'}':

{combined}

Nhiệm vụ: Viết 1 đoạn tóm tắt ngắn gọn (2-5 câu) cho toàn bộ Arc, nối mạch các sự kiện/tình tiết chính. Chỉ trả về đoạn tóm tắt, không lời dẫn."""
        resp = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.3,
            max_tokens=500,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return raw if raw else None
    except Exception as e:
        print(f"generate_arc_summary_from_chapters error: {e}")
        return None


def generate_chapter_metadata(content: str) -> Dict[str, str]:
    """Dùng model rẻ (gemini/haiku/deepseek) để tóm tắt nội dung và phân tích art_style. Trả về {"summary": "...", "art_style": "..."}. Defensive: trả về dict rỗng nếu lỗi."""
    if not content or not str(content).strip():
        return {"summary": "", "art_style": ""}
    try:
        model = getattr(Config, "METADATA_MODEL", None) or "google/gemini-2.5-flash"
        prompt = f"""Phân tích đoạn văn/chương sau và trả về ĐÚNG MỘT JSON với 2 key:
- "summary": Tóm tắt nội dung (2-4 câu, tiếng Việt).
- "art_style": Phong cách viết (ví dụ: kể chuyện, mô tả, đối thoại, hành động; 1-2 câu).

NỘI DUNG:
{content[:12000]}

Chỉ trả về JSON, không giải thích. Ví dụ: {{"summary": "...", "art_style": "..."}}"""
        messages = [{"role": "user", "content": prompt}]
        response = AIService.call_openrouter(
            messages=messages,
            model=model,
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        raw = AIService.clean_json_text(raw)
        data = json.loads(raw)
        return {
            "summary": str(data.get("summary", ""))[:2000],
            "art_style": str(data.get("art_style", ""))[:500],
        }
    except Exception as e:
        print(f"generate_chapter_metadata error: {e}")
        return {"summary": "", "art_style": ""}


def get_file_sample(file_content: str, sample_size: int = 80) -> str:
    """
    Lấy mẫu rải rác: 80 dòng đầu + 80 dòng giữa + 80 dòng cuối (nếu file dài).
    Trả về chuỗi kết hợp với marker [ĐẦU], [GIỮA], [CUỐI].
    """
    if not file_content or not str(file_content).strip():
        return ""
    lines = str(file_content).strip().splitlines()
    total_lines = len(lines)
    if total_lines <= sample_size * 3:
        return "\n".join(lines)
    parts = []
    parts.append(f"[ĐẦU FILE - {sample_size} dòng đầu]")
    parts.append("\n".join(lines[:sample_size]))
    mid_start = total_lines // 2 - sample_size // 2
    parts.append(f"\n\n[GIỮA FILE - {sample_size} dòng giữa (từ dòng {mid_start})]")
    parts.append("\n".join(lines[mid_start:mid_start + sample_size]))
    parts.append(f"\n\n[CUỐI FILE - {sample_size} dòng cuối]")
    parts.append("\n".join(lines[-sample_size:]))
    return "\n".join(parts)


def analyze_split_strategy(
    file_content: str,
    file_type: str = "story",
    context_hint: str = "",
) -> Dict[str, Any]:
    """
    AI Analyzer (Nhẹ): Phân tích mẫu rải rác (80 đầu + 80 giữa + 80 cuối) để tìm quy luật phân cách.
    Trả về {"split_type": "by_keyword"|"by_length"|"by_sheet", "split_value": str (regex/keyword)}.
    """
    if not file_content or not str(file_content).strip():
        return {"split_type": "by_length", "split_value": "2000"}
    sample = get_file_sample(file_content, sample_size=80)
    try:
        model = getattr(Config, "METADATA_MODEL", None) or "google/gemini-2.5-flash"
        type_hints = {
            "story": "Truyện - tìm quy luật phân cách chương (VD: 'Chương' viết hoa, dấu '***', xuống dòng 2 lần).",
            "character_data": "Dữ liệu nhân vật - tìm quy luật phân cách entity (VD: '##', '---', tên riêng ở đầu dòng).",
            "excel_export": "Excel/CSV - xác định cắt theo 'Sheet' marker hay 'Row count' (số dòng cố định).",
        }
        hint_text = type_hints.get(file_type.strip().lower(), type_hints["story"])
        if context_hint:
            hint_text += f"\nGợi ý người dùng: {context_hint}"
        prompt = f"""Phân tích mẫu file (80 dòng đầu + 80 dòng giữa + 80 dòng cuối) và TÌM QUY LUẬT PHÂN CÁCH.

Loại file: {hint_text}

MẪU FILE (240 dòng tổng hợp):
---
{sample}
---

NHIỆM VỤ: Tìm quy luật phân cách chương/thực thể/sheet trong file này.
- Ví dụ: "Chương" viết hoa ở đầu dòng, dấu "***", xuống dòng 2 lần, "[Sheet: X]", v.v.

YÊU CẦU: Trả về ĐÚNG MỘT JSON với:
- "split_type": một trong ["by_keyword", "by_length", "by_sheet"]
  * "by_keyword": Tìm thấy từ khóa/pattern lặp lại → trả về regex pattern hoặc keyword đơn giản
  * "by_length": Không tìm thấy pattern rõ ràng → cắt theo số ký tự cố định
  * "by_sheet": File Excel → cắt theo Sheet marker
- "split_value": 
  * Nếu by_keyword: Regex pattern (VD: "^Chương\\s+\\d+", "\\*{3,}", "^##\\s+") hoặc keyword đơn giản (VD: "Chương", "---")
  * Nếu by_length: số ký tự (VD: "2000")
  * Nếu by_sheet: "Sheet" hoặc "Row count"

QUAN TRỌNG: Chỉ trả về Regex pattern hoặc Keyword để Python dùng `re` module cắt file. KHÔNG cắt thực tế.

Ví dụ: {{"split_type": "by_keyword", "split_value": "^Chương\\s+\\d+"}}
Chỉ trả về JSON, không giải thích."""

        response = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = AIService.clean_json_text(raw)
        data = json.loads(raw)
        split_type = data.get("split_type", "by_length")
        split_value = str(data.get("split_value", "2000")).strip()
        if split_type not in ["by_keyword", "by_length", "by_sheet"]:
            split_type = "by_length"
        return {"split_type": split_type, "split_value": split_value}
    except Exception as e:
        print(f"analyze_split_strategy error: {e}")
        return {"split_type": "by_length", "split_value": "2000"}


def _build_smart_regex_pattern(keyword: str) -> str:
    """
    Xây dựng regex pattern hỗ trợ có dấu/không dấu và không phân biệt hoa thường.
    VD: "Chương" -> r"(?i)(CHƯƠNG|CHUONG|CHAPTER)\s+\d+[:\s-]*"
    """
    import re
    keyword_upper = keyword.upper().strip()
    if keyword_upper in ["CHƯƠNG", "CHUONG", "CHAPTER"]:
        return r"(?i)(CHƯƠNG|CHUONG|CHAPTER)\s+\d+[:\s-]*"
    elif keyword_upper in ["PHẦN", "PHAN", "PART"]:
        return r"(?i)(PHẦN|PHAN|PART)\s+\d+[:\s-]*"
    elif keyword_upper in ["---", "***", "==="]:
        return rf"(?i)\s*{re.escape(keyword)}\s*"
    else:
        return rf"(?i)^\s*{re.escape(keyword)}\s*"


def execute_split_logic(
    file_content: str,
    split_type: str,
    split_value: str,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """
    Python Worker (Mạnh): Cắt file bằng code Python thuần, không gọi AI.
    Trả về list of {"title": str, "content": str, "order": int}.
    debug=True: In ra debug log (dùng trong Streamlit với st.write).
    """
    if not file_content or not str(file_content).strip():
        return []
    content = str(file_content).strip()
    out = []
    try:
        if split_type == "by_keyword":
            import re
            pattern_str = split_value.strip()
            if not pattern_str:
                pattern_str = "---"
            
            is_regex = any(c in pattern_str for c in ["^", "$", "\\d", "\\s", "\\w", "\\+", "\\*", "\\?", "\\[", "\\(", "\\{", "("])
            
            if not is_regex:
                pattern_str = _build_smart_regex_pattern(pattern_str)
                is_regex = True
            
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
            except Exception as e:
                if debug:
                    print(f"Regex compile error: {e}, fallback to simple pattern")
                pattern_str = rf"^\s*{re.escape(split_value.strip())}\s*"
                pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
            
            matches = list(pattern.finditer(content))
            if debug:
                import streamlit as st
                st.write(f"🔍 **Debug Log:** Tìm thấy **{len(matches)}** vị trí phân cách:")
                for i, m in enumerate(matches[:10]):
                    line_num = content[:m.start()].count('\n') + 1
                    preview = content[max(0, m.start()-30):m.end()+30].replace('\n', ' ')
                    st.code(f"{i+1}. Dòng {line_num}: ...{preview}...", language=None)
                if len(matches) > 10:
                    st.caption(f"... và {len(matches) - 10} vị trí khác")
            
            if len(matches) == 0:
                if debug:
                    import streamlit as st
                    st.error("❌ **Không tìm thấy dấu hiệu phân chia chương.** Vui lòng kiểm tra lại định dạng hoặc thử keyword/pattern khác.")
                return []
            
            # Phần trước từ khóa đầu (nếu có)
            if matches[0].start() > 0:
                part_content = content[0:matches[0].start()].strip()
                if part_content:
                    title = "Phần mở đầu" if not out else "Phần 0"
                    out.append({"title": title, "content": part_content, "order": 1})
            
            # Nội dung NẰM GIỮA hai từ khóa: từ sau keyword[i] đến trước keyword[i+1]
            for i, match in enumerate(matches):
                start = match.end()  # Bắt đầu SAU từ khóa hiện tại
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                part_content = content[start:end].strip()
                if not part_content:
                    continue
                title = match.group(0).strip()[:50] if match.group(0) else f"Phần {len(out)+1}"
                if not title or len(title.strip()) < 2:
                    first_line = part_content.splitlines()[0] if part_content.splitlines() else ""
                    title = first_line[:50] if first_line else f"Phần {len(out)+1}"
                out.append({"title": title, "content": part_content, "order": len(out) + 1})
        elif split_type == "by_length":
            chunk_size = int(split_value) if split_value.isdigit() else 2000
            chunk_size = max(500, min(chunk_size, 50000))
            lines = content.splitlines()
            current_chunk = []
            current_len = 0
            chunk_num = 1
            for line in lines:
                line_len = len(line) + 1
                if current_len + line_len > chunk_size and current_chunk:
                    chunk_text = "\n".join(current_chunk).strip()
                    if chunk_text:
                        out.append({"title": f"Phần {chunk_num}", "content": chunk_text, "order": chunk_num})
                        chunk_num += 1
                    current_chunk = [line]
                    current_len = line_len
                else:
                    current_chunk.append(line)
                    current_len += line_len
            if current_chunk:
                chunk_text = "\n".join(current_chunk).strip()
                if chunk_text:
                    out.append({"title": f"Phần {chunk_num}", "content": chunk_text, "order": chunk_num})
        elif split_type == "by_sheet":
            import re
            if split_value.lower() == "row count" or split_value.isdigit():
                row_count = int(split_value) if split_value.isdigit() else 100
                lines = content.splitlines()
                for i in range(0, len(lines), row_count):
                    chunk_lines = lines[i:i + row_count]
                    if chunk_lines:
                        out.append({"title": f"Sheet {i // row_count + 1}", "content": "\n".join(chunk_lines), "order": i // row_count + 1})
            elif "[Sheet:" in content or "[Sheet " in content:
                pattern = re.compile(r"\[Sheet[:\s]+([^\]]+)\]", re.IGNORECASE)
                parts = pattern.split(content)
                current_sheet = "Sheet 1"
                current_content = []
                idx = 0
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        if part.strip():
                            current_content.append(part.strip())
                    else:
                        if current_content:
                            out.append({"title": current_sheet, "content": "\n".join(current_content), "order": idx + 1})
                            idx += 1
                        current_sheet = part.strip() or f"Sheet {idx + 2}"
                        current_content = []
                if current_content:
                    out.append({"title": current_sheet, "content": "\n".join(current_content), "order": idx + 1})
            else:
                out.append({"title": "Phần 1", "content": content, "order": 1})
        else:
            out.append({"title": "Phần 1", "content": content, "order": 1})
        return out
    except Exception as e:
        print(f"execute_split_logic error: {e}")
        return [{"title": "Phần 1", "content": content, "order": 1}]


# ==========================================
# 🧬 RULE MINING SYSTEM
# ==========================================
class RuleMiningSystem:
    """Hệ thống khai thác và quản lý luật từ chat"""

    @staticmethod
    def extract_rule_raw(user_prompt: str, ai_response: str) -> Optional[str]:
        """Trích xuất luật thô từ hội thoại"""
        prompt = f"""
        Bạn là "Trinh Sát Luật" (Rule Scout). Nhiệm vụ: Phát hiện sở thích/yêu cầu của User.

        HỘI THOẠI:
        - User: "{user_prompt}"
        - AI: (Phản hồi trước đó...)

        MỤC TIÊU:
        Phát hiện xem User có đang ngầm chỉ định CÁCH LÀM VIỆC, CÁCH VIẾT, hoặc ĐỊNH DẠNG không.

        TIÊU CHÍ (Độ nhạy cao):
        1. Yêu cầu định dạng: "chỉ json", "dùng markdown", "đừng viết code", "viết ngắn thôi".
        2. Điều chỉnh văn phong: "nghiêm túc hơn", "bớt nói nhảm", "dùng tiếng Việt".
        3. Sửa lỗi: "sai rồi", "không phải thế", "làm thế này mới đúng".

        HƯỚNG DẪN:
        - Nếu User nói: "Viết cái này bằng Python nhé" -> Tạo luật: "Luôn ưu tiên dùng Python".
        - Thà bắt nhầm còn hơn bỏ sót.

        OUTPUT:
        - Nếu phát hiện luật: Trả về 1 câu mệnh lệnh ngắn gọn kèm ngữ cảnh (Tiếng Việt). Ví dụ: "Luôn trả về định dạng JSON khi được yêu cầu...", "Không giải thích dài dòng khi user đang khó chịu...".
        - Nếu chỉ là chào hỏi/cảm ơn: Trả về "NO_RULE".

        Chỉ trả về Text.
        """

        messages = [
            {"role": "system", "content": "You are Rule Extractor. Return text only."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.3,
                max_tokens=300
            )

            text = response.choices[0].message.content.strip()

            if "NO_RULE" in text or len(text) < 5:
                return None
            return text
        except Exception as e:
            print(f"Rule extraction error: {e}")
            return None

    @staticmethod
    def analyze_rule_conflict(new_rule_content: str, project_id: str) -> Dict:
        """Check rule conflict with DB - Safe Version"""
        similar_rules_str = HybridSearch.smart_search_hybrid(new_rule_content, project_id, top_k=3)

        if not similar_rules_str:
            return {
                "status": "NEW",
                "reason": "No conflicts found",
                "existing_rule_summary": "None",
                "merged_content": None,
                "suggested_content": new_rule_content
            }

        judge_prompt = f"""
        Luật Mới: "{new_rule_content}"
        Luật Cũ trong DB: "{similar_rules_str}"

        Nhiệm vụ: So sánh mối quan hệ.

        - CONFLICT (Xung đột): Mâu thuẫn trực tiếp (Vd: Cũ bảo A, Mới bảo không A).
        - MERGE (Gộp): Cùng chủ đề nhưng luật Mới chi tiết hơn hoặc bổ sung cho luật Cũ.
        - NEW (Mới): Chủ đề khác hẳn.

        OUTPUT JSON ONLY:
        {{
            "status": "CONFLICT" | "MERGE" | "NEW",
            "existing_rule_summary": "Tóm tắt luật cũ (Tiếng Việt)",
            "reason": "Lý do (Tiếng Việt)",
            "merged_content": "Nội dung luật đã gộp hoàn chỉnh (nếu MERGE). Nếu khác thì để null."
        }}
        """

        messages = [
            {"role": "system", "content": "You are Rule Judge. Return only JSON."},
            {"role": "user", "content": judge_prompt}
        ]

        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.2,
                max_tokens=4000,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)

            result = json.loads(content)

            return {
                "status": result.get("status", "NEW"),
                "reason": result.get("reason", "No reason provided by AI"),
                "existing_rule_summary": result.get("existing_rule_summary", "N/A"),
                "merged_content": result.get("merged_content", None),
                "suggested_content": new_rule_content
            }

        except Exception as e:
            print(f"Rule analysis error: {e}")
            return {
                "status": "NEW",
                "reason": f"AI Judge Error: {str(e)}",
                "existing_rule_summary": "Error analyzing",
                "merged_content": None,
                "suggested_content": new_rule_content
            }

    @staticmethod
    def crystallize_session(chat_history: List[Dict], persona_role: str) -> str:
        """Tóm tắt và lọc thông tin giá trị từ chat history"""
        chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history])

        crystallize_prompt = f"""
        Bạn là Thư Ký Cuộc Họp ({persona_role}).
        
        Nhiệm vụ: Đọc đoạn chat dưới đây và LỌC BỎ NHỮNG THỨ VÔ NGHĨA.
        Chỉ giữ lại và TÓM TẮT những thông tin giá trị (Sự kiện, Ý tưởng, Quyết định, Lore mới).

        CHAT LOG: {chat_text}

        OUTPUT: Trả về bản tóm tắt súc tích (50-100 từ) bằng Tiếng Việt. 
        Nếu toàn là chào hỏi vô nghĩa, trả về "NO_INFO".
        """

        messages = [
            {"role": "system", "content": "You are Conversation Summarizer. Return text only."},
            {"role": "user", "content": crystallize_prompt}
        ]

        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=Config.ROUTER_MODEL,
                temperature=0.3,
                max_tokens=8000
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Crystallize error: {e}")
            return f"AI Error: {e}"
