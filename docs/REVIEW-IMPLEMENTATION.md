# Review implementation and release evidence

Baseline: `082f35c5df0522c25889a60d83b31d291e9e5476`. Work is tracked by issue #1 and PR #15; the PR records merge status and the exact verified revision.

## Implementation map

| Issue | Change | Verification |
|---|---|---|
| #2 | Resolve known child names locally; reject conflicts/duplicate names; name the selected child in responses; bind confirmation to child | Unit child-name isolation and actual PostgreSQL cross-child confirmation regression |
| #3 | Encrypted per-user/family/child clarification context, 30-minute expiry, bounded merge; ask for missing time/date | Deterministic round trip and PostgreSQL propose/confirm/repeat regression |
| #4 | Notification daily quota scoped to kind | PostgreSQL sends check-in and summary with both limits set to one |
| #5 | Explicit HTTP 429 → bounded retry honoring retry_after, retain response until retry; transport timeout remains uncertain | HTTP sender unit tests and PostgreSQL outbox retry regression |
| #6 | Natural-language previews capped by UTF-16 units; 20-item batch fits one Telegram message; inline confirm/cancel buttons | Worst-case Unicode batch unit test; callback identity/action validation |
| #7 | Production creator allowlist, admitted AI families, rolling request limits, global pause and inbound backpressure | Default-deny unit test and concurrent PostgreSQL global reservation test |
| #8 | Decode/validate inside per-job exception boundary | Corrupt row followed by valid row in PostgreSQL; provider never invoked on corrupt input |
| #9 | Stable oldest-message order per user plus session advisory lock across commits/network calls | PostgreSQL locked-user/two-worker selection-before-record regression |
| #10 | Family-scoped keyed lookup tokens for diaper categories and LIMIT 1 lookup | 50k newer pee rows + older poop fixture; EXPLAIN must use events_lookup |
| #11 | Period query tools, numbered candidates, versioned edit/delete proposals, reminder create/list/cancel and notification settings with confirmation, source-free natural renderer, Mini App reminder/delivery controls | Tool validation, PostgreSQL range/edit/idempotency tests; browser suite covers selected flows |
| #12 | Permission ID 202611419 recorded; metadata-only public manifest; protected server loader, checksum validation and deterministic LMS; raw trends and comparison status | CI verifies every official SD column across ten workbook assets, then tests loader and selected boundary cases; production comparison requires the generated code/data-bound validation cache |
| #13 | Local bounded source registry; WHO topics/results never sent to external classifier; unsupported clinical queries refused | Static-response injection/refusal unit tests; full clinical/language review is still outstanding |
| #14 | PostgreSQL CI, Docker build/Compose parse, browser mobile/desktop acceptance, container recreate/DB restore suite; heartbeat and content-free metrics | CI is authoritative; live Telegram/provider, public TLS and clinical acceptance remain separate operational gates |

## Evidence and limitations

CI at `82e6c5f` ([run 41484316920](https://github.com/zckyachmd/ruang-tumbuh/actions/runs/41484316920)) passed **90 tests** with PostgreSQL 16, including the 50k lookup/index regression and encrypted private-button revocation checks. Browser acceptance passed at **390px and 1280px**, including two members with different active child profiles and session expiry/re-login. Docker image build and production Compose parsing passed. Container recreate retained data, and the actual `scripts/backup-postgres.sh` round trip passed with `age` ciphertext mode `0600` and restore to an isolated PostgreSQL database.

The WHO job passed **94,864 numerical and loader/boundary checks** across ten checksum-pinned official workbooks. Assets were installed only in the temporary server runner directory and removed after verification; none were published as logs/artifacts. Production activation requires installing the protected assets and regenerating their code/data-bound validation cache; the numerical suite does not authorize clinical claims.

A follow-up regression unifies the deterministic provider's negation routing with the worker safety policy. The PR check summary records the exact test count for subsequent heads.
The final synthetic language evaluation contains 40 cases covering current signs, negation, history, educational questions and mixed clauses. Compared with the pre-change router, emergency false positives in this set decreased from 12 to 0; both versions had 0 emergency false negatives in this set. All 40 current routing expectations pass. These are engineering-authored expectations, not clinical ground truth or an estimate of real-world sensitivity/specificity. CI prints the evaluation on each run; qualified clinical review remains pending. Known profile names of one or two characters are also redacted before external classification, without replacing substrings inside other words.
The source runner could not install PostgreSQL or dependencies because its package access was restricted. Actual database/build verification therefore runs on GitHub Actions, not a mock database. The Docker smoke test verifies a synthetic run of the actual age backup script and restore; it does not certify production key custody, host encryption, backup scheduling, off-host retention or disaster-recovery procedures.

Permission has been granted. It does not supply live provider credentials, prove clinical correctness, or approve future commercial distribution. The private permission letter and licensed workbooks are not public artifacts.

## Operator setup

1. Set `APP_ENV=production`, `DEV_AUTH_ENABLED=0`, strong database password and a separately backed-up `APP_DATA_ENCRYPTION_KEY`.
2. Set `FAMILY_CREATOR_IDS` to the Telegram IDs allowed to create families. After provisioning, set `AI_FAMILY_IDS` for families allowed to use operator-funded AI; each member still separately consents. Existing families are not implicitly admitted to external AI on upgrade.
3. Set request budgets to the provider cost model: global/family rolling 24-hour request count, per-user rolling minute count, `max_tokens=1000` per completion. These are request caps, not currency accounting. Reservations remain consumed after failed/uncertain requests to avoid runaway retry costs. `AI_PAUSED=1` stops new model requests.
4. Use either polling or webhook, enable actual delivery separately, and configure the Mini App HTTPS URL. Configure Telegram webhook allowed updates for both `message` and `callback_query` if webhook transport is selected. Draft callbacks carry no authority beyond the authenticated user's accessible draft.
5. Run migrations before starting writers. Context and change drafts expire after 30 minutes; AI creation drafts expire after 24 hours. Confirmation is bound to user, family, child, expiry and version. Switching child requires re-selecting the original profile before confirming an old draft.
6. Read [WHO licence status](WHO-license-status.md) before installing protected reference assets. Leave comparison disabled until the deployment validation script passes; raw measurement trends work independently. The chat worker has no workbook mount.

Lookup tokens are HMAC-derived from a domain-separated data key and include the family ID. Database observers can still correlate equal diaper categories within one family; they do not receive plaintext subtype values or cross-family matching tokens. Key rotation recomputes lookup tokens in the same transaction as ciphertext rotation. Back up first and stop all writers during rotation.

## Run verification

With an isolated PostgreSQL database, install `requirements-dev.txt`, set `TEST_DATABASE_URL`, a synthetic `APP_DATA_ENCRYPTION_KEY`, and `APP_ENV=development`:

```bash
python -m unittest discover -s tests -v
python -m playwright install --with-deps chromium
python tests/ui_acceptance.py
python tests/runtime_smoke.py
```

The runtime smoke test requires `age` and creates its own Compose project and deletes only that project's synthetic volumes afterwards. It requires Docker and a free localhost port 8147. Browser tests create/drop an isolated schema and use localhost port 8137.

WHO reference checks run on a protected temporary server directory and delete assets afterwards; never upload that directory as an artifact:

```bash
python scripts/install-who-data.py /protected/who-data
python scripts/validate-who-reference.py /protected/who-data
```

Numerical success atomically writes `validation.json`, bound to the implementation and all asset checksums. It enables supported comparisons when the deployment feature flag is set; no manual approval record or new permission request is required. Clinical interpretation remains outside the implemented scope.

## Health and recovery

`docker compose exec worker python -m ruang_tumbuh.healthcheck --metrics` returns only heartbeat age, queue/outbox status counts, oldest pending age and AI reservation count. Alert on absent/stale heartbeat, growing queue age and failed/uncertain delivery. Set thresholds from measured deployment behavior; no latency SLO is asserted here.
The default container probe reads only the single worker heartbeat row. Full history counters run only with the explicit `--metrics` option, keeping the frequent liveness check independent of queue history size.
Metrics also report 24-hour provider outcomes, p95 call latency, reservations unobserved for over two minutes, actual Telegram `sent` delivery p95 lag, oldest undelivered age and token usage. Simulated sends are excluded from Telegram latency. Historical reservations remain `unknown`; a crash or metrics-write failure remains `reserved`, never inferred as success. A failed observation write logs only a fixed message and does not replay or discard a provider result. Token counts and request budgets are not monetary cost accounting. Production scraping, alert thresholds and notification routing still require operator configuration and verification.

An explicit 429 is retried up to five attempts. An unknown delivery outcome is not automatically resent. Mini App Settings shows recent personal delivery status. Inspect the record timeline before re-entering an activity whose acknowledgement was not received. A failed notification does not establish that an activity was absent or that a child is safe.

Do not close the release tracker solely on green synthetic CI: two-parent live Telegram/provider acceptance, public TLS, production backup/key recovery and any clinical claims need their own evidence. Clinical treatment, diagnosis and unrestricted medical answers are not implemented.
