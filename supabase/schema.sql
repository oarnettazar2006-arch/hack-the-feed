-- Schéma lu par l'interface. Le pipeline Python remplace le contenu à chaque exécution.
-- À coller une fois dans Supabase > SQL Editor > New query > Run.

create table if not exists topics (
  id text primary key,
  run_at timestamptz not null default now(),
  rang int not null,
  etat text not null,                -- à traiter maintenant, course de vitesse, à surveiller, angle mort durable, stable, en baisse
  titre text,
  sujet_type text not null,
  politique boolean not null,
  themes text[] not null default '{}',
  videos_total int not null,
  videos_recentes int not null,
  acceleration real not null,
  createurs_recents int not null,
  surperformance real not null,
  engagement real not null,
  score real not null,
  tons jsonb not null default '{}',
  pourquoi_ca_monte text,
  angle_brut text,
  prudence text,
  couvert boolean not null,
  couvert_par_brut boolean not null,
  serie jsonb not null default '[]',  -- [{jour, videos}] pour la mini-courbe
  video_declencheur text,
  imprevu boolean not null default false  -- trouvé uniquement par le filet aveugle
);

create table if not exists topic_positions (
  id bigint generated always as identity primary key,
  topic_id text not null references topics(id) on delete cascade,
  ordre int not null,
  libelle text not null,
  resume text not null,
  nb_videos int not null,
  vues bigint not null,
  partages bigint not null
);

create table if not exists topic_coverage (
  id bigint generated always as identity primary key,
  topic_id text not null references topics(id) on delete cascade,
  media text not null,
  groupe text,
  titre text not null,
  url text,
  date timestamptz,
  similarite real not null
);

create table if not exists videos (
  id text primary key,
  topic_id text not null references topics(id) on delete cascade,
  position text,                     -- libellé de la position, si la vidéo en porte une
  account text,
  platform text,
  published_at timestamptz not null,
  url text,
  contenu text not null,             -- paroles, texte à l'écran, image, légende
  sujet text,
  ton text,
  affirmation text,
  views bigint, likes bigint, shares bigint, comments bigint, followers bigint,
  est_declencheur boolean not null default false,
  est_phare boolean not null default false
);

create table if not exists brief (
  id bigint generated always as identity primary key,
  run_at timestamptz not null default now(),
  ordre int not null,
  topic_id text not null references topics(id) on delete cascade,
  titre text not null,
  etat text not null,
  pourquoi text,
  angle text,
  deja_traite_par text[] not null default '{}',
  valide boolean not null default false
);

create index if not exists videos_topic_idx on videos(topic_id);
create index if not exists positions_topic_idx on topic_positions(topic_id);
create index if not exists coverage_topic_idx on topic_coverage(topic_id);

-- Droits explicites (le projet n'expose pas automatiquement les nouvelles tables).
grant usage on schema public to anon, authenticated, service_role;
grant select on topics, topic_positions, topic_coverage, videos, brief to anon, authenticated;
grant all on topics, topic_positions, topic_coverage, videos, brief to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Lecture publique (données non sensibles), écriture réservée au pipeline (clé service_role).
alter table topics enable row level security;
alter table topic_positions enable row level security;
alter table topic_coverage enable row level security;
alter table videos enable row level security;
alter table brief enable row level security;

drop policy if exists "lecture" on topics;           create policy "lecture" on topics for select using (true);
drop policy if exists "lecture" on topic_positions;  create policy "lecture" on topic_positions for select using (true);
drop policy if exists "lecture" on topic_coverage;   create policy "lecture" on topic_coverage for select using (true);
drop policy if exists "lecture" on videos;           create policy "lecture" on videos for select using (true);
drop policy if exists "lecture" on brief;            create policy "lecture" on brief for select using (true);

-- Le bouton « valider » du brief : l'interface peut modifier uniquement la colonne valide.
drop policy if exists "validation" on brief;
create policy "validation" on brief for update using (true) with check (true);
revoke update on brief from anon, authenticated;
grant update (valide) on brief to anon, authenticated;

-- Personnalités émergentes (ajout du 4/11, voir aussi migration_personnalites.sql)
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
