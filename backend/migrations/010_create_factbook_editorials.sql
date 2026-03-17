CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.factbook_editorials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_date date NOT NULL,
    headline text NOT NULL,
    summary_bullets jsonb NOT NULL DEFAULT '[]'::jsonb,
    takeaway text NOT NULL DEFAULT '',
    summary_paragraph text NOT NULL DEFAULT '',
    source_url text NOT NULL,
    source_hash text NOT NULL,
    source_name text NOT NULL DEFAULT 'dawn',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_factbook_editorials_source_hash
    ON public.factbook_editorials (source_hash);

CREATE UNIQUE INDEX IF NOT EXISTS idx_factbook_editorials_date_headline
    ON public.factbook_editorials (publication_date, headline);

CREATE INDEX IF NOT EXISTS idx_factbook_editorials_publication_date
    ON public.factbook_editorials (publication_date DESC);
