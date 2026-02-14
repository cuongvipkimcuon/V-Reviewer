-- ==============================================================================
-- V7.1 Migration: crystallize message counter (tránh trùng, hiển thị X/30)
-- Chạy sau schema_v7_migration.sql
-- ==============================================================================

-- Bảng lưu số tin nhắn kể từ lần crystallize gần nhất (per project + user).
-- Sau mỗi lần crystallize: reset về 0. Hiển thị "X / 30" trong V Work.
CREATE TABLE IF NOT EXISTS chat_crystallize_state (
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  messages_since_crystallize INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (story_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_crystallize_state_story_user ON chat_crystallize_state(story_id, user_id);
COMMENT ON TABLE chat_crystallize_state IS 'V7.1: Số tin nhắn từ lần crystallize gần nhất (reset về 0 khi crystallize)';

-- ------------------------------------------------------------------------------
-- V Home: chat tự do, không lưu vào chat_history. Mỗi user có topic (reset topic = topic mới).
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v_home_current_topic (
  user_id TEXT PRIMARY KEY,
  topic_start_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE v_home_current_topic IS 'V7.1: Thời điểm bắt đầu topic hiện tại (Reset topic = cập nhật topic_start_at)';

CREATE TABLE IF NOT EXISTS v_home_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'model')),
  content TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  topic_start_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v_home_messages_user_topic ON v_home_messages(user_id, topic_start_at);
CREATE INDEX IF NOT EXISTS idx_v_home_messages_created ON v_home_messages(created_at);
COMMENT ON TABLE v_home_messages IS 'V7.1: Tin nhắn V Home (theo topic; context = 10 tin cuối của topic hiện tại)';
