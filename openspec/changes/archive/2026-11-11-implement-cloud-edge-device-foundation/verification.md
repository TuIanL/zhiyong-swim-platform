# Independent Verification — Cloud Edge Registry

## Verification record

- Repository: `TuIanL/zhiyong-swim-platform`
- Pull request: [#4](https://github.com/TuIanL/zhiyong-swim-platform/pull/4), remains Draft
- Fixed Apply head under review: `5b3dcec45628697f7401d45df3da4e0d05ff79db`
- Change: `implement-cloud-edge-device-foundation`
- Apply tasks recorded: 14/14
- Verification date: 2026-11-11 (Asia/Shanghai)
- Scope: independent review only. No business code, schema, migration, OpenAPI, main spec, or task checkboxes were changed.

## Verdict

**CRITICAL: 0 · WARNING: 3 · SUGGESTION: 5**

The fixed head has passing SQLite and PostgreSQL CI evidence, and the OpenSpec/packaging design is substantially implemented. Three WARNING findings remain: manager routes lock a Node before checking its tenant/site, `observed_at_raw` is stripped despite its raw-value contract, and there is no PostgreSQL test for explicit credential-revoke racing with heartbeat. The first two are implementation/contract defects; the third is a required concurrency-evidence gap.

- Merge blocking: **Yes**, until W1 and W2 are fixed and W3 has direct independent-connection PostgreSQL evidence.
- Ready to Archive: **No**.
- Targeted repair needed: **Yes**, limited to the three findings above and their tests/docs as appropriate.
- Ready to start the next business Change: **No**; close this Change's verification findings and obtain its separate completion decision first.
- Apply task state: unchanged at 14/14. This report does not convert Apply completion into Verify acceptance.

## Evidence bound to the fixed head

### GitHub Actions

The latest relevant workflow run is [run 42824584794](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42824584794), whose run metadata records `head_sha=5b3dcec45628697f7401d45df3da4e0d05ff79db`. GitHub's pull-request workflow checked out the synthetic merge result `53481543f7965c8d533e0091fd25148383294390` (the fixed PR head merged with unchanged `main` at `d7f1eedb13ac0f44abb738bc6e8b4d0d38d7766d`). Thus these are final-head PR checks, not results copied from an intermediate Apply commit.

| Job | Raw result | Notes |
| --- | --- | --- |
| SQLite (`129858447042`) | 121 passed, 49 skipped, 0 failed; 34 warnings | The 49 skips are PostgreSQL-only cases. Warnings: 33 SQLAlchemy SQLite datetime-adapter deprecations and one AnyIO/Starlette `BlockingPortal` deprecation. |
| PostgreSQL 17 (`129858446536`) | 169 passed, 1 skipped, 0 failed; 1 pytest warning | Ledger: shared=120, PostgreSQL-only=49. The one skip is SQLite-only. |

The PostgreSQL run used harness run id `6be03c34ffff756b`; the harness reported `result=passed`, primary cleanup `removed`, and CI fallback cleanup `absent` with `exit_code=0`. The uploaded [PostgreSQL evidence artifact](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42824584794/artifacts/13769545088) is artifact `13769545088`, digest `sha256:4e74362bf306085c6c0d78f34acec4e9cad7219c33cfbca1dd42e9ecd8467134`.

The PostgreSQL tests establish independent backend connections for same-key Node/Device/Credential creation and disable/issue/heartbeat races by observing distinct `pg_backend_pid()` values. They also cover failed disable/revoke transaction rollback, but do not cover the separate manual credential-revoke endpoint racing with heartbeat (W3).

### OpenSpec, source, and packaging checks

- `openspec validate implement-cloud-edge-device-foundation --strict --json`: passed, 1/1 Change, 0 issues.
- `openspec validate --specs --strict --json`: passed, `cloud-identity` 1/1, 0 issues.
- `git diff --check main...HEAD`: passed at the fixed Apply head.
- Markdown relative-link check across the Change, contracts, and verification documents: 14 Markdown files, 77 relative links checked, 0 missing targets; report code-path references: 19 checked, 0 missing.
- The original six-table revision `20261106_0001_cloud_identity.py` is byte-identical to the version on `main`.
- PostgreSQL harness validates container name, full container ID, owner/run labels, running status, loopback binding, and actual `5432/tcp` host-port mapping before psycopg connection or database creation. `pytest_configure` performs this check before collection.
- Cleanup guards distinguish an explicitly absent Docker object from daemon/permission/other errors, verify deletion, reject mismatched labels, and return nonzero for unconfirmed cleanup. Final CI reports removed/absent and exit 0.
- Packaging configuration includes migration resources; startup does not auto-migrate; `init-db` is constrained to the local `var/` SQLite target. The Apply report records a successful isolated wheel installation. I could not independently reproduce a wheel build in this verification sandbox: setuptools is not installed, and the isolated build could not download the build dependency because network DNS is unavailable. This is a verification limitation, not a claim of a packaging failure; the recorded Apply evidence was reviewed but not independently recreated here.

## Apply task evidence crosswalk

| Task | Evidence reviewed | Result |
| --- | --- | --- |
| 0.1 Authorization and scope | Owner authorization in the Change history; D11–D13 and scope in `proposal.md`, `design.md`, and `tasks.md`. | Complete as an authorization gate; not a technical test. |
| 1.1 Four-table model and constraints | `services/cloud/src/swimplatform/models.py`; schema/constraint tests; composite tenant/site/node foreign keys, checks, unique constraints, and `RESTRICT`; camera-only kind with generic Device identity. | Evidence present. No Cart entity/control was introduced. |
| 1.2 Migration and installation | Incremental migration under `services/cloud/src/swimplatform/migrations/versions/`; migration round-trip/reflection and rollback tests; initial migration byte comparison; `pyproject.toml`, startup, and CLI review. | Evidence present, with independent wheel reproduction limitation above. |
| 1.3 Isolated PostgreSQL harness and least privilege | `scripts/test-postgresql.py`, `services/cloud/tests/pg_support.py`, `conftest.py`, `test_pg_harness_guard.py`; connection-before-validation guard; dedicated schema and approved ten-table grants. | Evidence present; final CI cleanup succeeded. |
| 2.1 User APIs and authorization | `services/cloud/src/swimplatform/edge_registry.py`, `docs/contracts/cloud-edge-registry.md`, `docs/contracts/openapi.json`, `test_edge_registry_api.py`. | Core operations and role checks exist; cross-tenant lock ordering is W1, and endpoint-by-role test coverage is not exhaustive (S4). |
| 2.2 Durable idempotency | `IdempotencyRecord` model and registry transaction code; API and PostgreSQL concurrent same-key tests, restart/retry, conflict, and reauthorization checks. | Evidence present. Permanent retention/deletion interaction is S1; polymorphic resource reference is S2. |
| 3.1 Credential lifecycle and identity separation | Credential model/API, SHA-256 token digest, one-time issue response, log/database/idempotency assertions, expiry tests, and user-token/edge-token rejection tests. | Evidence present for default 7 days, 30-day maximum, UTC deadline, irreversible revoke, and separate identities. |
| 3.2 Administrative lifecycle and transactions | `update_edge_node`, issue/revoke code; PostgreSQL disable/issue/heartbeat and rollback tests using independent connections. | Disable/issue/heartbeat and rollback evidence present. Explicit revoke/heartbeat race lacks direct test (W3). |
| 4.1 Heartbeat contract | Heartbeat route/schema and `test_edge_registry_api.py`; 30-second interval, 90-second boundary, server-received timestamp, bounded health data and no administrative state mutation. | Evidence present except the raw-field whitespace mismatch W2. |
| 4.2 Time, offline, and retry boundaries | UTC and Asia/Shanghai PostgreSQL expiry tests, 35-day old-token rejection, online boundary and bounded retry behavior. | Evidence present; no automatic renewal or offline recovery is implemented, as scoped. |
| 5.1 Full dual-backend validation | Fixed-head GitHub run 42824584794 and raw job logs/artifact above. | Both complete backend suites passed; task file's earlier run reference is superseded for this Verify by the exact-head run above. |
| 5.2 Wheel and runtime boundary | Apply report wheel SHA/install evidence; packaging config, migration package discovery, startup and `init-db` reviewed. | Source/config review agrees; independent wheel reproduction was unavailable in this sandbox. |
| 5.3 Cross-artifact consistency and strict checks | Proposal, Design, Spec Delta, Tasks, OpenAPI, formal Edge Registry contract, test suite, strict validators and diff check. | Mostly aligned; `observed_at_raw` mismatch is W2; machine-readable error coverage is S3. |
| 5.4 Project/document synchronization | PR #4 and Notion engineering entry contain Apply evidence. This Verify report is appended there without changing task status. | Apply state retained; Verify findings recorded separately. |

## Requirement and decision traceability

The Change task traceability table has eight Registry verification rows when its separately tracked “Credential lifecycle audit boundary” scenario is counted with the seven top-level Registry requirements. It also tracks two database-validation requirements. All ten trace rows were checked against implementation, tests, or documented boundaries:

| Requirement / acceptance row | Implementation and evidence | Result |
| --- | --- | --- |
| Tenant scoped registry management | Twelve user operations in `edge_registry.py`, OpenAPI and API tests; manager roles and anonymous/non-member/coach/athlete cases. | Implemented; W1 exposes a foreign-row lock before scope rejection. OpenAPI error-response detail is S3. |
| Immutable device provenance | Four added tables, composite foreign keys, no delete/relocation API, `Device.kind` restricted to `camera`; tests cover mismatched parents and independent identity. | Implemented and tested. Camera identity is distinct from physical cart or pool-fixed placement. |
| Independent revocable Edge credentials | `Authorization: Bearer swim_edge_...`; Edge authentication resolves only its Node and is separate from User auth. | Implemented and tested for token non-interchangeability. |
| Bounded credential lifecycle | `token_urlsafe(32)` secret generation, SHA-256 digest persistence, one-time response, 7-day default/30-day cap, UTC expiry and irreversible revoke. | Implemented and tested, including UTC/Asia deadlines and 35-day re-connect returning 401. |
| Credential lifecycle audit boundary | Issuer/revoker user IDs and server times retained with `RESTRICT`; no general audit-event system or secret/hash in ordinary read/log/idempotency output. | Implemented and tested/documented. |
| Administrative Node lifecycle | Pending/active/disabled transitions, generation invalidation, atomic disable/revoke and rollback test. | Implemented; explicit revoke-vs-heartbeat concurrency test remains W3. |
| Bounded heartbeat observations | Server UTC `last_seen_at`, active and `<90s` online rule, 30-second cadence response, bounded health input, no SLA interpretation or admin status mutation. | Implemented; raw observation preservation has W2. |
| Durable request idempotency | Scoped unique key/hash records in same transaction; same-key independent-connection concurrency, retry, conflict and secret replay prevention. | Implemented. Permanent retention/privacy and soft polymorphic resource reference are S1/S2. |
| Isolated database validation | Dedicated `swim_cloud` schema, migration/app identity separation, app grants for ten approved tables, no DDL or role escalation. | Implemented and exercised by fixed-head PostgreSQL CI. |
| PostgreSQL schema integrity | Reflection/round-trip, restrictive/composite constraints, initial six-table migration unchanged, transaction rollback. | Implemented and exercised by fixed-head PostgreSQL CI. |

### D11 — Camera-first

`Device.kind` accepts `camera` only, with a generic Device identity and future kind extension point. No Cart table, motor, tracking, or safety-control protocol was added. The contract correctly distinguishes a camera installed on and moving with a cart from a camera fixed at a pool position. The model does not enforce a one-to-one cart relation, matching the approved decision to keep that physical deployment statement out of the Device identity model.

### D12 — EdgeCredential lifecycle

The implementation uses 32 bytes of cryptographic random material, stores a SHA-256 digest, returns the clear token only from successful issuance, excludes it from ordinary reads/logs/idempotency, and applies a server UTC default of seven days with a thirty-day maximum. Deadline equality is rejected. Revoke is irreversible; Node disable increments generation and revokes credentials transactionally. A credential older than 35 days is rejected; a controlled reissue/update is required. No renewal, unlimited offline extension, identity recovery protocol, or automatic rotation service exists.

### D13 — Heartbeat

Responses advertise the 30-second default interval and 90-second online window. Online requires an active Node and age in `[0, 90s)`, based on server receipt time. Client time is an observation only; bounded health input, retry simulation, and failure-without-administrative-state-change have coverage. The raw text preservation mismatch is W2. The 90-second window is not presented as an SLA.

## Findings

### CRITICAL

None.

### WARNING

#### W1 — Manager routes acquire a cross-tenant Node row lock before checking scope

- **Files / locations:** `services/cloud/src/swimplatform/edge_registry.py:119-131`, `:307-315`, `:382-389`, `:426-444`.
- **Reproduction:** A valid Owner/Admin for Tenant/Site A supplies the UUID of a known Node in Tenant/Site B to the Node PATCH, credential-issue, or credential-revoke route under Site A. `require_manager_site` succeeds for A. `lock_node` selects by `EdgeNode.id` alone and obtains `FOR UPDATE` on PostgreSQL; only after that does each route compare `tenant_id`/`site_id` and return 404.
- **Evidence:** `lock_node` has no tenant/site predicate at lines 119-120. The route order is explicit at 312-315, 386-389 and 430-433. The lock therefore targets the foreign row before the 404. Existing tests do not assert that a rejected foreign Node request avoids taking that lock.
- **Impact:** No foreign Node data is returned and the rejected request makes no intended persistent change. A manager with a known foreign Node UUID can nevertheless create lock contention against that tenant's lifecycle operations, and response/lock timing can act as a limited resource-existence/busy-state probe. Repeated requests can turn the contention into an availability risk. UUID unpredictability reduces blind discovery but does not remove the issue when an ID is known.
- **Recommendation:** Add a manager-scoped lock query that predicates on `id`, `tenant_id`, and `site_id` before locking; return the same 404 when no scoped row exists. Keep Edge-token authentication's Node lock scoped by the credential's own assigned Node. Add PostgreSQL tests that hold the foreign row lock, submit each affected foreign-ID route, and prove the request rejects without waiting on/locking that row or causing a mutation.
- **Disposition:** Merge/Archive blocking until fixed and tested.

#### W2 — `observed_at_raw` is whitespace-normalized despite its raw-value contract

- **Files / locations:** `services/cloud/src/swimplatform/schemas.py:10-11`, `:238-241`; contract `docs/contracts/cloud-edge-registry.md:39`; design `openspec/changes/implement-cloud-edge-device-foundation/design.md:79`.
- **Reproduction:** Instantiate `HeartbeatRequest(observed_at_raw="  device-clock raw  ")`; Pydantic returns `"device-clock raw"` because `HeartbeatRequest` inherits `Input` with `str_strip_whitespace=True`.
- **Evidence:** Runtime check of the schema produced the stripped value. The contract says “原样observed_at_raw” and Design says “保留原始不确定时间”. Existing heartbeat tests use a value without leading/trailing whitespace (`test_edge_registry_api.py:193-198`) and do not detect the loss.
- **Impact:** The value is explicitly diagnostic and not authoritative, but its original device-clock text cannot be faithfully preserved. That violates the accepted field semantics and can erase meaningful source formatting when investigating clock behavior.
- **Recommendation:** Override whitespace handling for this field (without weakening normalization for other inputs), then add a round-trip API/storage test with leading and trailing whitespace and verify exact preservation.
- **Disposition:** Merge/Archive blocking until implementation, contract, and test agree.

#### W3 — Explicit credential revoke racing with heartbeat lacks independent-connection PostgreSQL evidence

- **Files / locations:** `services/cloud/tests/test_edge_registry_transactions.py:134-174`, `:176-215`; sequential revoke coverage at `services/cloud/tests/test_edge_registry_api.py:211-220`; implementation at `services/cloud/src/swimplatform/edge_registry.py:233-258`, `:426-449`.
- **Reproduction / coverage gap:** There is no test that starts the explicit `DELETE /.../credentials/{credential_id}` operation concurrently with `/api/v1/edge/heartbeat` using distinct PostgreSQL backend PIDs. The existing disable/issue/heartbeat race exercises the automatic revoke performed by Node disable, while the manual credential DELETE test is sequential.
- **Evidence:** Transaction tests cover independent-connection same-key create, credential issue, disable/issue/heartbeat and rollback, but have no manual-revoke/heartbeat race case. The revoke route locks Node then Credential; heartbeat authenticates and locks the same Node then Credential, so code inspection suggests serialization, but this is not direct evidence for the required operation pair.
- **Impact:** The accepted transaction/concurrency behavior for the public revoke operation is not independently demonstrated. A lock-order regression or unexpected response/last_seen outcome could pass current CI.
- **Recommendation:** Add a PostgreSQL-only controlled race with `pool_size=8`, assert distinct `pg_backend_pid()` values, and validate both legal serial orders. After revoke commits, a heartbeat using that credential must return 401 and must not alter `last_seen_at`; first revoker/time must remain stable. Include the case in the required PostgreSQL collection ledger and rerun both full suites.
- **Disposition:** Merge/Archive blocking as an acceptance-evidence gap.

### SUGGESTION

#### S1 — Permanent idempotency records need a future retention/privacy decision

- **Files / locations:** `services/cloud/src/swimplatform/models.py:212-246`; `design.md:36` and `:71`.
- **Evidence:** The design intentionally retains idempotency records indefinitely; site and user references use `RESTRICT`, and rows retain tenant/site/user IDs, target/resource IDs, and hashes. This Change introduces no deletion operation, so no current route triggers the conflict.
- **Impact:** Future account, site, or tenant removal can be blocked by historical rows; retention of stable identifiers and hashes needs an explicit privacy/data-retention basis before production deletion or erasure workflows are designed.
- **Recommendation:** Record retention, purge/anonymization, and referential-integrity behavior as part of the future deletion/privacy design. Do not weaken the current history guarantee as part of this Verify.

#### S2 — `resource_id` is a deliberate soft reference, not a foreign key

- **Files / locations:** `services/cloud/src/swimplatform/models.py:230-245`; `design.md:36`.
- **Evidence:** `resource_kind` and `resource_id` are stored as a polymorphic pair and indexed; service code resolves the resource in the write transaction. The database cannot enforce a target FK across Node, Device, and Credential tables.
- **Impact:** If a future deletion path is added, a retained idempotency row can point to a removed resource and retries will resolve as `registry_conflict`; DB integrity alone cannot prevent or clean that orphan.
- **Recommendation:** Keep deletion/tombstone/purge ordering explicit in the later deletion design and test retries after any permitted deletion. This is consistent with the current no-delete scope.

#### S3 — OpenAPI omits machine-readable custom error responses

- **Files / locations:** `docs/contracts/openapi.json`; error semantics in `docs/contracts/cloud-edge-registry.md:46-52`.
- **Evidence:** The 12 new operations are present, but operation response objects generally declare success and 422 only, while the contract describes 401/403/404/409 custom errors.
- **Impact:** Generated clients and API tooling cannot discover all documented authorization and conflict outcomes from the OpenAPI document alone.
- **Recommendation:** In a separately authorized contract update, add reusable error schemas and the applicable 401/403/404/409 responses per operation. This is not a mismatch in the runtime behavior reviewed here.

#### S4 — Permission tests do not form a complete endpoint-by-role matrix

- **Files / locations:** `services/cloud/tests/test_edge_registry_api.py:53-69` and the rest of the API test module.
- **Evidence:** Role checks cover representative Node listing/detail, anonymous creation, manager paths, and selected revoke behavior; the fixture does not provide a second valid tenant with a foreign Node to test every operation's cross-tenant rejection path.
- **Impact:** Shared authorization helpers reduce code risk, but a future endpoint wired to the wrong dependency or scope could escape current role-specific regression coverage.
- **Recommendation:** Add parameterized coverage for all twelve operations across Owner/Admin, Coach, Athlete, anonymous, non-member, wrong-Site, and foreign-Tenant callers after W1's scoped locking fix.

#### S5 — CI has dependency/runtime deprecation warnings

- **Files / locations:** fixed-head run 42824584794, SQLite and PostgreSQL job logs.
- **Evidence:** SQLite reports 33 SQLAlchemy default SQLite datetime-adapter deprecations and one AnyIO/Starlette `BlockingPortal` deprecation. The workflow also reports Node.js 20 action-runtime and punycode deprecations.
- **Impact:** These warnings do not fail the current suites, but dependency/runtime upgrades may change behavior or eventually make the checks noisy or incompatible.
- **Recommendation:** Plan an explicit SQLite datetime adapter policy and update affected dependencies/actions before their supported runtimes are removed. No migration or CI change is made in this Verify.

## Scope and artifact consistency

- Proposal, Design, Spec Delta, Tasks, API contract, OpenAPI paths, and implementation consistently describe the 12 operations, additive four-table scope, D11–D13, the existing six-table baseline, and deferred product capabilities.
- The 12 operation paths are represented in OpenAPI. Custom error responses are less complete in the machine-readable document (S3).
- D11 camera-first behavior is implemented without Cart or motion-control scope expansion.
- D12 secret handling, UTC expiry, 7/30-day bounds, irreversible revocation, and 35-day offline limitation align across design, code, tests, and contract.
- D13 30/90-second behavior and server receipt-time authority align, except the `observed_at_raw` raw-value discrepancy (W2).
- The four new tables and incremental migration preserve the original six tables and initial revision; model/migration reflection and PostgreSQL constraints are tested.
- PostgreSQL application access is limited to the approved ten business tables' required DML plus the intended version-table read; schema ownership, DDL, and privilege escalation are rejected by tests.

## Final independent Verify decision

The exact fixed head is green in both CI backends and passes strict OpenSpec validation. This does **not** meet the project's acceptance bar while W1 and W2 remain and W3 lacks required concurrency evidence. The Change is **not ready to merge or Archive** and requires a focused repair followed by a new independent Verify authorization. This report records Verify findings only; no Archive, main-spec sync, task-state change, PR readiness transition, merge, or next Change was performed.
