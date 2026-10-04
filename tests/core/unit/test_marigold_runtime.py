from etsy_listings.core.preparation.runtime import Runtime


def test_inspection_of_missing_runtime_is_read_only(tmp_path):
    home = tmp_path / 'home'
    report = Runtime(home=home).inspect()
    assert not report.available
    assert 'etsy-listings marigold setup' in report.problem
    assert not home.exists()
