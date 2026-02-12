-- ==============================================================================
-- V6.5 Migration: Chunk Embeddings, Chat Crystallize Log, Chunking Source Types
-- Chạy sau schema_v6_migration.sql. Cần bật pgvector extension trong Supabase.
-- ==============================================================================

-- 0) Bật pgvector nếu chưa có (Supabase thường đã có sẵn)
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------------------------
-- 1) CHUNKS: Thêm cột embedding cho vector hóa (dimension phụ thuộc embedding model, VD: 4096 cho qwen3-embedding)
-- ------------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chunks' AND column_name = 'embedding') THEN
    ALTER TABLE chunks ADD COLUMN embedding vector(4096);  -- Điều chỉnh 4096 nếu model dùng dimension khác
  END IF;
END $$;

-- Index cho similarity search chunks (uncomment khi đã có dữ liệu embedding)
-- CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Thêm source_type để phân biệt Excel (by_row) vs Word (semantic)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chunks' AND column_name = 'source_type') THEN
    ALTER TABLE chunks ADD COLUMN source_type TEXT DEFAULT 'chapter' CHECK (source_type IN ('chapter', 'excel_row', 'word_semantic', 'other'));
  END IF;
END $$;

-- ------------------------------------------------------------------------------
-- 2) BẢNG: chat_crystallize_log (ghi nhận các lần auto-crystallize)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_crystallize_log (
  id BIGSERIAL PRIMARY KEY,
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  crystallize_date DATE NOT NULL DEFAULT CURRENT_DATE,
  serial_in_day INT NOT NULL DEFAULT 1,
  message_count INT NOT NULL,
  bible_entry_id BIGINT,  -- FK tới story_bible nếu lưu được
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_crystallize_log_story ON chat_crystallize_log(story_id);
CREATE INDEX IF NOT EXISTS idx_chat_crystallize_log_date ON chat_crystallize_log(crystallize_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_crystallize_serial 
  ON chat_crystallize_log(story_id, user_id, crystallize_date, serial_in_day);

-- ------------------------------------------------------------------------------
-- 3) RPC: hybrid_chunk_search (vector + text, giống hybrid_search cho story_bible)
-- ------------------------------------------------------------------------------
-- Chạy sau khi đã có cột embedding và dữ liệu. Tham khảo hybrid_search của story_bible.
-- CREATE OR REPLACE FUNCTION hybrid_chunk_search(
--   query_text TEXT,
--   query_embedding vector(4096),
--   story_id_input UUID,
--   match_threshold FLOAT DEFAULT 0.3,
--   match_count INT DEFAULT 10
-- ) RETURNS SETOF chunks AS $$
--   SELECT * FROM chunks
--   WHERE story_id = story_id_input
--   AND (embedding IS NULL OR 1 - (embedding <=> query_embedding) > match_threshold)
--   OR content ILIKE '%' || query_text || '%'
--   ORDER BY CASE WHEN embedding IS NOT NULL THEN 1 - (embedding <=> query_embedding) ELSE 0.5 END DESC
--   LIMIT match_count;
-- $$ LANGUAGE sql STABLE;

-- ------------------------------------------------------------------------------
-- 4) HƯỚNG DẪN ĐIỀU CHỈNH TRONG Supabase SQL Editor
-- ------------------------------------------------------------------------------
-- - Nếu embedding dimension khác 4096 (VD: 768, 1536, 3072): 
--   ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(DIMENSION_CUA_BAN);
-- - Nếu dùng model embedding khác, kiểm tra config.EMBEDDING_MODEL và dimension tương ứng
-- - Sau khi có dữ liệu chunks.embedding, chạy:
--   CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
