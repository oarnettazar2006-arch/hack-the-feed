-- Ajout du 7/11 : filtre politique et comparaison des personnalités. À coller dans Supabase > SQL Editor > Run.
alter table topics add column if not exists campagne boolean not null default false;   -- sujet de la campagne 2027
alter table topics add column if not exists personnalites text[] not null default '{}'; -- personnalités de la campagne citées
alter table topics add column if not exists camps jsonb not null default '{}';         -- camp politique -> nb de personnalités

alter table personnalites add column if not exists parti text;
alter table personnalites add column if not exists camp text;              -- extrême gauche … extrême droite, divers, international, null = non classée
alter table personnalites add column if not exists tendance text;          -- monte / stable / baisse
alter table personnalites add column if not exists solde real;             -- (favorable - critique - ironique) / vidéos, de -1 à +1
alter table personnalites add column if not exists surperformance real;    -- médiane vues / abonnés des vidéos récentes
alter table personnalites add column if not exists taux_engagement real;   -- interactions / vues des vidéos récentes
alter table personnalites add column if not exists part_de_voix real;      -- part des vues récentes parmi les personnalités françaises
alter table personnalites add column if not exists serie jsonb not null default '[]';
alter table personnalites add column if not exists video_phare text;
alter table personnalites add column if not exists video_phare_url text;
alter table personnalites add column if not exists video_phare_compte text;
alter table personnalites add column if not exists video_phare_traitement text;
alter table personnalites add column if not exists reactions jsonb not null default '{}';
alter table personnalites add column if not exists vues bigint;
alter table personnalites add column if not exists interactions bigint;
notify pgrst, 'reload schema';
