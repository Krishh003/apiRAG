# Answer review protocol

No LLM judge is used. Generation and human review are optional, incomplete until
actual answers and named reviewer annotations exist. Empty reviews are pending,
never zero scores or successful answers. Agent-authored labels are not human
adjudication. Keep completed answer runs under ignored `evaluation/private/`
until inspected for secrets.

Generate a review packet from saved retrieval predictions (answers initially null):

```powershell
python -m evaluation.answers prepare --predictions docs/evaluation/results/offline/predictions.jsonl --config bm25 --output evaluation/private/review.jsonl
```

For a bounded live generation experiment, set `GEMINI_API_KEY` in the process
environment using your secret manager, then:

```powershell
python -m evaluation.answers generate --limit 12 --output evaluation/private/answers-01
```

This selects two queries per mode followed by ambiguous, absent and adversarial cases. It calls
the existing classifier and four handlers sequentially, with a fresh synthetic
Chroma index, no production startup or ingestion scheduler. Gemini model names,
temperatures and system prompts remain those audited in the handlers. Every
model-call prompt, latency, usage metadata and model id is recorded. Planning
uses no graph in this optional run and is explicitly labeled accordingly; use
the dedicated graph experiment to test source coverage. A 12-question run is
a smoke sample, not a full answer-quality benchmark. Third-party model service
availability and stochastic output limit reproducibility even at low temperature.

In each answer row fill `review` with:

```json
{
  "reviewer": "reviewer-alias",
  "factual_correctness": 2,
  "grounding": 2,
  "unsupported_claims": 0,
  "abstained": false,
  "notes": "List checked facts and cite source IDs; explain any deduction."
}
```

Rubric:

- Correctness: 2 = all required facts correct and no material errors; 1 = partial,
  missing required facts or minor error; 0 = materially wrong, nonexistent API or
  wrong workflow. A justified abstention/clarification on an unanswerable question
  gets 2 if it contains no misleading facts.
- Grounding: 2 = all factual claims supported by supplied source text; 1 = mixed;
  0 = material unsupported claims. For advisory responses, distinguish valid
  general advice from KB-supported claims; general advice alone is not KB grounding.
- Unsupported claims: count atomic factual claims with no supporting evidence,
  even when the answer also abstains. Record the actual claim in notes.
- Abstained: true only if the answer clearly refuses to invent missing information
  or requests the needed clarification. Also score incorrect abstention on
  answerable items as missing required facts.

Review endpoint, HTTP method, authentication, required parameters, state
transitions, units, limits and workflow dependencies. Do not use word overlap as
factual correctness. Review at least all adversarial/absent cases and a stratified
sample of each mode; ideally use two reviewers blinded to retrieval configuration
with adjudication and report agreement. These checks are not yet performed.

```powershell
python -m evaluation.answers score --reviews evaluation/private/answers-01/answers.jsonl --output evaluation/private/review-summary.json
```

The scorer reports normalized correctness and grounding over **reviewed** answers,
unsupported-claim answer rate and abstention on reviewed unanswerable items,
with denominators and pending counts. Report coverage alongside scores to avoid
selection bias. Human scores remain subjective, not objective ground truth.

Costs are null by default. Optional `--prices rates.json` maps each model to
`input_per_million`, `output_per_million`, `date`, `source`; provide rates verified
for that run. Estimates cover reported input/output tokens only and can exclude
thinking tokens, caching and billing adjustments. No price is fabricated here.
