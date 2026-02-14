-- ==============================================================================
-- V7.6 Migration: RPC hybrid_search (story_bible) và hybrid_chunk_search (chunks)
-- Chấp nhận embedding IS NULL: hàng chưa đồng bộ vector vẫn được trả về, gán similarity = 0.5.
-- Chạy sau schema_v7.5_migration.sql. Cần pgvector và story_bible/chunks đã có cột embedding.
-- ==============================================================================
DROP FUNCTION IF EXISTS hybrid_search(text, vector, double precision, integer, uuid);
CREATE EXTENSION IF NOT EXISTS vector;

-- Đảm bảo story_bible có cột embedding (nếu chưa có từ migration trước)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'story_bible' AND column_name = 'embedding') THEN
    ALTER TABLE story_bible ADD COLUMN embedding vector(1536);
  END IF;
END $$;

-- ------------------------------------------------------------------------------
-- 1) hybrid_search: story_bible — vector + text, NULL embedding vẫn trả về (similarity 0.5)
-- ------------------------------------------------------------------------------
-- App gọi: query_text, query_embedding, match_threshold, match_count, story_id_input
CREATE OR REPLACE FUNCTION hybrid_search(
  query_text TEXT,
  query_embedding vector(1536),
  match_threshold FLOAT DEFAULT 0.3,
  match_count INT DEFAULT 30,
  story_id_input UUID DEFAULT NULL
)
RETURNS TABLE (
  id UUID,
  story_id UUID,
  entity_name TEXT,
  description TEXT,
  source_chapter INT,
  parent_id UUID,
  lookup_count INT,
  importance_bias NUMERIC,
  last_lookup_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  embedding vector(1536),
  similarity FLOAT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    b.id,
    b.story_id,
    b.entity_name,
    b.description,
    b.source_chapter,
    b.parent_id,
    b.lookup_count,
    b.importance_bias,
    b.last_lookup_at,
    b.created_at,
    b.updated_at,
    b.embedding,
    (CASE
      WHEN b.embedding IS NOT NULL THEN 1 - (b.embedding <=> query_embedding)
      ELSE 0.5
    END)::FLOAT AS similarity
  FROM story_bible b
  WHERE b.story_id = story_id_input
  AND (
    (b.embedding IS NOT NULL AND (1 - (b.embedding <=> query_embedding) > match_threshold))
    OR (b.embedding IS NULL)
    OR (b.entity_name ILIKE '%' || COALESCE(query_text, '') || '%')
    OR (b.description ILIKE '%' || COALESCE(query_text, '') || '%')
  )
  ORDER BY (CASE WHEN b.embedding IS NOT NULL THEN 1 - (b.embedding <=> query_embedding) ELSE 0.5 END) DESC
  LIMIT match_count;
$$;

COMMENT ON FUNCTION hybrid_search(TEXT, vector(1536), FLOAT, INT, UUID) IS 'V7.6: Bible hybrid search. Rows with NULL embedding are included with similarity 0.5.';

-- ------------------------------------------------------------------------------
-- 2) hybrid_chunk_search: chunks — vector + text, NULL embedding vẫn trả về (rank 0.5)
-- ------------------------------------------------------------------------------
-- App gọi: query_text, query_embedding, story_id_input, match_threshold, match_count
DROP FUNCTION IF EXISTS hybrid_chunk_search(text, vector, uuid, double precision, integer);
CREATE OR REPLACE FUNCTION hybrid_chunk_search(
  query_text TEXT,
  query_embedding vector(1536),
  story_id_input UUID,
  match_threshold FLOAT DEFAULT 0.3,
  match_count INT DEFAULT 10
)
RETURNS SETOF chunks
LANGUAGE sql
STABLE
AS $$
  SELECT c.*
  FROM chunks c
  WHERE c.story_id = story_id_input
  AND (
    (c.embedding IS NOT NULL AND (1 - (c.embedding <=> query_embedding) > match_threshold))
    OR (c.embedding IS NULL)
    OR (c.content ILIKE '%' || COALESCE(query_text, '') || '%')
  )
  ORDER BY CASE WHEN c.embedding IS NOT NULL THEN 1 - (c.embedding <=> query_embedding) ELSE 0.5 END DESC
  LIMIT match_count;
$$;

COMMENT ON FUNCTION hybrid_chunk_search(TEXT, vector(1536), UUID, FLOAT, INT) IS 'V7.6: Chunk hybrid search. Rows with NULL embedding are included and ranked as 0.5.';

-- ------------------------------------------------------------------------------
-- 3) Hướng dẫn
-- ------------------------------------------------------------------------------
-- Dimension embedding = 1536 (đổi vector(1536) nếu dùng model khác, VD: 768 hoặc 4096).
-- Bảng chunks.embedding phải cùng dimension (ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536); nếu cần).
