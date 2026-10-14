# Synthetic development evidence

All fixture documents and deterministic embedding/model responses are fictional.
`TestEmbedder` in the retrieval tests supplies small vectors solely to exercise the
real persistent Chroma index; it is never imported by application code.
Tests use isolated temporary corpus/index paths. Production has no fixture seeding.
