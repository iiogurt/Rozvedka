"""Wikidata fetching for the actor gazetteer: replies the API cut short are asked again, so no entity is lost."""
from rozvedka import actor_sources


def test_truncated_replies_are_asked_again_in_halves(monkeypatch):
    big = {"Q2", "Q7", "Q8"}                        # like countries: a reply holding more than one of them is cut short
    asked = []

    def fake_get(url, params=None, **kw):
        ids = params["ids"].split("|")
        asked.append(len(ids))
        ents, size = {}, 0
        for q in ids:
            size += 10 if q in big else 1
            if size > 12:                              # the API stops adding entities at its size limit
                return {"warnings": {"result": {"*": "This result was truncated"}}, "entities": ents}
            ents[q] = {"missing": ""} if q == "Q5" else {"id": q}
        return {"entities": ents}

    monkeypatch.setattr(actor_sources, "_get", fake_get)
    qids = [f"Q{i}" for i in range(1, 61)]
    got = actor_sources.entities(qids, "labels", ["en"])
    assert set(got) == set(qids) - {"Q5"}             # every entity arrives; a missing one is not asked again
    assert asked[0] == 50 and len(asked) > 2


def test_an_entity_too_large_alone_is_skipped_not_retried_forever(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append(params["ids"])
        return {"warnings": {"result": {"*": "This result was truncated"}}, "entities": {}}

    monkeypatch.setattr(actor_sources, "_get", fake_get)
    assert actor_sources.entities(["Q1", "Q2"], "labels", ["en"]) == {}
    assert calls == ["Q1|Q2", "Q1", "Q2"]
