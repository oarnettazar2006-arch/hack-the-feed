"""Tests sans réseau ni dépense : python -m pytest pipeline/tests -q (depuis la racine du repo)."""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from htf import config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")


def fake_oriane(monkeypatch, handler):
    from htf.sources import oriane
    orig = oriane.Oriane.__init__

    def patched(self, api_key=None):
        orig(self, "cle-test")
        self.http = httpx.Client(base_url=oriane.BASE_URL, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(oriane.Oriane, "__init__", patched)
    return oriane


def test_authentification_bearer_puis_repli(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(200, json={"data": {"results": []}, "metadata": {"pagination": {"totalCount": 3}}})

    oriane = fake_oriane(monkeypatch, handler)
    _, total = oriane.Oriane().search({}, limit=1)
    assert total == 3 and seen == ["Bearer cle-test"]


def test_retard_indexation_corrige_et_filet_aveugle(monkeypatch):
    today = date.today()
    comp = lambda day: {0: 0.05, 1: 0.15, 2: 0.4}.get((today - date.fromisoformat(day)).days, 1.0)
    true = lambda day: 400 if (today - date.fromisoformat(day)).days > 5 else 400 * (6 - (today - date.fromisoformat(day)).days)

    def vid(i, day):
        return {"id": i, "platform": "tiktok", "profileHandle": "c", "publishedAt": f"{day}T10:00:00Z", "media": []}

    def handler(req):
        body = json.loads(req.content)
        day = body["filters"]["publishedAt"]["after"]
        names = [q.get("name") for q in body.get("queries", [])]
        limit = int(req.url.params["limit"])
        if names == ["fr"] and limit == 1:
            return httpx.Response(200, json={"data": {"results": []}, "metadata": {"pagination": {"totalCount": int(1e5 * comp(day))}}})
        if names == ["fr"]:
            res = [vid(f"b_{day}_{i}", day) for i in range(3)] + [vid(f"t_{day}_0", day)]
            return httpx.Response(200, json={"data": {"results": res}, "metadata": {"pagination": {"totalCount": 99999}}})
        total = int(true(day) * comp(day))
        res = [vid(f"t_{day}_{i}", day) for i in range(min(limit, total))]
        return httpx.Response(200, json={"data": {"results": res}, "metadata": {"pagination": {"totalCount": total}}})

    oriane = fake_oriane(monkeypatch, handler)
    from htf import store
    oriane.collect_social(days=17, per_day=10, themes=["logement", oriane.BLIND_NET])
    volume = defaultdict(float)
    for it in store.load_items("social"):
        if it["metrics"]["theme_query"] == "logement":
            volume[it["published_at"][:10]] += it["metrics"]["weight"]
    assert all(round(v) == true(d) for d, v in volume.items())
    # Une vidéo vue par le thème puis par le filet aveugle garde le poids du thème.
    shared = [it for it in store.load_items("social") if it["id"].endswith("_0") and ":t_" in it["id"]]
    assert shared and all(it["metrics"]["weight"] > 1 for it in shared)


def test_vues_instagram_estimees():
    from htf.analyze import _engagement_rates, _views
    vids = [{"metrics": {"platform": "instagram", "views": 20000, "likes": 1500, "comments": 300, "shares": 200}}] * 6
    missing = {"metrics": {"platform": "instagram", "views": None, "likes": 3000, "comments": 600, "shares": 400}}
    assert round(_views(missing, _engagement_rates(vids + [missing]))) == 40000


def test_publication_coordonnee():
    from htf.analyze import coordination
    t0 = datetime(2026, 11, 2, tzinfo=timezone.utc)
    copy = "Paroles : regardez ce que le gouvernement cache sur la nouvelle taxe sur les livrets partagez avant suppression"

    def v(i, acc, txt):
        return {"id": f"x{i}", "source": "oriane", "account": acc, "published_at": (t0 + timedelta(hours=i)).isoformat(), "text": txt}

    campaign = [v(i, f"compte{i}", copy) for i in range(7)]
    normal = [v(10 + i, f"autre{i}", f"Paroles : avis personnel {i} sur l'épargne, mots différents à chaque fois {i * 7}") for i in range(10)]
    assert coordination(campaign + normal)["comptes"] == 7
    assert coordination(normal) is None


def test_brief_perime_jamais_exporte(monkeypatch):
    from htf import export
    config.OUT_DIR.mkdir(parents=True)
    topic = {"id": "t1", "titre": "Nouveau titre", "rang": 1, "etat": "à surveiller", "sujet_type": "x", "politique": True,
             "themes": [], "videos_total": 1, "videos_recentes": 1, "score": 1, "tons": {}, "couverture": [],
             "couvert": False, "couvert_par_brut": False, "serie": [], "video_declencheur": None, "videos": [],
             "signaux": {"acceleration": 1, "createurs_recents": 1, "surperformance_mediane": 1, "engagement": 0}}
    (config.OUT_DIR / "topics.json").write_text(json.dumps([topic]))
    (config.OUT_DIR / "brief.json").write_text(json.dumps([{"sujet": "t1", "titre": "Ancien titre", "etat": "x",
                                                            "pourquoi": "", "angle": "", "deja_traite_par": []}]))
    sent = defaultdict(list)

    class FakeHttp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def delete(self, *a, **k): return httpx.Response(204, request=httpx.Request("DELETE", "http://x"))
        def post(self, path, content): sent[path] += json.loads(content); return httpx.Response(201)

    monkeypatch.setattr(export, "_client", lambda: FakeHttp())
    export.run()
    assert sent["/brief"] == []


def test_couverture_connue_depuis():
    from htf.analyze import coverage_known_since

    def m(acc, source, day):
        return {"account": acc, "source": source, "published_at": f"{day}T08:00:00+00:00"}

    medias = [m("Le Monde", "archive", f"2026-10-{d}") for d in range(21, 31)]
    medias += [m("HugoDécrypte", "youtube", f"2026-10-{d}") for d in range(27, 31)] + [m("HugoDécrypte", "youtube", "2026-10-31")]
    medias += [m("CNews", "youtube", "2026-10-30")]  # trop peu de contenus : ignoré
    known = coverage_known_since(medias)
    assert known == {"presse": "2026-10-21", "concurrents": "2026-10-27"}


def test_citation_retrouvee_dans_la_video():
    from htf.analyze import locate
    m = {"chunks": [[0.0, "salut tout le monde"], [4.2, "le gouvernement veut taxer"], [6.0, "les livrets A des étudiants"]],
         "frames": [[9.5, "https://x/f.webp", "ILS VEULENT TAXER TON LIVRET A"]]}
    assert locate("le gouvernement veut taxer les livrets A", m) == {"seconde": 4.2}
    assert locate("Ils veulent taxer ton livret A", m) == {"seconde": 9.5, "image": "https://x/f.webp"}
    assert locate("une phrase absente de la vidéo entière", m) == {}


def _video(i, hours, followers=1000, views=1000, account=None):
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return {"id": f"v{i}", "account": account or f"c{i}", "url": None, "source": "oriane",
            "published_at": (t0 + timedelta(hours=hours)).isoformat(),
            "metrics": {"views": views, "followers": followers, "likes": 0, "comments": 0, "shares": 0}}


def test_video_pivot():
    from htf.analyze import pivot
    calm = [_video(i, i * 20) for i in range(5)]                      # 1 vidéo toutes les 20 h
    early = _video(50, 30, followers=100, views=5000)                 # surperforme, mais rien ne suit
    spark = _video(99, 120, followers=100, views=8000)                # surperforme, puis tout s'emballe
    wave = [_video(100 + i, 122 + i * 2) for i in range(12)]
    best, effect = pivot(calm + [early, spark] + wave, {"*": 0.05})
    assert best["id"] == "v99" and effect["apres_48h"] == 12


def test_preuve_hors_legende_et_anciennes_annotations():
    from htf import annotate, store
    from htf.analyze import evidence
    vids = [_video(i, i, views=1000 * (10 - i)) for i in range(4)]
    base = {"sujet": "s", "ton": "critique", "affirmation": "a", "personnalites": []}
    v3 = lambda suffit, canal, cit: {**base, "legende_suffit": suffit, "canal": canal, "citation": cit,
                                     "reaction_public": "rejet"}
    store.save_annotations("v3", {"v0": v3(False, "paroles", "on paie deux fois plus cher"),
                                  "v1": v3(False, "texte à l'écran", "loyer x2 en un an"),
                                  "v2": v3(True, "légende", "")})
    store.save_annotations("v2", {"v3": {**base, "personnalites": ["Marie Dupont"]}})  # ancienne annotation
    notes = annotate.notes()
    assert annotate.names(notes["v3"]) == ["Marie Dupont"] and annotate.treatment(notes["v3"], "Marie Dupont") == "critique"
    proof = evidence(vids, notes, {"*": 0.05})
    assert proof["videos_lues"] == 3 and proof["part_hors_legende"] == 0.67
    assert [q["video"] for q in proof["citations"]] == ["v0", "v1"]


def test_garde_fous_annotation():
    from htf.annotate import _guard
    text = "Paroles : le loyer a doublé en un an à Lyon\nLégende : ça suffit #logement"
    note = {"reaction_public": "rejet", "citation": "le loyer a doublé en un an"}
    _guard(note, text)
    assert note == {"reaction_public": "sans commentaires", "citation": "le loyer a doublé en un an"}
    note = {"reaction_public": "rejet", "citation": "les loyers explosent partout en France"}
    _guard(note, text + "\nCommentaires populaires : honteux | pareil chez moi")
    assert note == {"reaction_public": "rejet", "citation": ""}
