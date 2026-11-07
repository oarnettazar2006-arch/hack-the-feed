-- Ajout du 7/11 : filet décollage et volumes réels. À coller dans Supabase > SQL Editor > Run.
alter table topics add column if not exists videos_decollage int not null default 0;     -- vidéos récentes à ≥ 3× l'audience du créateur
alter table personnalites add column if not exists volume_reel jsonb;                    -- tout l'index Oriane : vidéos, vues, interactions (récent / référence)
alter table personnalites add column if not exists acceleration_reelle real;             -- accélération calculée sur le volume réel
alter table personnalites add column if not exists surexposition_source text;            -- « vues réelles (index Oriane) » ou « vues de l'échantillon lu »
notify pgrst, 'reload schema';
