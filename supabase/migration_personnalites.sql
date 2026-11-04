-- Ajout du 4/11 : personnalités émergentes. À coller dans Supabase > SQL Editor > Run.
create table if not exists personnalites (
  id bigint generated always as identity primary key,
  run_at timestamptz not null default now(),
  rang int not null,
  nom text not null,
  hors_liste boolean not null,        -- absente de nos listes de candidats et personnalités : repérée seule
  videos_total int not null,
  videos_recentes int not null,
  acceleration real not null,
  createurs_recents int not null,
  score real not null,
  tons jsonb not null default '{}',
  affirmations text[] not null default '{}'
);
alter table personnalites enable row level security;
drop policy if exists "lecture" on personnalites;
create policy "lecture" on personnalites for select using (true);
grant select on personnalites to anon, authenticated;
grant all on personnalites to service_role;
grant usage, select on all sequences in schema public to service_role;
