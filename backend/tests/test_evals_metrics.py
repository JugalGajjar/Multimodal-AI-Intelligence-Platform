from evals.metrics import keyword_coverage, mean, recall_at_k


class TestRecallAtK:
    def test_full_overlap_is_one(self):
        assert recall_at_k({"a", "b"}, ["a", "b", "c"]) == 1.0

    def test_no_overlap_is_zero(self):
        assert recall_at_k({"a"}, ["b", "c"]) == 0.0

    def test_partial_overlap(self):
        assert recall_at_k({"a", "b", "c"}, ["a", "b", "x"]) == 2 / 3

    def test_empty_expected_is_vacuous_one(self):
        # No grounding requirement → don't penalise.
        assert recall_at_k(set(), ["a", "b"]) == 1.0

    def test_duplicate_retrieved_ids_dont_inflate(self):
        # Set semantics on retrieved side prevent double-counting.
        assert recall_at_k({"a", "b"}, ["a", "a", "a"]) == 0.5


class TestKeywordCoverage:
    def test_all_present(self):
        assert keyword_coverage(["foo", "bar"], "foo and bar") == 1.0

    def test_case_insensitive(self):
        assert keyword_coverage(["Foo"], "the FOO is here") == 1.0

    def test_substring_match(self):
        # "Kafka" matches inside "Apache Kafka cluster".
        assert keyword_coverage(["Kafka"], "Apache Kafka cluster") == 1.0

    def test_none_present(self):
        assert keyword_coverage(["zzz"], "foo bar") == 0.0

    def test_partial(self):
        assert keyword_coverage(["foo", "bar", "baz"], "foo bar") == 2 / 3

    def test_empty_keywords_is_vacuous_one(self):
        assert keyword_coverage([], "anything") == 1.0

    def test_blank_keyword_ignored(self):
        # An accidental empty string in the dataset shouldn't always-match.
        assert keyword_coverage(["", "foo"], "foo") == 1.0


class TestMean:
    def test_mean_of_values(self):
        assert mean([1.0, 2.0, 3.0]) == 2.0

    def test_empty_is_none(self):
        assert mean([]) is None
