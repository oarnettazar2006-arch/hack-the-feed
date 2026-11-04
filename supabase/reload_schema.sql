-- Recharge le cache des colonnes de l'API Supabase (à lancer après chaque modification du schéma).
notify pgrst, 'reload schema';
