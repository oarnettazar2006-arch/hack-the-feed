-- Ajout du 7/11 : historique des sondages (relevés réguliers) et émergence hors sondages.
-- À coller dans Supabase > SQL Editor > Run.
create table if not exists sondages (
  id bigint generated always as identity primary key,
  institut text not null,
  date date not null,                     -- dernier jour de terrain du sondage
  candidat text not null,                 -- nom tel qu'écrit dans le tableau
  nom text,                               -- nom complet reconnu dans nos listes (null sinon)
  score real not null,                    -- intentions de vote au 1er tour (%)
  hypothese_principale boolean not null default false,
  autres boolean not null default false,  -- pris dans la colonne « Autres »
  premier_releve timestamptz not null default now(),
  dernier_releve timestamptz not null default now(),
  unique (institut, date, candidat)
);
create table if not exists sondages_releves (
  id bigint generated always as identity primary key,
  releve_le timestamptz not null default now(),
  sondages int not null,
  dernier_sondage date,
  source text
);
alter table personnalites add column if not exists teste_depuis date;            -- premier sondage qui le teste
alter table personnalites add column if not exists colonne_propre_depuis date;   -- premier sondage avec une colonne à son nom
alter table personnalites add column if not exists visibilite_comparable text;   -- hors sondages : « aussi visible que X (sondé à Y %) »
do $$ begin
  execute 'alter table sondages enable row level security';
  execute 'alter table sondages_releves enable row level security';
end $$;
drop policy if exists "lecture" on sondages;
create policy "lecture" on sondages for select using (true);
drop policy if exists "lecture" on sondages_releves;
create policy "lecture" on sondages_releves for select using (true);
grant select on sondages, sondages_releves to anon, authenticated;
grant all on sondages, sondages_releves to service_role;
grant usage, select on all sequences in schema public to service_role;
notify pgrst, 'reload schema';
