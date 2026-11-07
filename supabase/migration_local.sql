-- Ajout du 7/11 : veille locale (Sud-Ouest) et comptes éclaireurs. À coller dans Supabase > SQL Editor > Run.
alter table topics add column if not exists regions jsonb not null default '{}';            -- région -> nb de vidéos rattachées
alter table topics add column if not exists foyer text;                                     -- région où le sujet est né (null si aucune)
alter table topics add column if not exists local_vers_national boolean not null default false; -- né localement puis diffusé ailleurs / repris au national
create table if not exists comptes_eclaireurs (
  id bigint generated always as identity primary key,
  rang int not null,
  compte text not null,
  plateforme text,
  abonnes int,
  url text,
  region text,                         -- région rattachée (ex. Sud-Ouest), null si inconnue
  nb_sujets int not null,              -- sujets sur lesquels le compte a publié dans le premier quart
  avance_moyenne_jours real,           -- avance moyenne sur la date médiane des vidéos du sujet
  sujets text[] not null default '{}',
  exemple_url text,
  type text,                           -- créateur, média ou élu (d'après la bio), null si bio inconnue
  bio text
);
alter table comptes_eclaireurs add column if not exists type text;
alter table comptes_eclaireurs add column if not exists bio text;
alter table comptes_eclaireurs enable row level security;
drop policy if exists "lecture" on comptes_eclaireurs;
create policy "lecture" on comptes_eclaireurs for select using (true);
grant select on comptes_eclaireurs to anon, authenticated;
grant all on comptes_eclaireurs to service_role;
grant usage, select on all sequences in schema public to service_role;
notify pgrst, 'reload schema';
