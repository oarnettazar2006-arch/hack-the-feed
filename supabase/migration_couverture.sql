-- Ajout du 4/11 (3) : depuis quand la couverture médias est connue (garde-fou de l'angle mort).
alter table topics add column if not exists couverture_presse_depuis date;
alter table topics add column if not exists couverture_concurrents_depuis date;
alter table topics add column if not exists couverture_complete boolean not null default false;
notify pgrst, 'reload schema';
