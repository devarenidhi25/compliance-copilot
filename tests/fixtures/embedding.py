class TestEmbedder:
    __test__ = False
    # Deterministic synthetic test vectors, never a production fallback.
    def identity(self): return {'model':'synthetic-test-only','revision':'1'}
    def encode(self, texts):
        return [[1.0 if 'identity' in t.lower() else 0.0,1.0 if 'review' in t.lower() else 0.0,0.1] for t in texts]

