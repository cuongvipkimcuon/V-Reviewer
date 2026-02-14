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


def _get_default_tool_model() -> str:
    """Model mặc định cho Router, Planner và các công cụ (từ Settings > AI Model)."""
    try:
        model = st.session_state.get("default_ai_model") or getattr(Config, "DEFAULT_TOOL_MODEL", None)
        return model or Config.ROUTER_MODEL
    except Exception:
        return getattr(Config, "DEFAULT_TOOL_MODEL", None) or Config.ROUTER_MODEL


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


# Giới hạn token cho lịch sử chat đưa vào Router/Planner (tránh vượt context window).
ROUTER_PLANNER_CHAT_HISTORY_MAX_TOKENS = 6000


def cap_chat_history_to_tokens(text: str, max_tokens: int = ROUTER_PLANNER_CHAT_HISTORY_MAX_TOKENS) -> str:
    """Cắt lịch sử chat sao cho không vượt max_tokens; giữ phần đuôi (tin nhắn gần nhất)."""
    if not text or max_tokens <= 0:
        return text or ""
    est = AIService.estimate_tokens(text)
    if est <= max_tokens:
        return text
    # Giữ đuôi: cắt từ đầu. Ước tính ~4 ký tự/token.
    target_chars = max_tokens * 4
    if len(text) <= target_chars:
        return text
    out = text[-target_chars:]
    while AIService.estimate_tokens(out) > max_tokens and len(out) > 500:
        out = out[500:]
    return out


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


def parse_chapter_range_from_query(query: str) -> Optional[Tuple[int, int]]:
    """
    Trích số chương từ câu hỏi (chương 1, chapter 5, chương 5 đến 10, từ chương 3 tới 7...).
    Trả về (start, end) hoặc None nếu không nhận diện được. Dùng cho fallback read_full_content khi search_chunks không có số chương trong chunk.
    """
    if not query or not isinstance(query, str) or not query.strip():
        return None
    q = query.strip().lower()
    # Khoảng: "chương 5 đến 10", "từ chương 3 tới 7", "chapter 2 to 5"
    range_match = re.search(
        r"(?:chương|chapter)\s*(\d+)\s*(?:đến|tới|to|-)\s*(?:chương|chapter)?\s*(\d+)",
        q,
        re.IGNORECASE,
    )
    if range_match:
        try:
            a, b = int(range_match.group(1)), int(range_match.group(2))
            return (min(a, b), max(a, b))
        except (ValueError, IndexError):
            pass
    # Một chương: "chương 1", "chapter 3", "chương 5"
    single_match = re.search(r"(?:chương|chapter)\s*(\d+)", q, re.IGNORECASE)
    if single_match:
        try:
            n = int(single_match.group(1))
            if n >= 1:
                return (n, n)
        except (ValueError, IndexError):
            pass
    return None


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


def get_timeline_events(project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Lấy sự kiện timeline của project (bảng timeline_events V7). Trả về [] nếu bảng chưa có hoặc lỗi."""
    if not project_id:
        return []
    try:
        services = init_services()
        if not services:
            return []
        supabase = services["supabase"]
        r = (
            supabase.table("timeline_events")
            .select("id, event_order, title, description, raw_date, event_type, chapter_id")
            .eq("story_id", project_id)
            .order("event_order")
            .limit(limit)
            .execute()
        )
        return list(r.data) if r.data else []
    except Exception as e:
        print(f"get_timeline_events error: {e}")
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
            model=_get_default_tool_model(),
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
        """Router V2: Phân tích Intent và Target Files, có inject bible_index để nhận diện ý định.
        chat_history_text được giới hạn token để không vượt context window."""
        chat_history_text = cap_chat_history_to_tokens(chat_history_text or "")
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
### VAI TRÒ
Bạn là AI Điều Phối Viên (Router) cho hệ thống V7-Universal. Nhiệm vụ của bạn là phân tích Input của User và quyết định công cụ (Intent) chính xác nhất để xử lý. Chỉ trả về JSON.

### 1. DỮ LIỆU ĐẦU VÀO
- QUY TẮC DỰ ÁN: {rules_context}
- BẢNG PREFIX ENTITY: {prefix_setup_str}
- DANH SÁCH ENTITY (Bible): {bible_index if bible_index else "(Trống)"}
- LỊCH SỬ CHAT: {chat_history_text}

### 2. BẢNG QUY TẮC CHỌN INTENT (ƯU TIÊN TỪ TRÊN XUỐNG)

| INTENT | ĐIỀU KIỆN KÍCH HOẠT (TRIGGER) | TỪ KHÓA NHẬN DIỆN |
| :--- | :--- | :--- |
| **ask_user_clarification** | Câu hỏi quá ngắn, mơ hồ, thiếu chủ ngữ hoặc không rõ ngữ cảnh. | "Tính đi", "Nó là ai", "Cái đó sao rồi" (khi không có history). |
| **web_search** | Cần thông tin **THỰC TẾ, THỜI GIAN THỰC** bên ngoài dự án. | "Tỷ giá", "Giá vàng", "Thời tiết", "Tin tức", "Thông số súng Glock ngoài đời", "mới nhất", "tra cứu". |
| **numerical_calculation** | Yêu cầu **TÍNH TOÁN CON SỐ**, thống kê, so sánh dữ liệu định lượng. | "Tính tổng", "Doanh thu", "Trung bình", "Đếm số lượng", "% tăng trưởng". |
| **update_data** | User ra lệnh **GHI NHỚ**, cập nhật, sửa đổi dữ liệu hệ thống. | "Hãy nhớ rằng...", "Cập nhật lại...", "Sửa quy tắc...", "Thêm nhân vật...". |
| **read_full_content** | 1. Nhắc **TÊN FILE** hoặc **SỐ CHƯƠNG** cụ thể. 2. Yêu cầu: Tóm tắt, Review, Viết tiếp, Kiểm tra logic toàn bài. | "Chương 1", "Chapter 5", "File luong.xlsx", "Tóm tắt chương này". |
| **manage_timeline** | Hỏi về **THỨ TỰ THỜI GIAN**, sự kiện trước/sau, timeline, flashback. | "Sự kiện nào trước", "Sau khi A chết thì...", "Mốc thời gian", "Năm bao nhiêu". |
| **query_Sql** | Hỏi chi tiết về **THUỘC TÍNH ĐỐI TƯỢNG** (Structure Data) trong DB. | "Nhân vật A là ai", "Địa điểm B có đặc điểm gì". |
| **mixed_context** | Cần **CẢ** nội dung file/chương **VÀ** thông tin Bible (vừa đoạn văn vừa nhân vật/lore). | "Trong chương 3 nhân vật A làm gì và quan hệ với B", "Nội dung chương 5 kết hợp mô tả nhân vật". |
| **search_chunks** | Hỏi **CHI TIẾT VỤN VẶT** trong văn bản nhưng **KHÔNG** nhắc số chương cụ thể. | "Ai nói câu...", "Hùng cầm vũ khí gì", "Chi tiết cái áo màu đỏ". |
| **search_bible** | Hỏi về Lore, cốt truyện chung, khái niệm, quan hệ nhân vật; **hoặc** user tham chiếu nội dung đã nói trong chat (crystallize). | (Tên nhân vật trong Bible), "Thế giới này vận hành sao", "Quy tắc phép thuật"; "như tôi đã nói về...", "chủ đề trước đó", "đoạn chat trước về X". |
| **chat_casual** | Chào hỏi xã giao, không yêu cầu dữ liệu hay tra cứu. | "Hello", "Cảm ơn", "Bạn khỏe không". |

### 3. HƯỚNG DẪN XỬ LÝ ĐẶC BIỆT (CRITICAL RULES)
1. **Quy tắc "Chương Cụ Thể":** Nếu user nhắc "Chương X", "Chapter Y" -> BẮT BUỘC chọn `read_full_content`. Tuyệt đối KHÔNG chọn `search_chunks`.
2. **Quy tắc "Thực Tế":** Nếu hỏi tỷ giá, tin tức, thời tiết, giá vàng, thông số thực tế -> BẮT BUỘC chọn `web_search`. Tuyệt đối KHÔNG chọn `chat_casual` hay `search_bible`.
3. **Quy tắc "Làm Rõ":** Nếu không hiểu user muốn gì (câu quá ngắn/mơ hồ) -> Chọn `ask_user_clarification` và điền `clarification_question`.
4. **Quy tắc "Tham chiếu chat cũ":** Nếu tin nhắn mới CHỈ là tham chiếu đến lệnh/câu hỏi trước (vd: "làm cái đó", "ok làm đi", "như vừa nói", "thực hiện đi", "đúng rồi làm đi") thì dựa vào LỊCH SỬ CHAT: lấy lại intent và rewritten_query của tin nhắn user gần nhất có nội dung cụ thể, điền vào output. Ví dụ: history có "user: Tóm tắt chương 1" rồi "model: ..." rồi "user: làm đi" -> intent vẫn read_full_content, rewritten_query "Tóm tắt chương 1".
5. **Quy tắc "Tham chiếu nội dung chat (crystallize)":** Nếu user nói đã bàn / đã nói về chủ đề X trong chat (vd: "như tôi đã nói về nhân vật A", "chủ đề trước đó về timeline", "theo đoạn chat trước về quy tắc") -> chọn `search_bible`. Điền `rewritten_query` là chủ đề hoặc từ khóa cần tìm (vd: "nhân vật A", "timeline", "quy tắc đã thảo luận"). Hệ thống sẽ tìm trong Bible kể cả entry [CHAT] (crystallize từ chat).

### 4. LOGIC TRÍCH XUẤT CHAPTER RANGE
- "Chương 1", "Chap 5" -> chapter_range_mode: "range", chapter_range: [1, 1] hoặc [5, 5]
- "Chương 1 đến 5" -> chapter_range_mode: "range", chapter_range: [1, 5]
- "3 chương đầu", "mấy chương đầu" -> chapter_range_mode: "first", chapter_range_count: 3 (hoặc số user nói)
- "Chương mới nhất", "mấy chương cuối" -> chapter_range_mode: "latest", chapter_range_count: 1 (hoặc số user nói)
- Không liên quan chương -> chapter_range: null, chapter_range_mode: null

### 5. VÍ DỤ MINH HỌA (FEW-SHOT)

**Input:** "Tóm tắt nội dung chương 1 cho anh."
**Output:** {{ "intent": "read_full_content", "reason": "User yêu cầu tóm tắt và chỉ định chương 1.", "chapter_range": [1, 1], "chapter_range_mode": "range", "rewritten_query": "Tóm tắt chương 1", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Thằng Hùng sử dụng loại súng nào trong truyện?" (Không nhắc chương)
**Output:** {{ "intent": "search_chunks", "reason": "Hỏi chi tiết cụ thể về nhân vật Hùng, không rõ vị trí chương.", "target_bible_entities": ["Hùng"], "rewritten_query": "Hùng sử dụng súng gì", "target_files": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Tỷ giá USD/VND hôm nay bao nhiêu?"
**Output:** {{ "intent": "web_search", "reason": "Hỏi thông tin thời gian thực ngoài hệ thống.", "rewritten_query": "Tỷ giá USD VND hôm nay", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Sự kiện Hùng gặp Thảo xảy ra trước hay sau vụ nổ?"
**Output:** {{ "intent": "manage_timeline", "reason": "Hỏi về thứ tự trước sau của 2 sự kiện.", "rewritten_query": "So sánh thời gian sự kiện Hùng gặp Thảo và vụ nổ", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Tính tổng doanh thu của 3 tháng đầu năm."
**Output:** {{ "intent": "numerical_calculation", "reason": "Yêu cầu tính toán tổng số liệu.", "rewritten_query": "Tổng doanh thu 3 tháng đầu năm", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "", "update_summary": "" }}

**Input:** "Lưu ý quy tắc này: Không được viết tắt tên nhân vật."
**Output:** {{ "intent": "update_data", "reason": "User ra lệnh ghi nhớ quy tắc.", "update_summary": "Thêm quy tắc cấm viết tắt tên nhân vật vào hệ thống.", "rewritten_query": "Ghi nhớ quy tắc", "target_files": [], "target_bible_entities": [], "inferred_prefixes": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5, "clarification_question": "" }}

### 6. INPUT CỦA USER
"{user_prompt}"

### 7. OUTPUT (JSON ONLY) — Trả về đúng format sau, đủ các key:
{{
    "intent": "ask_user_clarification" | "web_search" | "numerical_calculation" | "update_data" | "read_full_content" | "manage_timeline" | "query_Sql" | "mixed_context" | "search_chunks" | "search_bible" | "chat_casual",
    "target_files": [],
    "target_bible_entities": [],
    "inferred_prefixes": [],
    "reason": "Lý do ngắn gọn bằng tiếng Việt",
    "rewritten_query": "Viết lại câu hỏi cho search",
    "chapter_range": null hoặc [start, end],
    "chapter_range_mode": null hoặc "first" | "latest" | "range",
    "chapter_range_count": 5,
    "clarification_question": "" hoặc "Câu hỏi gợi ý (khi intent ask_user_clarification)",
    "update_summary": "" hoặc "Mô tả thao tác (khi intent update_data)"
}}
"""

        messages = [
            {"role": "system", "content": "Bạn là AI Router thông minh. Chỉ trả về JSON."},
            {"role": "user", "content": router_prompt}
        ]

        try:
            response = AIService.call_openrouter(
                messages=messages,
                model=_get_default_tool_model(),
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
            result.setdefault("clarification_question", "")
            result.setdefault("update_summary", "")
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
                "clarification_question": "",
                "update_summary": "",
            }

    @staticmethod
    def get_plan_v7(user_prompt: str, chat_history_text: str, project_id: str = None) -> Dict:
        """
        V7 Agentic Planner: Trả về plan (mảng bước) thay vì single intent.
        Return: { "analysis": str, "plan": [ { step_id, intent, args: { query_refined, target_files, target_bible_entities, chapter_range, ... } } ], "verification_required": bool }
        Nếu câu hỏi đơn giản -> plan 1 bước. Câu phức tạp (vd so sánh timeline + Bible) -> nhiều bước.
        Fallback: nếu parse lỗi hoặc API trả format cũ (single intent) -> chuyển thành plan 1 bước.
        """
        rules_context = ""
        bible_index = ""
        prefix_setup_str = ""
        if project_id:
            rules_context = ContextManager.get_mandatory_rules(project_id)
            bible_index = get_bible_index(project_id, max_tokens=2000)
        try:
            prefix_setup = Config.get_prefix_setup()
            prefix_setup_str = "\n".join(
                f"- [{p.get('prefix_key', '')}]: {p.get('description', '')}" for p in (prefix_setup or [])
            ) if prefix_setup else "(Chưa cấu hình Bible Prefix.)"
        except Exception:
            prefix_setup_str = "(Chưa cấu hình Bible Prefix.)"

        # Giới hạn lịch sử chat theo token để không vượt context (giữ tin gần nhất).
        chat_history_capped = cap_chat_history_to_tokens(chat_history_text or "")
        planner_prompt = f"""Bạn là V7 Planner. Nhiệm vụ: phân tích câu user và đưa ra KẾ HOẠCH (mảng bước) thực thi.

DỮ LIỆU: QUY TẮC={rules_context[:1500]} | PREFIX={prefix_setup_str[:800]} | BIBLE INDEX={bible_index[:2000] if bible_index else "(Trống)"} | LỊCH SỬ={chat_history_capped}

INPUT USER: "{user_prompt}"

QUY TẮC:
- **Tham chiếu chat cũ:** Nếu user chỉ nói kiểu xác nhận/tham chiếu (vd: "làm cái đó", "ok làm đi", "như vừa nói", "thực hiện đi") thì dựa vào LỊCH SỬ: lấy lại ý định/câu hỏi của tin nhắn user gần nhất có nội dung cụ thể, dùng làm query_refined và intent tương ứng cho plan 1 bước.
- **Tham chiếu nội dung chat (crystallize):** Nếu user nói đã bàn/đã nói về chủ đề X (vd: "như tôi đã nói về nhân vật A", "chủ đề trước đó về timeline") -> dùng intent `search_bible`, query_refined = chủ đề/từ khóa cần tìm (Bible gồm cả entry [CHAT] crystallize).
- Câu ĐƠN GIẢN (một ý): trả về plan có 1 bước với intent phù hợp.
- Câu PHỨC TẠP (nhiều ý): tách thành nhiều bước. VD: "Kiểm tra thứ tự sự kiện A rồi so với quy tắc Bible" -> step1: manage_timeline (lấy sự kiện A), step2: search_bible (lấy quy tắc).
- Mỗi bước: step_id (số từ 1), intent (đúng tên: manage_timeline | numerical_calculation | read_full_content | search_chunks | search_bible | mixed_context | web_search | ask_user_clarification | update_data | query_Sql | chat_casual), args (query_refined, target_files[], target_bible_entities[], chapter_range null hoặc [a,b], chapter_range_mode, chapter_range_count). dependency: null hoặc step_id bước trước (thường null vì chạy tuần tự).
- verification_required: true nếu plan có numerical_calculation, manage_timeline, hoặc bất kỳ intent cần grounding (read_full_content, search_chunks, search_bible, mixed_context, query_Sql); ngược lại false.

Trả về ĐÚNG MỘT JSON:
{{
  "analysis": "Giải thích ngắn tại sao chọn các bước này",
  "plan": [
    {{ "step_id": 1, "intent": "tên_intent", "args": {{ "query_refined": "...", "target_files": [], "target_bible_entities": [], "chapter_range": null, "chapter_range_mode": null, "chapter_range_count": 5 }}, "dependency": null }}
  ],
  "verification_required": true
}}
Chỉ trả về JSON."""

        try:
            response = AIService.call_openrouter(
                messages=[
                    {"role": "system", "content": "Bạn là V7 Planner. Chỉ trả về JSON với analysis, plan, verification_required."},
                    {"role": "user", "content": planner_prompt}
                ],
                model=_get_default_tool_model(),
                temperature=0.1,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            content = AIService.clean_json_text(content)
            data = json.loads(content)
        except Exception as e:
            print(f"Planner V7 error: {e}")
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)

        plan = data.get("plan")
        if not plan or not isinstance(plan, list):
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)

        analysis = data.get("analysis", "")
        verification_required = bool(data.get("verification_required", False))
        normalized_plan = []
        for i, s in enumerate(plan):
            if not isinstance(s, dict):
                continue
            intent = (s.get("intent") or "chat_casual").strip()
            args = s.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            step_id = int(s.get("step_id", i + 1))
            dependency = s.get("dependency")
            normalized_plan.append({
                "step_id": step_id,
                "intent": intent,
                "args": {
                    "query_refined": args.get("query_refined") or args.get("rewritten_query") or user_prompt,
                    "target_files": args.get("target_files") if isinstance(args.get("target_files"), list) else [],
                    "target_bible_entities": args.get("target_bible_entities") if isinstance(args.get("target_bible_entities"), list) else [],
                    "chapter_range": args.get("chapter_range"),
                    "chapter_range_mode": args.get("chapter_range_mode"),
                    "chapter_range_count": args.get("chapter_range_count", 5),
                    "inferred_prefixes": args.get("inferred_prefixes") if isinstance(args.get("inferred_prefixes"), list) else [],
                    "clarification_question": args.get("clarification_question") or "",
                    "update_summary": args.get("update_summary") or "",
                },
                "dependency": dependency,
            })
        if not normalized_plan:
            single = SmartAIRouter.ai_router_pro_v2(user_prompt, chat_history_text, project_id)
            return SmartAIRouter._single_intent_to_plan(single, user_prompt)

        # Bật verify nếu plan chứa bất kỳ intent cần numerical/timeline/grounding
        intents_need_verify = {"numerical_calculation", "manage_timeline", "read_full_content", "search_chunks", "search_bible", "mixed_context", "query_Sql"}
        if any(s.get("intent") in intents_need_verify for s in normalized_plan):
            verification_required = True

        return {
            "analysis": analysis,
            "plan": normalized_plan,
            "verification_required": verification_required,
        }

    @staticmethod
    def _single_intent_to_plan(single_router_result: Dict, user_prompt: str) -> Dict:
        """Chuyển kết quả router single-intent thành plan 1 bước (tương thích V7)."""
        intent = single_router_result.get("intent", "chat_casual")
        return {
            "analysis": single_router_result.get("reason", ""),
            "plan": [{
                "step_id": 1,
                "intent": intent,
                "args": {
                    "query_refined": single_router_result.get("rewritten_query") or user_prompt,
                    "target_files": single_router_result.get("target_files") or [],
                    "target_bible_entities": single_router_result.get("target_bible_entities") or [],
                    "chapter_range": single_router_result.get("chapter_range"),
                    "chapter_range_mode": single_router_result.get("chapter_range_mode"),
                    "chapter_range_count": single_router_result.get("chapter_range_count", 5),
                    "inferred_prefixes": single_router_result.get("inferred_prefixes") or [],
                    "clarification_question": single_router_result.get("clarification_question") or "",
                    "update_summary": single_router_result.get("update_summary") or "",
                },
                "dependency": None,
            }],
            "verification_required": intent in (
                "numerical_calculation", "manage_timeline",
                "read_full_content", "search_chunks", "search_bible", "mixed_context", "query_Sql",
            ),
        }


# ==========================================
# 🔄 V7 DYNAMIC RE-PLANNING
# ==========================================
def evaluate_step_outcome(intent: str, ctx_text: str, sources: List[str]) -> Tuple[bool, str]:
    """
    Đánh giá bước vừa chạy: có "thất bại" (không tìm thấy dữ liệu) cần cân nhắc re-plan không.
    Returns: (should_consider_replan, reason).
    """
    if not intent or intent in ("chat_casual", "ask_user_clarification", "update_data", "web_search"):
        return False, ""
    ctx_upper = (ctx_text or "").upper()
    ctx_lower = (ctx_text or "").lower()
    src_list = sources or []

    if intent == "read_full_content":
        if "--- TARGET CONTENT ---" not in ctx_text and "NỘI DUNG CHƯƠNG" not in ctx_text:
            return True, "read_full_content: không tìm thấy file/chương (target content trống)"
        return False, ""

    if intent == "search_chunks":
        has_chunk = any("chunk" in s.lower() or "reverse" in s.lower() for s in src_list)
        has_fallback = "Chapter fallback" in str(src_list) or "NỘI DUNG CHƯƠNG" in ctx_text
        if not has_chunk and not has_fallback:
            return True, "search_chunks: không tìm thấy chunk hoặc fallback chương"
        return False, ""

    if intent == "search_bible":
        has_bible = "📚" in str(src_list) or "KNOWLEDGE BASE" in ctx_upper or "--- " in ctx_text and "---" in ctx_text
        if not has_bible or (len(ctx_text or "") < 500 and "Bible" not in ctx_text):
            return True, "search_bible: không tìm thấy dữ liệu Bible"
        return False, ""

    if intent == "mixed_context":
        has_any = "📚" in str(src_list) or "RELATED FILES" in ctx_text or "Timeline" in ctx_upper or "Chunk" in str(src_list)
        if not has_any:
            return True, "mixed_context: không có Bible, file, timeline hay chunk"
        return False, ""

    if intent == "manage_timeline":
        if "[TIMELINE] Chưa có dữ liệu" in ctx_text or "Timeline (empty)" in str(src_list):
            return True, "manage_timeline: chưa có dữ liệu timeline_events"
        return False, ""

    if intent == "query_Sql":
        if "KNOWLEDGE BASE (query_Sql" not in ctx_text and "🔍 Query SQL" not in str(src_list):
            return True, "query_Sql: không có dữ liệu Bible/đối tượng"
        return False, ""

    return False, ""


def replan_after_step(
    user_prompt: str,
    cumulative_context: str,
    step_results: List[Dict],
    step_just_done: Dict,
    outcome_reason: str,
    remaining_plan: List[Dict],
    project_id: Optional[str] = None,
) -> Tuple[str, str, List[Dict]]:
    """
    Gọi LLM quyết định: continue / replace / abort sau khi một bước thất bại (không tìm thấy dữ liệu).
    Returns: (action, reason, new_plan). new_plan chỉ có khi action == "replace".
    """
    intent_done = step_just_done.get("intent", "chat_casual")
    args_done = step_just_done.get("args") or {}
    remaining_summary = json.dumps([{"step_id": s.get("step_id"), "intent": s.get("intent")} for s in remaining_plan], ensure_ascii=False)

    prompt_text = f"""User hỏi: "{user_prompt[:500]}"

Vừa thực thi xong bước: intent={intent_done}, args={json.dumps(args_done, ensure_ascii=False)[:300]}.
Kết quả bước này: {outcome_reason} (không tìm thấy dữ liệu / thất bại).

Context đã tích lũy (rút gọn): {cumulative_context[:2500]}...

Kế hoạch còn lại (chưa chạy): {remaining_summary}

Nhiệm vụ: Quyết định một trong ba:
1. **continue** – Giữ nguyên plan còn lại, chạy tiếp (thử bước tiếp theo).
2. **replace** – Thay thế plan còn lại bằng plan mới (vd: thay "tìm file A" bằng "tìm file B", hoặc đổi intent khác phù hợp). Trả về new_plan là mảng bước thay thế (format giống plan: step_id, intent, args với query_refined, target_files, target_bible_entities, chapter_range, ...).
3. **abort** – Dừng thực thi, không chạy thêm bước; trả lời dựa trên context hiện có.

Trả về ĐÚNG MỘT JSON (chỉ JSON, không giải thích):
{{ "action": "continue" | "replace" | "abort", "reason": "Lý do ngắn", "new_plan": [] }}

Với action=replace thì new_plan phải có ít nhất 1 bước. Với continue/abort thì new_plan để []."""

    try:
        r = AIService.call_openrouter(
            messages=[
                {"role": "system", "content": "Bạn là V7 Re-planner. Chỉ trả về JSON với action, reason, new_plan."},
                {"role": "user", "content": prompt_text},
            ],
            model=_get_default_tool_model(),
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        content = AIService.clean_json_text(r.choices[0].message.content or "{}")
        data = json.loads(content)
        action = (data.get("action") or "continue").strip().lower()
        if action not in ("continue", "replace", "abort"):
            action = "continue"
        reason = str(data.get("reason") or "").strip() or outcome_reason
        new_plan = data.get("new_plan") if isinstance(data.get("new_plan"), list) else []
        if action == "replace" and not new_plan:
            action = "continue"
            new_plan = []
        return action, reason, new_plan
    except Exception as e:
        print(f"replan_after_step error: {e}")
        return "continue", "", []


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
            events = get_timeline_events(project_id)
            if events:
                lines = ["[TIMELINE EVENTS - Thứ tự sự kiện / mốc thời gian]"]
                for e in events:
                    order = e.get("event_order", 0)
                    title = e.get("title", "")
                    desc = (e.get("description") or "")[:800]
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
            update_summary = router_result.get("update_summary", "") or "Ghi nhớ / cập nhật dữ liệu theo yêu cầu user."
            context_parts.append(f"[CẬP NHẬT DỮ LIỆU - CẦN XÁC NHẬN]\n{update_summary}\n\nThao tác này chỉ thực hiện sau khi user xác nhận. Trả lời tóm tắt nội dung sẽ được ghi và nhắc user xác nhận trước khi thực hiện.")
            sources.append("✏️ Update (pending confirm)")

        elif intent == "query_Sql":
            # Dữ liệu đối tượng (entity, thuộc tính): Bible + chapters. Không dùng timeline_events (đó là manage_timeline).
            rewritten = (router_result.get("rewritten_query") or "").strip() or (router_result.get("target_bible_entities") or [""])[0]
            sql_context_parts = []
            raw_list = HybridSearch.smart_search_hybrid_raw(rewritten, project_id, top_k=5) if rewritten else []
            if raw_list:
                part = format_bible_context_by_sections(raw_list)
                sql_context_parts.append(f"\n--- KNOWLEDGE BASE (query_Sql - đối tượng) ---\n{part}")
            if sql_context_parts:
                block = "\n".join(sql_context_parts)
                context_parts.append(block)
                total_tokens += AIService.estimate_tokens(block)
                sources.append("🔍 Query SQL")
            else:
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

        # mixed_context: bổ sung timeline + chunks (Bible và file đã có ở trên) để đủ nguồn trả lời.
        if intent == "mixed_context":
            events = get_timeline_events(project_id, limit=30)
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


# ==========================================
# 📝 AUTO-SUMMARY / CHAPTER METADATA (V5)
# ==========================================
def suggest_import_category(text: str) -> str:
    """Gợi ý prefix/category cho nội dung import (dùng LLM nhẹ). Dùng prefix từ DB (get_prefixes), trả về [OTHER] nếu không khớp."""
    if not text or len(text.strip()) < 20:
        return "[OTHER]"
    try:
        model = _get_default_tool_model()
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
        model = _get_default_tool_model()
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
    """Dùng model từ Settings để tóm tắt nội dung và phân tích art_style. Trả về {"summary": "...", "art_style": "..."}. Defensive: trả về dict rỗng nếu lỗi."""
    if not content or not str(content).strip():
        return {"summary": "", "art_style": ""}
    try:
        model = _get_default_tool_model()
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


def extract_timeline_events_from_content(content: str, chapter_label: str = "") -> List[Dict[str, Any]]:
    """
    AI trích xuất các sự kiện timeline từ nội dung chương (thứ tự, mốc thời gian, flashback).
    Trả về list [{"event_order": int, "title": str, "description": str, "raw_date": str, "event_type": "event"|"flashback"|"milestone"|"timeskip"|"other"}].
    """
    if not content or not str(content).strip():
        return []
    try:
        model = _get_default_tool_model()
        ctx = f"Chương: {chapter_label}\n\n" if chapter_label else ""
        prompt = f"""Trích xuất các SỰ KIỆN theo thứ tự thời gian từ nội dung dưới đây. Mỗi sự kiện có thứ tự (event_order bắt đầu 1), tiêu đề ngắn, mô tả, thời điểm (raw_date: có thể là "đầu chương", "sau khi X", "trước chiến tranh", năm, v.v.), và loại (event_type: event, flashback, milestone, timeskip, other).

{ctx}NỘI DUNG:
{content[:25000]}

Trả về ĐÚNG MỘT JSON với key "events" là mảng các object:
{{ "event_order": 1, "title": "...", "description": "...", "raw_date": "...", "event_type": "event" }}
event_type chỉ được là một trong: event, flashback, milestone, timeskip, other.
Nếu không có sự kiện rõ ràng, trả về {{ "events": [] }}. Chỉ trả về JSON."""
        response = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = AIService.clean_json_text(raw)
        data = json.loads(raw)
        events = data.get("events") if isinstance(data, dict) else []
        if not isinstance(events, list):
            return []
        out = []
        for i, e in enumerate(events):
            if not isinstance(e, dict):
                continue
            order = int(e.get("event_order", i + 1))
            title = str(e.get("title", "")).strip() or f"Sự kiện {order}"
            desc = str(e.get("description", ""))[:2000]
            raw_date = str(e.get("raw_date", ""))[:200]
            etype = str(e.get("event_type", "event")).lower()
            if etype not in ("event", "flashback", "milestone", "timeskip", "other"):
                etype = "event"
            out.append({
                "event_order": order,
                "title": title,
                "description": desc,
                "raw_date": raw_date,
                "event_type": etype,
            })
        return out
    except Exception as ex:
        print(f"extract_timeline_events_from_content error: {ex}")
        return []


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
        model = _get_default_tool_model()
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
                model=_get_default_tool_model(),
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
                model=_get_default_tool_model(),
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
                model=_get_default_tool_model(),
                temperature=0.3,
                max_tokens=8000
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Crystallize error: {e}")
            return f"AI Error: {e}"
