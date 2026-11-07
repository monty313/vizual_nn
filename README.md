# vizual_nn

## Project mission
Build and maintain the vizual nn project with reliable setup, execution, and delivery workflows.

## What this repository currently contains
Top-level structure:
- `.env.example` (file)
- `.gitignore` (file)
- `doctrine` (dir)
- `lab` (dir)
- `README.md` (file)
- `requirements.txt` (file)
- `run.py` (file)
- `seeds` (dir)
- `tests` (dir)
- `web` (dir)

Primary languages/tooling detected: Python (16), Markdown (2), JavaScript (1)

Likely key implementation files:
- `README.md`

## Quickstart (operator + LLM friendly)
Use this sequence first, then adapt to repo-specific details.

1. Clone and enter repo:
   ```bash
   git clone https://github.com/monty313/vizual_nn.git
   cd vizual_nn
   ```
2. Setup environment/dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run locally:
   ```bash
   python main.py  # adjust to project entrypoint
   ```
4. Validate changes:
   ```bash
   pytest -q
   ```

## Operating intent (CEO-mode guide for future LLMs)
When continuing this project, optimize for business outcome first:

- Preserve or improve strategy quality, reliability, and reproducibility.
- Prefer small, testable, reversible changes over broad rewrites.
- Keep docs synchronized with code behavior.
- Add explicit assumptions, constraints, and success criteria in every major change.

## Delivery checklist
- [ ] Environment setup is deterministic.
- [ ] Primary run path is documented and works.
- [ ] Validation/test path is documented and works.
- [ ] Key risks and TODOs are tracked in the handoff file.

## Branch and release notes
- Default branch: `main`
- Keep PRs focused and attach proof-of-run or proof-of-test for behavior changes.
