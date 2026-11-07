-- Ajout du 7/11 : X (Twitter) via Apify, croisé avec les sujets. À coller dans Supabase > SQL Editor > Run.
alter table topics add column if not exists x_tweets int not null default 0;             -- tweets rapprochés du sujet
alter table topics add column if not exists x_premier timestamptz;                       -- premier tweet rapproché
alter table topics add column if not exists x_avant_videos boolean not null default false; -- le sujet circulait sur X avant la 1re vidéo lue
alter table topics add column if not exists x_exemples jsonb not null default '[]';      -- 5 tweets : compte, abonnés, date, texte, url, likes
notify pgrst, 'reload schema';
