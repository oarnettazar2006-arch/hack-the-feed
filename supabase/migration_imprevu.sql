-- Ajout du 4/11 (2) : sujets imprévus, trouvés uniquement par le filet aveugle.
alter table topics add column if not exists imprevu boolean not null default false;
notify pgrst, 'reload schema';
