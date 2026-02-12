-- ==============================================================================
-- V6.6 Migration: Semantic Intent, Prefix-Persona, Project simplification
-- Chạy sau schema_v6.5_migration.sql
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1) BẢNG: semantic_intent (mẫu câu hỏi + intent + data liên quan, vector hóa)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS semantic_intent (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  question_sample TEXT NOT NULL,
  intent TEXT NOT NULL,
  related_data TEXT,
  embedding vector(4096),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_intent_story ON semantic_intent(story_id);
-- CREATE INDEX IF NOT EXISTS idx_semantic_intent_embedding ON semantic_intent USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ------------------------------------------------------------------------------
-- 2) bible_prefix_config: Thêm cột persona_key (gắn prefix với persona, null = RULE/CHAT/OTHER)
-- ------------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'bible_prefix_config' AND column_name = 'persona_key') THEN
    ALTER TABLE bible_prefix_config ADD COLUMN persona_key TEXT;
  END IF;
END $$;

-- ------------------------------------------------------------------------------
-- 3) Bảng settings: lưu semantic_intent_threshold (70-99, mặc định 85)
-- ------------------------------------------------------------------------------
-- Chạy trong app hoặc thủ công: INSERT INTO settings (key, value) VALUES ('semantic_intent_threshold', 85) ON CONFLICT (key) DO UPDATE SET value = 85;

-- ------------------------------------------------------------------------------
-- 4) HƯỚNG DẪN
-- ------------------------------------------------------------------------------
-- - stories: Bỏ hiển thị/chọn category khi tạo project (persona tùy chỉnh rồi)
-- - chapters: arc_id đã có từ schema_v6
-- - Nếu embedding dimension khác 4096, sửa semantic_intent.embedding
