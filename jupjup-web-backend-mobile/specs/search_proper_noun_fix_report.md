# Korean proper noun search regression

Base: `e82b1bf`. Backend only; all execution used offline dependencies, mock/recorded
providers, and SQLite in memory. No frontend, real database, or network access.

Kiwi 0.21.0 emits `발로` for standalone `발로란트` and `텍스` for standalone
`텍스쳐`, while document context such as `발로란트 공략` or `텍스쳐 소스`
retains the complete noun. Query understanding previously populated `original_terms`
only from morphology, so BM25 retrieval and lexical relevance lost the exact term.
Recognizing the full term also needs to clear the query's low-signal classification.

The fix is confined to `QueryUnderstander.parse`: append deduplicated normalized
whitespace-delimited residual words to `original_terms`, alongside morphology.
Require a keyword substring and, when available, exact local vocabulary evidence.
This limits expansion to indexed forms of extracted keywords rather than introducing
unrelated predicates/function words. Remove time/facet/stop spans first and exclude
purpose markers and purpose forms (including particles). Use the combined originals
for the existing known-vocabulary signal check. Existing retrieval and relevance
consumers already use `original_terms`; no index, schema, tokenizer, correction,
public keyword, or semantic-query changes are needed.

Tests cover standalone normalized/social-prefixed terms, deduplication, purpose/time/
platform/type preservation, vocabulary guards, and all four term × saved-tags/body
combinations through real Kiwi, BM25, relevance, and the search service. The four
integration cases and two standalone parser cases fail against the base parser and
pass with this fix. Integration assertions verify exact BM25 matched terms, full
field-weighted key coverage, lexical evidence, normal signal, and returned documents.

Four existing queries now retain complete indexed words: `q_0023` (글램핑장),
`q_0032` (휘낭시에), `q_0036` (집들이), and `q_0044` (물주기).
Only their eight mock/recorded response hashes were refreshed; all other golden and
challenge response hashes remain identical. Recorded cross-reranker replay passes
without new recordings. Existing relevance/ranking assertions remain unchanged.

Validation:

```sh
UV_OFFLINE=1 uv run pytest tests/unit/test_text.py tests/unit/test_understanding.py tests/unit/test_facets_intent.py tests/unit/test_temporal.py tests/unit/test_bm25f.py tests/unit/test_relevance.py tests/unit/test_cross_rerank.py tests/integration/test_search_v0.py tests/integration/test_api_search.py tests/integration/test_demo_trace.py tests/eval/test_golden_regression.py tests/eval/test_recorded_regression.py
UV_OFFLINE=1 uv run ruff check src tests
UV_OFFLINE=1 uv run mypy
git diff --check
```

Result: **524 passed**; ruff clean; mypy clean across 118 source files; diff clean.
Pytest reports one existing Starlette/httpx deprecation warning.
