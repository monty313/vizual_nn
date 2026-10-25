# Private doctrine folder

Drop your private `kag_mark_doctrine/` files here (schema.yaml, logical_forms.md, obs_feel_spec.md,
PRINCIPLES_LEARNING.md, seed_triples.jsonl, ...). Everything in this folder except this README is
git-ignored, so proprietary doctrine never reaches the public repo.

When present, `lab/student.py` loads these files (`.md`, `.yaml`, `.txt`) into the LLM
student's system prompt as the knowledge graph it must reason over. The coded doctrine teacher in
`lab/doctrine.py` works without them.
