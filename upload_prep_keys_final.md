# Upload Preparation: Credential Verification Final

Date: 2026-09-07

Both previously unverified credentials were tested against their real provider APIs using the values loaded from the local `.env`. Secrets and response contents were not printed or written to disk.

## Gemini

- API operation: `models.embed_content`
- Model: `gemini-embedding-2`
- Test input: a minimal credential-verification sentence
- Result: **PASS**
- Returned vector length: `768`
- Vector validation: first value is numeric and all 768 values are finite

This confirms the Gemini key is authenticated and functional for the embedding operation used by the project.

## LangSearch

- API operation: `POST https://api.langsearch.com/v1/web-search`
- Test query: `Python official documentation`
- Requested result count: `3`
- Result: **PASS**
- HTTP status: `200`
- Returned populated result records: `3`
- Result validation: first result included a title and URL

This confirms the LangSearch key is authenticated and functional for live web search.

## Final Credential Status

- `GEMINI_API_KEY`: non-compromised value and live functional embedding verified.
- `GROQ_API_KEY`: non-compromised value and live functional agent smoke test verified previously.
- `LANGSEARCH_API_KEY`: non-compromised value and live functional search verified.
- No key values are included in this report.
- `.env` remains ignored and is absent from Git tracking.

Day 1 credential verification is complete. Day 2 README and packaging work can begin.
