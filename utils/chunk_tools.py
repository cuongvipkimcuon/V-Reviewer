# utils/chunk_tools.py - Công cụ chunk (tách văn bản / Excel theo dòng) dùng chung cho Workstation và Chunking
"""Logic chunk: tách theo ngữ nghĩa (như Workstation) và Excel theo dòng. Dùng lại từ Workstation."""
from typing import List, Dict, Any, Optional, Tuple

# Re-export và wrapper cho workflow chunk thống nhất


def split_text_to_chunks(
    text: str,
    file_type: str = "story",
    context_hint: str = "",
) -> List[Dict[str, Any]]:
    """
    Tách văn bản thành các chunk (cùng logic Workstation).
    Dùng analyze_split_strategy + execute_split_logic từ ai_engine.
    Returns: list of {"title": str, "content": str, "order": int}.
    """
    if not text or not str(text).strip():
        return []
    from ai_engine import analyze_split_strategy, execute_split_logic
    strategy = analyze_split_strategy(text, file_type=file_type, context_hint=context_hint)
    chunks = execute_split_logic(
        text,
        strategy.get("split_type", "by_length"),
        strategy.get("split_value", "2000"),
    )
    if not chunks and text.strip():
        chunks = execute_split_logic(text, "by_length", "2000")
    return chunks


def split_text_by_length_with_overlap(
    text: str,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> List[Dict[str, Any]]:
    """
    Fallback: cắt theo độ dài có overlap (ngữ cảnh đoạn trước).
    Returns: list of {"title": str, "content": str, "order": int}.
    """
    if not text or not text.strip():
        return []
    parts = []
    start = 0
    idx = 1
    while start < len(text):
        end = min(start + chunk_size, len(text))
        part = text[start:end]
        ctx_start = max(0, start - overlap)
        context_prefix = text[ctx_start:start] if ctx_start < start else ""
        full_content = (context_prefix + "\n\n[---]\n\n" + part).strip() if context_prefix else part.strip()
        if full_content:
            parts.append({"title": f"Đoạn {idx}", "content": full_content, "order": idx})
            idx += 1
        start = end - overlap if end < len(text) else len(text)
    return parts


def load_excel_as_chunks(file) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Excel theo dòng: mỗi dòng = 1 chunk (metadata sheet_name, row_index, source_file).
    Returns (list of {raw_content, content, meta_json}, error_message).
    """
    from utils.file_importer import UniversalLoader
    return UniversalLoader.load_excel_as_chunks(file)


def load_docx_text(file) -> Tuple[str, Optional[str]]:
    """Đọc file Word thành text (để sau đó dùng split_text_to_chunks)."""
    from utils.file_importer import UniversalLoader
    return UniversalLoader.load(file)
