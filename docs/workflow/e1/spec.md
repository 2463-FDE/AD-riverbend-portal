# E1 Spec (EARS)

> Status: AGREED — frozen contract 2026-08-06
> Source: docs/workflow/e1/requirements.md (AGREED 2026-08-06)
> Frozen by owner decision 2026-08-06. Changes only by explicit human decision, never silently
> mid-loop; the drift gate and codex review both anchor here.

## 1. Statements

### E1-REQ-1 — local test command

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-1 | The repository shall provide a single documented command that runs the entire frontend UI-component test suite locally. | |
| E1-SPEC-2 | When the documented command is run on a fresh clone after the documented dependency-install step, the frontend test suite shall run without further undocumented setup. | |
| E1-SPEC-3 | If any component test fails, then the test command shall exit non-zero and identify the failing test. | |

### E1-REQ-2 — CI test gate

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-4 | When a pull request is opened or updated, the CI pipeline shall run the frontend test suite. | |
| E1-SPEC-5 | If the frontend test suite fails, then the CI pipeline shall report an overall failure. | Merge-blocking itself is a required-checks setting on the repository host, outside this repo; the spec's observable is the red check. |

### E1-REQ-3 — CI type-check gate

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-6 | When a pull request is opened or updated, the CI pipeline shall type-check all frontend source. | |
| E1-SPEC-7 | If type-checking reports any error, then the CI pipeline shall report an overall failure. | |

### E1-REQ-4 — CI lint gate

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-8 | When a pull request is opened or updated, the CI pipeline shall lint all frontend source. | |
| E1-SPEC-9 | If linting reports any failure, then the CI pipeline shall report an overall failure. | |

### E1-REQ-5 — truthful health endpoint

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-10 | While the frontend application is serving pages, the frontend health endpoint shall answer a health request with success. | |
| E1-SPEC-11 | If the frontend application is unable to serve pages, then the frontend health endpoint shall not answer with success. | Non-success response or no response both satisfy this. |
| E1-SPEC-12 | The frontend health endpoint shall answer without an authenticated session and shall include no PHI and no secret values in its response. | Response is status-only by contract. |

### E1-REQ-6 — truthful compose health status

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-13 | While the frontend container has started but the application is not yet serving, the compose environment shall report the frontend as not healthy. | |
| E1-SPEC-14 | When the frontend application begins serving, the compose environment shall report the frontend healthy within a configured interval. | |
| E1-SPEC-15 | If the frontend application stops serving while its container keeps running, then the compose environment shall report the frontend unhealthy within a configured window. | |

### E1-REQ-7 — CI runtime boot check

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-16 | When a pull request is opened or updated, the CI pipeline shall start the frontend from the same built production image the compose environment runs. | |
| E1-SPEC-17 | If the started frontend does not answer a health request with success within a configured window, then the CI pipeline shall report an overall failure. | Closes TODO-45: a boot-broken image cannot ship green. |

### E1-REQ-8 — seed component test

| ID | Statement | Notes |
|----|-----------|-------|
| E1-SPEC-18 | The frontend test suite shall contain at least one test that renders a real UI component from the portal and asserts on its rendered output. | Proves the harness end to end, not a trivial always-pass test. |
| E1-SPEC-19 | The seed test shall not assert on the behavior of deliberately defective flows (above all the registration success path, TODO-1). | Teaching artifacts stay intact; see requirements §4. |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| E1-REQ-1 | E1-SPEC-1, E1-SPEC-2, E1-SPEC-3 |
| E1-REQ-2 | E1-SPEC-4, E1-SPEC-5 |
| E1-REQ-3 | E1-SPEC-6, E1-SPEC-7 |
| E1-REQ-4 | E1-SPEC-8, E1-SPEC-9 |
| E1-REQ-5 | E1-SPEC-10, E1-SPEC-11, E1-SPEC-12 |
| E1-REQ-6 | E1-SPEC-13, E1-SPEC-14, E1-SPEC-15 |
| E1-REQ-7 | E1-SPEC-16, E1-SPEC-17 |
| E1-REQ-8 | E1-SPEC-18, E1-SPEC-19 |
