"""Point d'entrée : python -m htf.cli <commande>."""
import argparse
import json
from datetime import datetime

from . import analyze, annotate, config, showcase, store
from .sources import fake_social, media


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
    sub.add_parser("analyze", help="regrouper, scorer, comparer aux médias (gratuit)")
    sc = sub.add_parser("showcase", help="fiches Opus pour les premiers sujets + brief (payant)")
    sc.add_argument("--top", type=int, default=config.TOP_TOPICS_SHOWCASE)
    sub.add_parser("cost", help="dépenses enregistrées")
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
    elif args.cmd == "analyze":
        topics = analyze.run()
        config.OUT_DIR.mkdir(parents=True, exist_ok=True)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=2))
        show([{k: t[k] for k in ("rang", "etat", "sujet_type", "videos_total", "videos_recentes", "signaux", "couvert")}
              for t in topics])
    elif args.cmd == "showcase":
        topics = json.loads((config.OUT_DIR / "topics.json").read_text())
        cards = showcase.build_cards(run_id, topics, args.top)
        brief = showcase.morning_brief(cards)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2))
        (config.OUT_DIR / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        show({"fiches": args.top, "brief": brief, "dépense ($)": round(store.spent(run_id), 4)})
    elif args.cmd == "cost":
        show({"total ($)": round(store.spent(), 4), "détail": store.cost_report()})


if __name__ == "__main__":
    main()
