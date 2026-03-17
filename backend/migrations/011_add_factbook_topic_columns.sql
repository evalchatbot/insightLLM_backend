ALTER TABLE public.factbook_editorials
    ADD COLUMN IF NOT EXISTS topic_domain text NOT NULL DEFAULT 'Other';

ALTER TABLE public.factbook_editorials
    ADD COLUMN IF NOT EXISTS thesis_statement text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_factbook_editorials_topic_domain_date
    ON public.factbook_editorials (topic_domain, publication_date DESC);
