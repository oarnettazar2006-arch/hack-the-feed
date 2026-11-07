-- Ajout du 7/11 : signaux faibles (sujets neufs, trop petits pour le radar). À coller dans Supabase > SQL Editor > Run.
alter table topics add column if not exists signal_faible boolean not null default false;
alter table topics add column if not exists vu_jusqu_au date;   -- dernier jour de vidéos lu pour ce sujet
notify pgrst, 'reload schema';
