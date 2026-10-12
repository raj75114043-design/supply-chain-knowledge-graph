from sckg.eval.run import evaluate, gate


def test_quality_gate_passes():
    m = evaluate()
    assert gate(m) == [], gate(m)
