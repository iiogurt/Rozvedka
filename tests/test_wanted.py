"""Wanted notices (rozvedka/wanted.py): what is kept of a notice, how its names and relation words are read."""
from rozvedka import identity, wanted


def test_dates_written_month_first():
    assert identity.dob("December 28, 1951") == "1951-12-28"
    assert identity.dob("June 20,  1991 (35 years)") == "1991-06-20"
    assert identity.dob("10 Dec 1948") == "1948-12-10"


def test_names_and_cases():
    assert wanted._name("MARY CAROLE MCDONNELL") == "Mary Carole Mcdonnell"
    assert wanted._name("Wang, Hongwei") == "Wang Hongwei"
    assert wanted.is_case("GRU 29155 CYBER ACTORS", [])
    assert wanted.is_case("APT 41 GROUP", []) and wanted.is_case("JABBERZEUS SUBJECTS", [])
    assert not wanted.is_case("WANG DONG", []) and not wanted.is_case("APT 41 GROUP", ["1980-01-01"])
    assert wanted.case_label("GRU 29155 CYBER ACTORS") == "GRU 29155 Cyber Actors"


def test_relation_words():
    s = "Potemkin is alleged to have been a Russian military intelligence officer assigned to Unit 74455."
    assert wanted.relation(s, person=False) == ("member or officer", "officer")
    # another person is never a target, nor a fellow "member": family, an associate or charged together
    assert wanted.relation("He is the uncle of Fausto Isidro Meza-Flores, also known as El Chapo Isidro.", True)[0] == "family"
    assert wanted.relation("Zhou Shuai and Yin Kecheng are wanted for compromising computers worldwide.", True)[0] == "charged together"
    assert wanted.relation("He was one of bin Laden's most trusted associates before the attacks.", True)[0] == "associate"
    assert wanted.relation("He committed cyber attacks against agencies of the government.", False)[0] == "target"
    assert wanted.relation("Son Un Chol and Kim Mu Rim are wanted.", True)[0] == "charged together"      # a surname, not a son
    assert wanted.relation("He is wanted for the abduction of Robert Levinson.", True)[0] == "victim"
    assert wanted.relation("Prigozhin was the primary funder of the Internet Research Agency.", False)[0] == "support or funding"
    assert wanted.relation("Both men did business with Example Ltd.", False) == ("", "")


def test_actor_of_needs_a_safe_name():
    rows = {"A": {"kind": "person", "data": '{"names": [{"name": "Emilio Lopez"}], "description": "Spanish writer"}'},
            "B": {"kind": "person", "data": '{"names": [{"name": "Park Jin Hyok"}], "description": "North Korean programmer"}'},
            "C": {"kind": "person", "data": '{"names": [{"name": "El Señor"}], "description": "Colombian drug trafficker"}'},
            "D": {"kind": "person", "data": '{"names": [{"name": "Wang Dong"}], "description": "Chinese spy, wanted by FBI"}'}}

    def entry(name, *aliases):
        return {"name": name, "names": [name, *aliases]}
    got = wanted.actor_of({"FBI:1": entry("Emilio Jose Corredor Lopez", "Emilio Lopez"),   # two words, no trade: not him
                           "FBI:2": entry("Park Jin Hyok"),                                # three words
                           "FBI:3": entry("Melvin Perez Cardenas", "El Senor"),             # a title, not a name
                           "FBI:4": entry("Wang Dong")}, rows)                              # two words, a spy
    assert got == {"FBI:2": "B", "FBI:4": "D"}


def test_european_fields():
    page = """<div class="field field--name-field-w-first-name"><div>MOINI, Armin</div></div>
      <div class="field field--name-field-alias"><div class="field-label">Alias</div><div>Nero</div></div>
      <div class="field field--name-field-crime"><div class="field-label">Crime</div>
        <div>Illicit trafficking in narcotic drugs</div>
        <div>Laundering of the proceeds of crime</div></div>"""
    p = wanted._Fields()
    p.feed(page)
    assert p.get("field-w-first-name") == "MOINI, Armin"
    assert wanted._field_values(p, "field-alias", "Alias") == ["Nero"]
    assert wanted._field_values(p, "field-crime", "Crime") == ["Illicit trafficking in narcotic drugs", "Laundering of the proceeds of crime"]


def test_relation_word_near_the_name():
    long = ("The indictment charges Ivan Petrov, Pavel Sidorov and Oleg Ivanov with hacking campaigns that hurt thousands of "
            "victims in many countries and caused losses of hundreds of millions of dollars worldwide.")
    assert wanted.relation(long, True, "pavel sidorov")[0] == "charged together"           # "victims" is not about him
    assert wanted.relation("He is wanted for the abduction of Robert A. Levinson.", True, "robert a levinson")[0] == "victim"
    s = ("He is reportedly a senior leader of the Haqqani network, a group in Afghanistan and Pakistan that has fought for decades, "
         "and keeps up close ties to the Taliban and al Qaeda.")
    assert wanted.relation(s, False, "al qaeda") == ("", "")                                # "senior" is the Haqqani network's


def test_members_of_a_target():
    s = "Parvar ran false personas in a campaign targeting current and former members of the United States Intelligence Community."
    assert wanted.relation(s, False, "united states intelligence community")[0] == "target"
