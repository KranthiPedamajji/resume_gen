# resume_gen (Resume RAG Backend)

## Setup

1) Put resume files in `storage/resumes/` (supported: .pdf, .docx, .txt) or upload via `/upload-resumes`.
2) Copy `.env` and set `ANTHROPIC_API_KEY`.
3) Install requirements:

```
pip install -r requirements.txt
```

4) Run the server:

```
uvicorn app.main:app --reload --port 8000
```

## Streamlit UI (optional)

Install UI deps (already in requirements.txt) and run:

```
streamlit run ui/app.py
```

To point the UI at a different backend URL:

```
set BACKEND_URL=http://127.0.0.1:8000
```

## Health

```
curl -X GET http://127.0.0.1:8000/health
```

## Parse JD

```
curl -X POST http://127.0.0.1:8000/parse-jd -H "Content-Type: application/json" -d '{"jd_text":"..."}'
```

## Upload resumes

```
curl -X POST "http://127.0.0.1:8000/upload-resumes" \
  -F "files=@storage/resumes/python_fullstack.pdf" \
  -F "files=@storage/resumes/java_fullstack.docx"
```

## Reindex

```
curl -X POST http://127.0.0.1:8000/reindex
```

## Generate

```
curl -X POST http://127.0.0.1:8000/generate -H "Content-Type: application/json" -d '{"jd_text":"...","top_k":25}'
```

Optional flags:
- `multi_query`: enable multi-query retrieval
- `parse_with_claude`: use Claude for JD parsing when multi-query is enabled
- `audit`: run a second Claude audit for unsupported claims
- `domain_rewrite`: enable domain-aware and company-aware bullet framing
- `target_company_type`: one of `startup`, `enterprise`, `regulated`, `bigtech`

The response may include `resume_id` for editing.

## Export DOCX

```
curl -X POST http://127.0.0.1:8000/export-docx -H "Content-Type: application/json" -d '{"company_name":"Acme","position_name":"Data Engineer","jd_text":"..."}'
```

Export from an existing resume_id (no Claude call):

```
curl -X POST http://127.0.0.1:8000/export-docx -H "Content-Type: application/json" -d '{"resume_id":"<resume_id>","jd_text":"..."}'
```

## Resume editing (patch one bullet)

Generated resume state is saved under:
`storage/generated_resumes/<resume_id>/v1/`

Fetch latest state and roles:

```
curl -X GET http://127.0.0.1:8000/resumes/<resume_id>
```

Edit a single bullet and re-export DOCX:

```
curl -X PATCH http://127.0.0.1:8000/resumes/<resume_id>/bullet -H "Content-Type: application/json" -d '{
  "role_selector": { "company": "Acme Inc", "dates": "May 2021 - Jul 2023" },
  "bullet_index": 2,
  "new_bullet": "Improved data quality checks for analytics pipelines and reporting.",
  "export_docx": true
}'
```

## ATS score

```
curl -X POST http://127.0.0.1:8000/ats-score -H "Content-Type: application/json" -d '{
  "jd_text": "...",
  "resume_id": "<resume_id>",
  "top_n_skills": 25,
  "strict_mode": true
}'
```

## Overrides + patch suggestions + apply

Save user overrides:
```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/overrides -H "Content-Type: application/json" -d '{
  "skills": [
    {
      "skill": "Fivetran",
      "level": "hands_on",
      "target_roles": ["<role_id>"],
      "proof_bullets": [
        "Built and maintained Fivetran connectors to ingest Salesforce and HubSpot data into Snowflake."
      ]
    }
  ]
}'
```

Suggest patches (deterministic, no Claude):
```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/suggest-patches -H "Content-Type: application/json" -d '{
  "jd_text": "...",
  "strict_mode": true,
  "apply_overrides": true,
  "truth_mode": "strict"
}'
```

Blocked plan (show only blocked skills + remediation template):
```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/blocked-plan -H "Content-Type: application/json" -d '{
  "jd_text": "...",
  "truth_mode": "strict",
  "top_n": 10
}'
```

Add overrides from blocked items:
```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/overrides/from-blocked -H "Content-Type: application/json" -d '{
  "items": [
    {
      "skill": "Fivetran",
      "level": "worked_with",
      "role_id": "<role_id>",
      "proof_bullet": "Used Fivetran to support data ingestion and transformation workflows, improving consistency and reliability."
    }
  ]
}'
```

Apply patches in one batch:
```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/apply-patches -H "Content-Type: application/json" -d '{
  "patches": [
    {
      "role_id": "<role_id>",
      "section": "experience",
      "action": "insert",
      "after_index": 2,
      "new_bullet": "Built and maintained Fivetran connectors to ingest Salesforce and HubSpot data into Snowflake."
    }
  ],
  "export_docx": true,
  "truth_mode": "strict"
}'
```

## Rewrite a bullet with Claude (optional)

This does NOT apply the change automatically. It returns a suggested rewrite you can review and then save via PATCH /resumes/{resume_id}/bullet.

```
curl -X POST http://127.0.0.1:8000/resumes/<resume_id>/rewrite-bullet -H "Content-Type: application/json" -d '{
  "role_selector": { "role_id": "<role_id>" },
  "bullet_index": 2,
  "jd_text": "..."
}'
```
