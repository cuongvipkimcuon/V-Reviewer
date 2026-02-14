-- ==============================================================================
-- V7 Migration: timeline_events (Manage Timeline intent)
-- Chạy sau schema_v6.6_migration.sql
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- TABLE: timeline_events (sự kiện theo thời gian, flashback, mốc thời gian)
-- Dùng cho intent manage_timeline: truy vấn thứ tự sự kiện, kiểm tra nhất quán thời gian
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timeline_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  arc_id UUID REFERENCES arcs(id) ON DELETE SET NULL,
  chapter_id BIGINT REFERENCES chapters(id) ON DELETE SET NULL,
  event_order INT NOT NULL DEFAULT 0,
  title TEXT NOT NULL DEFAULT '',
  description TEXT DEFAULT '',
  raw_date TEXT DEFAULT '',
  event_type TEXT DEFAULT 'event' CHECK (event_type IN ('event', 'flashback', 'milestone', 'timeskip', 'other')),
  meta_json JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_events_story_id ON timeline_events(story_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_arc_id ON timeline_events(arc_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_story_order ON timeline_events(story_id, event_order);
CREATE INDEX IF NOT EXISTS idx_timeline_events_chapter_id ON timeline_events(chapter_id);

COMMENT ON TABLE timeline_events IS 'V7: Sự kiện timeline cho intent manage_timeline (thứ tự, flashback, mốc thời gian)';
