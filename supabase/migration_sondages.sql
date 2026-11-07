-- Ajout du 7/11 : sondages et surexposition. À coller dans Supabase > SQL Editor > Run.
alter table personnalites add column if not exists sondage real;               -- moyenne des sondages des 21 derniers jours (%)
alter table personnalites add column if not exists sondage_detail text;        -- « moyenne de N sondage(s), dernier Ifop du … »
alter table personnalites add column if not exists mentions_presse int;        -- titres de presse et de vidéos de médias qui le citent
alter table personnalites add column if not exists surexposition_videos real;  -- part de vues ÷ part dans les sondages (>1 : plus visible qu'il ne pèse)
alter table personnalites add column if not exists surexposition_presse real;  -- part de mentions presse ÷ part dans les sondages
alter table personnalites add column if not exists sondages_serie jsonb;       -- liste de {date, institut, score}
alter table personnalites add column if not exists historique_videos jsonb;    -- liste de {jour, videos} sur 2 mois (Oriane), si mesurée
notify pgrst, 'reload schema';
