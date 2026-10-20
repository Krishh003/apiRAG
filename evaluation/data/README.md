# Synthetic fixture v1

Original fictional contracts, authored specifically for this benchmark. No public
API claims, company documents, customer data or production database exports.
All origins use the reserved `.example` namespace. No network fetch is needed.

`corpus.jsonl`: stable document id, provenance, APIEntry-compatible entry and facts.
One endpoint per document. Relationships refer to other synthetic operation names.

`questions.jsonl`: 100 questions, 25 endpoint, 25 auth/parameters, 12 planning,
12 comparison, 10 advisory, 6 ambiguous, 5 absent, 5 adversarial. Of these, 87 are
answerable. Three adversarial questions have false premises correctable from
sources. Two ask for nonexistent/secret information and are unanswerable.

`question.schema.json` documents annotation types. `evaluation.dataset.validate`
also enforces referential integrity, unique ids, relationship targets, synthetic
provenance and answerability consistency. Grade 2 means necessary direct evidence;
grade 1 means supporting context. v1 uses grade 2 for every labeled document.
Unlisted documents are nonrelevant **under these authored labels**, not an
independent judgment that no other useful supporting evidence exists.

Ambiguous requests intentionally have no qrels: clarification is the reference
behavior. Their nonempty retrieval results must not be counted as successful
answers or as failed recall. Evaluate their generated behavior separately.
Multi-hop references require all listed source facts. Reference plans specify
operation order; source recall alone does not score step ordering.

Annotations and documents were authored together, with repeated question forms.
This is a small transparent regression benchmark, not a representative production
sample or independently adjudicated test collection. No tuning/validation/test
split is claimed. Independent review and a larger held-out corpus remain needed.
Keep the frozen v1 unchanged when tuning; version future annotations separately.

Rebuild deterministically: `python -m evaluation.build_fixture`. Validate and
print SHA256 fingerprints: `python -m evaluation.dataset`. No private material
is read by either command.
