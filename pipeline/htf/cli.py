"""Point d'entrée : python -m htf.cli <commande>."""
import argparse
import json
from datetime import datetime

from . import analyze, annotate, backtest, config, export, pipeline, showcase, snowball, store
from .sources import fake_social, media, oriane


def show(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(prog="htf")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("media", help="collecter presse et YouTube (gratuit)")
    f = sub.add_parser("fake", help="générer de fausses vidéos sociales (gratuit)")
    f.add_argument("--scale", type=float, default=1.0)
    for name in ("annotate-social", "annotate-media"):
        a = sub.add_parser(name, help="annoter avec Haiku (payant)")
        a.add_argument("--limit", type=int, default=None)
    sub.add_parser("oriane-ping", help="1 appel Oriane : vérifie clé et format (crédits)")
    op = sub.add_parser("oriane-plan", help="nombre d'appels d'une collecte (gratuit)")
    oc = sub.add_parser("oriane-collect", help="collecte sociale Oriane (crédits)")
    for x in (op, oc):
        x.add_argument("--days", type=int, default=17)
        x.add_argument("--per-day", type=int, default=30)
        x.add_argument("--themes", nargs="*", default=None)
    oc.add_argument("--yes", action="store_true", help="lancer sans confirmation")
    sub.add_parser("oriane-find-media", help="trouver les comptes TikTok/Instagram des médias (crédits, ~40 appels)")
    sub.add_parser("oriane-media", help="vidéos des comptes médias via Oriane (crédits)")
    ic = sub.add_parser("oriane-csv", help="importer un export CSV de l'app Oriane (gratuit)")
    ic.add_argument("path")
    sub.add_parser("analyze", help="regrouper, scorer, comparer aux médias (gratuit)")
    sc = sub.add_parser("showcase", help="fiches Opus pour les premiers sujets + brief (payant)")
    sc.add_argument("--top", type=int, default=config.TOP_TOPICS_SHOWCASE)
    sb = sub.add_parser("snowball", help="mesurer le vrai volume des sujets imprévus (Oriane + Haiku)")
    sb.add_argument("--max", type=int, default=3)
    sub.add_parser("export", help="envoyer les résultats dans Supabase (gratuit)")
    ck = sub.add_parser("check", help="tout vérifier avant de commencer (gratuit)")
    ck.add_argument("--oriane", action="store_true", help="tester aussi Oriane (1 appel)")
    rn = sub.add_parser("run", help="chaîne complète : collecte, annotation, analyse, fiches, export")
    rn.add_argument("--days", type=int, default=17)
    rn.add_argument("--per-day", type=int, default=30)
    rn.add_argument("--top", type=int, default=config.TOP_TOPICS_SHOWCASE)
    rn.add_argument("--no-collect", action="store_true", help="repartir des vidéos déjà collectées")
    rn.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    sub.add_parser("backtest-candidates", help="histoires de presse testables pour la preuve sur le passé (gratuit)")
    bt = sub.add_parser("backtest", help="mesurer l'avance des réseaux sur la presse (Oriane, ~15 appels)")
    bt.add_argument("story", help="l'histoire, en une phrase")
    bt.add_argument("press_day", help="date du premier article, AAAA-MM-JJ")
    sub.add_parser("purge-fake", help="supprimer les fausses vidéos de test")
    sub.add_parser("cost", help="dépenses enregistrées")
    dc = sub.add_parser("oriane-decollage", help="filet décollage : vidéos FR à ≥3× l'audience du créateur (crédits)")
    dc.add_argument("--days", type=int, default=17)
    sub.add_parser("oriane-volumes", help="volumes réels par personnalité, agrégations Oriane (crédits)")
    sub.add_parser("controle-echantillon", help="grille de 30 vidéos à annoter à la main (gratuit)")
    cc = sub.add_parser("controle-comparer", help="comparer la grille remplie à Haiku (gratuit)")
    cc.add_argument("fichier")
    sub.add_parser("visuels", help="graphiques PNG dans docs/visuels (gratuit)")
    po = sub.add_parser("polls", help="relever les sondages présidentielle 2027 sur Wikipédia (gratuit)")
    po.add_argument("--export", action="store_true", help="envoyer l'historique dans Supabase")
    hi = sub.add_parser("polls-history", help="vidéos par jour citant une personnalité (Oriane, 10 crédits par jour)")
    hi.add_argument("nom")
    hi.add_argument("termes", nargs="+")
    hi.add_argument("--debut", default="2026-09-01")
    hi.add_argument("--fin", default=None)
    args = p.parse_args()

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.cmd == "media":
        show(media.collect())
    elif args.cmd == "fake":
        show({"nouvelles vidéos": fake_social.generate(scale=args.scale)})
    elif args.cmd == "annotate-social":
        show(annotate.annotate_social(run_id, args.limit))
    elif args.cmd == "annotate-media":
        show(annotate.annotate_media(run_id, args.limit))
    elif args.cmd == "oriane-ping":
        show(oriane.ping())
    elif args.cmd == "oriane-plan":
        show(oriane.plan(args.days, args.per_day, args.themes))
    elif args.cmd == "oriane-collect":
        show(oriane.plan(args.days, args.per_day, args.themes, media=False))
        if args.yes or input("Lancer cette collecte ? (oui/non) ").strip().lower() in ("o", "oui", "y", "yes"):
            show(oriane.collect_social(args.days, args.per_day, args.themes))
    elif args.cmd == "oriane-find-media":
        show(oriane.find_media_profiles())
    elif args.cmd == "oriane-media":
        show(oriane.collect_media())
    elif args.cmd == "oriane-csv":
        show(oriane.import_csv(args.path))
    elif args.cmd == "analyze":
        topics = analyze.run()
        config.OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Les fiches et le brief dépendent des regroupements : une nouvelle analyse les rend caducs.
        (config.OUT_DIR / "brief.json").unlink(missing_ok=True)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=2))
        persons = analyze.people()
        (config.OUT_DIR / "people.json").write_text(json.dumps(persons, ensure_ascii=False, indent=2))
        show([{k: p[k] for k in ("nom", "hors_liste", "videos_total", "acceleration", "createurs_recents")} for p in persons[:10]])
        show([{k: t[k] for k in ("rang", "etat", "sujet_type", "videos_total", "videos_recentes", "signaux", "couvert")}
              for t in topics])
    elif args.cmd == "showcase":
        topics = json.loads((config.OUT_DIR / "topics.json").read_text())
        cards = showcase.build_cards(run_id, topics, args.top)
        brief = showcase.morning_brief(cards)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2))
        (config.OUT_DIR / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        show({"fiches": args.top, "brief": brief, "dépense ($)": round(store.spent(run_id), 4)})
    elif args.cmd == "snowball":
        topics = json.loads((config.OUT_DIR / "topics.json").read_text())
        show(snowball.measure(run_id, topics, args.max))
        (config.OUT_DIR / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=2))
    elif args.cmd == "export":
        show(export.run())
    elif args.cmd == "check":
        show(pipeline.check(args.oriane))
    elif args.cmd == "run":
        ask = (lambda q: True) if args.yes else (lambda q: input(q + " (oui/non) ").strip().lower() in ("o", "oui", "y", "yes"))
        show(pipeline.run(run_id, args.days, args.per_day, args.top, not args.no_collect, ask))
    elif args.cmd == "backtest-candidates":
        show(backtest.candidates())
    elif args.cmd == "backtest":
        show(backtest.measure(run_id, args.story, args.press_day))
    elif args.cmd == "purge-fake":
        show({"fausses vidéos supprimées": store.purge_fake()})
    elif args.cmd == "polls":
        from . import polls
        show(polls.collect())
        if args.export:
            show(polls.export())
    elif args.cmd == "polls-history":
        from datetime import date as _date
        from . import analyze as _an, polls
        end = _date.fromisoformat(args.fin) if args.fin else (_an._last_complete_day() or datetime.now()).date()
        h = polls.oriane_history(args.nom, args.termes, _date.fromisoformat(args.debut), end)
        show({"jours": len(h), "vidéos": sum(x["videos"] for x in h)})
    elif args.cmd == "visuels":
        from . import visuels
        show(visuels.run())
    elif args.cmd == "controle-echantillon":
        from . import controle
        show(controle.sample())
    elif args.cmd == "controle-comparer":
        from . import controle
        show(controle.compare(args.fichier))
    elif args.cmd == "oriane-decollage":
        show(oriane.collect_breakout(args.days))
    elif args.cmd == "oriane-volumes":
        from . import analyze as _an, politics
        end = (_an._last_complete_day() or datetime.now()).date()
        show(oriane.people_volumes(list(politics.AFFILIATIONS), end, config.WINDOW_RECENT, config.WINDOW_BASELINE))
    elif args.cmd == "cost":
        show({"total ($)": round(store.spent(), 4), "détail": store.cost_report()})


if __name__ == "__main__":
    main()
