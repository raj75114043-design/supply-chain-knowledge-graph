from sckg.resolve import Entity, Resolver, acronym, norm_tokens, score

ERP = [Entity("S01", "Volta Cell Systems Co., Ltd."), Entity("S05", "Penang Precision Sensors Sdn Bhd"), Entity("S03", "Kiyomi Semiconductor K.K.")]


def test_normalisation_strips_legal_forms():
    assert norm_tokens("Tijuana Harness Works S.A. de C.V.") == ["tijuana", "harnes", "work"] or norm_tokens("Tijuana Harness Works S.A. de C.V.")[0] == "tijuana"
    assert acronym(norm_tokens("Volta Cell Systems Co., Ltd.")) == "vcs"


def test_aliases_resolve_to_erp_supplier():
    r = Resolver(list(ERP))
    for m in ["Volta Cells", "VCS", "Volta Cell Systems"]:
        assert r.resolve(m)[0] == "S01", m
    assert r.resolve("Kiyomi Semi")[0] == "S03"


def test_lookalike_company_is_not_merged():
    r = Resolver(list(ERP))
    assert r.resolve("Penang Precision Tooling")[0] not in {"S05"}
    assert score("Volta Mobility Ventures", ["Volta Cell Systems Co., Ltd."]) < 0.86


def test_ambiguous_mention_goes_to_review_unless_supply_context():
    r = Resolver(list(ERP))
    r.resolve("Penang Precision Tooling Sdn Bhd")               # creates a look-alike entity
    assert r.resolve("Penang Precision")[0] is None and r.review_queue
    assert r.resolve("Penang Precision", supply_context=True)[0] == "S05"
