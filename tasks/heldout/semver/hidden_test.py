from solution import compare_versions as c
def test_numeric(): assert c("1.10.0", "1.9.0") == 1
def test_equal(): assert c("2.0.0", "2.0.0") == 0
def test_prerelease_lower(): assert c("1.0.0-alpha", "1.0.0") == -1
def test_alpha_vs_alpha1(): assert c("1.0.0-alpha", "1.0.0-alpha.1") == -1
def test_numeric_ids(): assert c("1.0.0-beta.2", "1.0.0-beta.11") == -1
def test_numeric_vs_alpha(): assert c("1.0.0-1", "1.0.0-alpha") == -1
def test_build_ignored(): assert c("1.0.0+build.5", "1.0.0+build.9") == 0
def test_rc(): assert c("1.0.0-rc.1", "1.0.0-beta.11") == 1
