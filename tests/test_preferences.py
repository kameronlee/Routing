from routing_backend.preferences import preference_from_descriptors


def test_descriptors_raise_relevant_weights() -> None:
    pref = preference_from_descriptors(["heat sensitive", "noise averse", "scenic"])

    assert pref.weight_cool > 1.0
    assert pref.weight_quiet > 1.0
    assert pref.weight_scenic > 1.0
    assert pref.comfort_threshold < 26.0
