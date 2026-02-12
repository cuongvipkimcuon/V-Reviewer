-- ==============================================================================
-- V6 Migration: AI-ERP Operating System
-- Arc Architecture, Chunks, Validation Logs. Run after schema_v5_migration.sql.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1) TABLE: arcs (Timeline & Context Partitioning)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS arcs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'STANDALONE' CHECK (type IN ('SEQUENTIAL', 'STANDALONE')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'draft')),
  summary TEXT DEFAULT '',
  parent_arc_id UUID REFERENCES arcs(id) ON DELETE SET NULL,
  prev_arc_id UUID REFERENCES arcs(id) ON DELETE SET NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arcs_story_id ON arcs(story_id);
CREATE INDEX IF NOT EXISTS idx_arcs_prev_arc_id ON arcs(prev_arc_id);
CREATE INDEX IF NOT EXISTS idx_arcs_parent_arc_id ON arcs(parent_arc_id);
CREATE INDEX IF NOT EXISTS idx_arcs_story_sort ON arcs(story_id, sort_order);

-- ------------------------------------------------------------------------------
-- 2) CHAPTERS: add arc_id (nullable for backward compatibility)
-- ------------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'arc_id') THEN
    ALTER TABLE chapters ADD COLUMN arc_id UUID REFERENCES arcs(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_chapters_arc_id ON chapters(arc_id);

-- ------------------------------------------------------------------------------
-- 3) TABLE: chunks (Row-level content with reverse traceability)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  arc_id UUID REFERENCES arcs(id) ON DELETE CASCADE,
  chapter_id BIGINT REFERENCES chapters(id) ON DELETE SET NULL,
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  raw_content TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  meta_json JSONB DEFAULT '{}',
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_story_id ON chunks(story_id);
CREATE INDEX IF NOT EXISTS idx_chunks_arc_id ON chunks(arc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chapter_id ON chunks(chapter_id);

-- Optional: pgvector index for similarity search (uncomment if using pgvector)
-- CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ------------------------------------------------------------------------------
-- 4) TABLE: validation_logs (Active Sentry - Conflict Detection)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS validation_logs (
  id BIGSERIAL PRIMARY KEY,
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  arc_id UUID REFERENCES arcs(id) ON DELETE SET NULL,
  log_type TEXT NOT NULL CHECK (log_type IN ('bible_integrity', 'cross_sheet', 'schema_mismatch', 'other')),
  message TEXT NOT NULL,
  details JSONB DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved_force_sync', 'resolved_keep_exception')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_logs_story_id ON validation_logs(story_id);
CREATE INDEX IF NOT EXISTS idx_validation_logs_status ON validation_logs(story_id, status);
CREATE INDEX IF NOT EXISTS idx_validation_logs_arc_id ON validation_logs(arc_id);

-- ------------------------------------------------------------------------------
-- 5) ARC RELATIONS (for timeline / hierarchy tracking)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS arc_relations (
  id BIGSERIAL PRIMARY KEY,
  arc_id UUID NOT NULL REFERENCES arcs(id) ON DELETE CASCADE,
  related_arc_id UUID NOT NULL REFERENCES arcs(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL DEFAULT 'follows',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(arc_id, related_arc_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_arc_relations_arc_id ON arc_relations(arc_id);
CREATE INDEX IF NOT EXISTS idx_arc_relations_related ON arc_relations(related_arc_id);
