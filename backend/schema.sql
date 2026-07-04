-- Supabase schema for the Call Intelligence Agent.
-- The project referenced in .env already has this applied. Only needed if you
-- point the app at your own Supabase project.
-- Run in the Supabase SQL Editor (or via the Management API).

create table if not exists public.runs (
  id                  uuid primary key default gen_random_uuid(),
  created_at          timestamptz not null default now(),
  source_type         text not null default 'transcript',   -- 'transcript' | 'audio'
  source_name         text,
  meeting_date        date,
  domain              text,
  domain_rationale    text,
  tag                 text,
  summary             text,
  segment_count       int,
  mock_mode           boolean default false,
  transcript          text,                                  -- transcription (audio) or pasted text
  segments            jsonb,
  result              jsonb not null,                        -- full MeetingIntelligence object
  trace               jsonb,                                 -- per-node agent trace (for observability replay)
  human_review_count  int default 0
);

alter table public.runs enable row level security;

-- Demo policy: open access (anon + service role). Tighten for production.
drop policy if exists "anon_all_runs" on public.runs;
create policy "anon_all_runs" on public.runs for all using (true) with check (true);

-- Custom domain-context registry (built-in domains live in code; these are added at run time).
create table if not exists public.domains (
  key         text primary key,
  agent       text not null,
  description text not null,
  context     text not null default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table public.domains enable row level security;
drop policy if exists "anon_all_domains" on public.domains;
create policy "anon_all_domains" on public.domains for all using (true) with check (true);
