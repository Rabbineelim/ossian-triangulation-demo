# Ossian Triangulation Stage

This fork adds a presentable domain-filtered triangulation stage after Ossian's existing import and cleaning workflow.

## What changed

- New project route: `/projects/{pid}/triangulate`
- Source-level domain assignment and optional subdomain/context
- Record-level evidence extraction from approved `cleaned_units`
- Source-specific aggregation into findings
- Domain + theme comparability gate
- Convergent concern, convergent strength, divergent, mixed/complementary, and insufficient-source outcomes
- Human review of proposed claims
- Evidence drill-down to the original cleaned unit
- JSON and CSV triangulation exports
- New persistent SQLite tables for assignments, evidence, findings, results, and reviews

## Run locally

```bash
pip install -r requirements.txt
python -m ossian.web
```

Open `http://127.0.0.1:8000`.

## Demo sequence

1. Create a project.
2. Upload at least two sources about the same domain.
3. Run cleaning and review the cleaned units.
4. Return to the project and click **Triangulate**.
5. Confirm the source domains.
6. Click **Run triangulation**.
7. Filter by domain, inspect source findings and evidence, then approve/edit/reject a proposed result.
8. Export CSV or audit JSON.

## Safety of the original repository

Work in your fork or in a separate Git branch. Nothing changes in the teammate's original repository unless you push there or they merge a pull request.

## Current analysis limitation

The included theme and stance extraction is a deterministic keyword baseline intended to demonstrate and evaluate the framework. It is transparent and auditable, but not a final NLP model. A later embedding, classifier, or LLM layer can replace the extractor while preserving the same workflow and database contract.
