-- 5/11 : preuve dans la vidéo (paroles, texte à l'écran), vidéo pivot, format proposé, traitement des personnalités.
alter table topics add column if not exists format_brut text;
alter table topics add column if not exists declencheur_avant integer;
alter table topics add column if not exists declencheur_apres integer;
alter table topics add column if not exists part_hors_legende real;
alter table topics add column if not exists videos_lues integer;
alter table topics add column if not exists canaux jsonb;
alter table topics add column if not exists reactions jsonb;
alter table topics add column if not exists citations jsonb;

alter table videos add column if not exists canal text;
alter table videos add column if not exists legende_suffit boolean;
alter table videos add column if not exists citation text;
alter table videos add column if not exists reaction_public text;
alter table videos add column if not exists miniature text;

alter table brief add column if not exists format text;

alter table personnalites add column if not exists reactions jsonb;
alter table personnalites add column if not exists vues bigint;
alter table personnalites add column if not exists interactions bigint;

notify pgrst, 'reload schema';
