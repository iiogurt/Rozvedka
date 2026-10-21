"""GLEIF: how a list company is recognised in the LEI register, and the ownership links it brings into the network."""
from rozvedka import gleif


def rec(lei, name, country, reg="", other=()):
    return {"lei": lei, "name": name, "country": country, "reg": reg, "other": list(other), "city": "", "hq": country,
            "jurisdiction": country, "form": "", "status": "ACTIVE", "registration": "ISSUED", "initial": "", "updated": ""}


def co(names, countries, leis=(), numbers=()):
    return {"names": names, "countries": countries, "leis": list(leis), "numbers": list(numbers)}


def test_an_lei_the_entry_states_decides():
    m = gleif.match({"US:1": co(["SOMETHING ELSE"], [], leis=["LEI0000000000000001"])}, {"LEI0000000000000001": rec("LEI0000000000000001", "X", "RU")})
    assert m == {"US:1": {"leis": ["LEI0000000000000001"], "how": "lei"}}


def test_registration_numbers_need_the_country_and_a_name_word_or_an_ogrn():
    companies = {"US:1": co(["INTERNATIONAL TRADE AND INDUSTRIAL TECHNOLOGY"], ["DE"], numbers=["HRB12345"]),
                 "US:2": co(["LUKOIL OAO"], ["RU"], numbers=["1027700035769"]),
                 "US:3": co(["KIMPAS KIMYEVI MADDELER"], ["TR"], numbers=["4810512"]),
                 "US:4": co(["ACME"], ["FR"], numbers=["4810512"])}
    records = {"A": rec("A", "Brüll GmbH", "DE", "HRB 12345"),                                  # the same number, another company
               "B": rec("B", 'Публичное акционерное общество "Нефтяная компания "ЛУКОЙЛ"', "RU", "1027700035769"),   # an OGRN
               "C": rec("C", "KİMPAŞ KİMYEVİ MADDELER PAZARLAMA", "TR", "4810512")}
    m = gleif.match(companies, records)
    assert "US:1" not in m and m["US:2"] == {"leis": ["B"], "how": "registration"}
    assert m["US:3"]["leis"] == ["C"] and "US:4" not in m                                    # another country


def test_names_need_the_country_a_distinctive_name_and_one_record():
    companies = {"US:1": co(["ORION LIMITED LIABILITY COMPANY"], ["RU"]),
                 "US:2": co(["PERSIA INTERNATIONAL BANK PLC"], ["GB"]),
                 "US:3": co(["CREDIT BANK OF MOSCOW"], []),                        # no country: never by name
                 "US:4": co(["ALPHA BETA TRADING"], ["AE"])}
    records = {"A": rec("A", "Orion Limited Liability Company", "RU"), "B": rec("B", "PERSIA INTERNATIONAL BANK PLC", "GB"),
               "C": rec("C", "Credit Bank of Moscow", "RU"), "D": rec("D", "Alpha Beta Trading", "AE"),
               "E": rec("E", "ALPHA BETA TRADING", "AE")}
    m = gleif.match(companies, records)
    assert set(m) == {"US:2"} and m["US:2"]["how"] == "name"                  # Orion is too common; two Alpha Betas


def test_words_read_cyrillic_and_drop_legal_forms():
    assert gleif.words('Общество с ограниченной ответственностью "Бизнес-Финанс"') >= {"biznes", "finans"}
    assert gleif.words("JSC Bank “National Standard”") == {"bank", "national", "standard"}
    assert not gleif.distinctive("ORION LLC") and gleif.distinctive("PERSIA INTERNATIONAL BANK") and gleif.distinctive("Chelyabinvestbank")
    assert gleif.country("Russia") == "RU" and gleif.country("Korea, North") == "KP" and gleif.country("DE") == "DE"
    assert gleif.label(rec("X", "Банк ЗЕНИТ", "RU", other=["Bank ZENIT"])) == "Bank ZENIT"


def test_the_network_layer(monkeypatch):
    from rozvedka import ties
    g = ties._Graph({})
    g.node("US:1", "org", "LUKOIL OAO", "us", {"list": "US"})

    class Targets:                                    # the list entries the build recognised
        root = {"US:1": "US:1"}

        def node(self, key):
            return "US:1"
    g.targets = Targets()
    st = {"meta": {"retrieved": "2026-10-21"},
          "matches": {"US:1": {"leis": ["P"], "how": "lei"}, "US:9": {"leis": ["Q"], "how": "name"}},   # US:9 is on no list now
          "records": {"P": rec("P", "PJSC LUKOIL", "RU"), "C": rec("C", "LUKOIL Securities B.V.", "NL")},
          "relations": [{"child": "C", "parent": "P", "type": "IS_DIRECTLY_CONSOLIDATED_BY", "status": "ACTIVE", "start": "2021-01-01",
                         "end": "", "accounts": ["2021-01-01", "2021-12-31"], "validation": "FULLY_CORROBORATED", "reference": ""},
                        {"child": "X", "parent": "P", "type": "IS_DIRECTLY_CONSOLIDATED_BY", "status": "INACTIVE", "start": "",
                         "end": "", "validation": "", "reference": ""}]}                                # X has no record: skipped
    monkeypatch.setattr(gleif, "stored", lambda: st)
    assert ties._from_gleif(g) == {"matched": 1, "relations": 1, "nodes": 1}
    import json
    assert json.loads(g.entities["US:1"][4])["gleif"][0]["how"] == "lei"
    (t,) = g.ties.values()
    assert t[:5] == ["lei:C", "US:1", "directly owned by", "direct parent of", "gleif"]
    assert json.loads(t[7])["accounts"] == ["2021-01-01", "2021-12-31"] and g.entities["lei:C"][3] == "gleif"
