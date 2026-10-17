# Darwin Inc.

**Human org charts are generation zero.**

Everyone organizes AI agent teams by copying human org charts. But agents aren't human: they can be cloned, share memory instantly, and never get tired. Darwin Inc. treats an org chart as code and lets agents evolve past it.

Built at the Recursive Agents Hackathon (Crusoe x Cerebral Valley, Oct 17, 2026) on **NVIDIA Nemotron** via **Crusoe Managed Inference**, with **You.com** web search.

## How it works

1. **An organization is a YAML file.** Roles, handoffs, who can veto, how many parallel attempts, shared memory, circuit breakers. Swap the file, get a different company. See [`orgs/`](orgs/).
2. **Three human seed orgs (generation 0):**
   - `crusoe_general`: teaching hospital. Triage writes the definition of done, a fellow implements, an attending with veto power reviews, discharge re-runs the team's tests. Inspired by Cockroach Labs' [MOLT Sinai](https://www.cockroachlabs.com/blog/experiment-running-hospital-code/).
   - `research_lab`: the PI sets direction, three grad students attempt in parallel, an undergrad writes tests, the PI picks the best attempt, lab meeting = shared memory.
   - `flat_startup`: one engineer, no review. The baseline.
3. **Same work, fair grading.** Every org fixes the same vague one-line issues (`tasks/`), graded by hidden tests the agents never see.
4. **Evolution.** A Nemotron meta-agent reads where each org failed and proposes one structural mutation: a blind reviewer who never sees the code, five disposable clones that race, instant shared memory, giving a role web search, changing the circuit breaker. A mutant survives only if it beats its parent.
5. **Controlled experiment.** Prompts for each kind of work (`prompts/`) are frozen and shared by every org. Only structure changes, so any score difference comes from organization, not prompt wording.
6. **Held-out exam.** The best human org, the evolved champion and the baseline are re-scored on tasks evolution never saw.

Every step is written to `runs/<id>/events.jsonl`, so a run can be replayed visually without calling any model.

## Run it

```bash
pip install -r requirements.txt
export CRUSOE_API_KEY=...          # never commit this
export YDC_API_KEY=...             # optional: enables You.com search
export DARWIN_BUDGET=5             # hard spend cap in USD

python run.py check                # key works? Nemotron models found?
python run.py once --org hospital --task median
python run.py compare --split train
python run.py evolve --generations 3 --children 2
```

Offline (no key, fake model, for plumbing): `DARWIN_MOCK=1 python run.py evolve --generations 1`

Models (override with `DARWIN_WORKER_MODEL` / `DARWIN_META_MODEL`): workers use `nvidia/nemotron-3.5-lightning-30b-a3b`, the meta-agent uses `nvidia/Nemotron-3-Super-120B-A12B`.

## Layout

```
orgs/        seed org charts (YAML)
prompts/     frozen prompts, one per kind of work
tasks/       train/ and heldout/: issue.md, starter.py, hidden_test.py
reference/   reference solutions (only used to verify the hidden tests)
darwin/      engine.py (runs an org), evolve.py (mutations + meta-agent),
             evaluate.py (scoring), llm.py (Crusoe/Nemotron), search.py (You.com),
             sandbox.py (isolated test runs)
run.py       CLI
```

## Built during the hackathon

Everything in this repository was written on Oct 17, 2026 during the event. The teaching-hospital org is our own re-implementation of the idea in Cockroach Labs' blog post; no code or prompts were copied.
