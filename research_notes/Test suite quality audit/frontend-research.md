# Frontend and browser test resilience

## Which frontend assertions survive implementation changes?

### Takeaway
Test an interaction through a component's public props and accessible DOM, then assert the outcome its user cares about. State shape, hook names, CSS classes and child component boundaries are usually weaker contracts.

### Cited Findings
- Testing Library favors DOM nodes over component instances and tests that resemble actual use. This is a testing philosophy rather than an empirical performance guarantee. — [Testing Library guiding principles](https://testing-library.com/docs/guiding-principles/)
- The query priority is role with accessible name, then labels for form inputs; test IDs are a fallback where semantic queries are unsuitable. Async findBy queries retry, while getBy and queryBy do not. A deliberate test ID offers a clearer contract than a CSS class/id invisible to users. — [Testing Library queries](https://testing-library.com/docs/queries/about/)
- Kent C. Dodds' accordion example illustrates two defects in implementation tests: changing state representation breaks a passing product's tests; breaking the click-handler wiring leaves direct state-method tests green. One click-and-observe test handles both cases. Public props and rendered output serve the developer and end user, respectively. — [Testing Implementation Details](https://kentcdodds.com/blog/testing-implementation-details)
- user-event simulates interactions, including multiple events and interactability checks. fireEvent dispatches a particular event. Unsupported interactions may still require fireEvent, but this introduces assumptions about the real browser event sequence. — [Testing Library user-event introduction](https://testing-library.com/docs/user-event/intro/)

### Inferences
- Audit criterion: renaming an internal hook, extracting a child component or changing an array to a map should leave tests passing when behavior is unchanged. A reusable public hook may deserve direct tests; private page coordination usually needs a user-level oracle.
- Proposed listing-editor example: render a listing, fill its Title label, invoke Save and assert the saved title after reload or through the persistence adapter. An assertion that setDraft received an object may miss disconnected Save wiring.
- Proposed media-reel example: choose a named picture, move it, assert the resulting ordered media names. Test reorder permutations through a pure function and retain one DOM test showing the controls invoke the rule.
- Public callbacks are legitimate assertion surfaces when they are documented component outputs. The issue is private collaboration, not mocks in general.

### Gaps
- These sources supply author guidance and examples, not universal estimates of runtime or resilience improvement.
- The examples above are proposed audit patterns, not claims that these repository behaviors currently fail.

## What belongs in the browser, and what can move down the stack?

### Takeaway
Keep real layout, resource decoding and the built frontend/backend seam in the browser. Move independent business rules and backend validation matrices to the lowest stable interface, preserving focused wiring tests.

### Cited Findings
- jsdom does not perform layout or visual rendering, even with pretendToBeVisual. That setting alters visibility hints and animation-frame availability. Images are not loaded by default. — [jsdom README](https://github.com/jsdom/jsdom#pretending-to-be-a-visual-browser)
- Vitest explains that simulated DOM environments can diverge from real browsers. Browser Mode provides native execution but has longer initialization and does not completely replace a standalone end-to-end runner. — [Vitest: why Browser Mode](https://vitest.dev/guide/browser/why)
- Playwright recommends user-visible behavior, isolation, semantic attributes or explicit test contracts, and retrying web assertions rather than an immediate boolean extracted from isVisible. — [Playwright best practices](https://playwright.dev/docs/best-practices)

### Inferences
- Browser keeper: drag calibration handles, obtain a PNG from FastAPI, confirm browser decoding at its actual dimensions, save and inspect persisted template. Browser geometry, HTTP, real rendering and persistence are genuine combined seams.
- Browser keeper: create a listing in the built SPA, edit, wait for autosave, reload and observe persisted values. Test malformed payload matrices directly through application/API interfaces rather than repeating this journey for every case.
- Move down: gallery caps, swatch gating, reordering permutations, placement transforms and selection/focus rules suit pure stable-function tests. Retain component wiring and a real-browser interaction/resource smoke test.
- A jsdom test stubbing geometry, pointer capture and ResizeObserver and manually firing events cannot prove genuine dragging works. Extensive shims signal either a direct transformation test or thin real-browser test may be better.
- A multi-component DOM test is an integration test even if its directory says unit. Classify by dependencies, not filename labels.

### Gaps
- Runner initialization cost is documented but actual net savings here require measurement. A runner migration is not automatically the most valuable action.
- No rule says all filesystem assertions need browser coverage; identify the extra seam before retaining duplicate journey matrices.

## How should waits, timer behavior and snapshots be audited?

### Takeaway
Await meaningful state changes, control time when time is the subject and reserve snapshots for focused, reviewed contracts.

### Cited Findings
- Playwright discourages production-test waitForTimeout because elapsed-time waits are flaky. Locator actions and web assertions wait automatically; meaningful network events or visibility signals are preferable. — [Playwright Page.waitForTimeout](https://playwright.dev/docs/api/class-page#page-wait-for-timeout)
- Testing Library recommends fake timers where timers make tests slow, flaky or unpredictable. Restore real timers and flush pending work to avoid leakage. — [Testing Library fake timers](https://testing-library.com/docs/using-fake-timers/)
- With fake timers, configure userEvent.setup's advanceTimers option with the runner advancement function. Setting delay to null as a workaround is discouraged. — [Testing Library user-event options](https://testing-library.com/docs/user-event/options/)
- Jest requires short, focused, deterministic snapshots reviewed as code. Blind regeneration can record defects. Serialized DOM snapshots and visual pixel comparisons serve different purposes; snapshots supplement focused assertions. — [Jest snapshot testing](https://jestjs.io/docs/snapshot-testing)

### Inferences
- Proposed autosave test: control time to prove edits coalesce before the documented debounce and persist the latest title afterwards. Keep one browser test awaiting a saved state; avoid repeating real debounce delays for validation permutations.
- Replace sleeps after Save with its response and the final saved state. A network response alone may precede React's rendered outcome.
- Wait for action completion before asserting an item is absent. Absence while loading can be a false passing result.
- Broad innerHTML snapshots lock classes, wrappers and generated IDs. Prefer named behavior assertions unless exact serialization is the product contract. Small deterministic error/API snapshots may remain valuable.
- Render goldens are not automatically low-value snapshots: image bytes/per-pass output can be a deliberate contract. Apply the same independent-oracle and review requirements without treating them like broad DOM snapshots.

### Gaps
- Sources cannot establish which existing tests are slow or flaky; use actual durations before reporting empirical impact.
- Fake timers do not control network work, Python threads or promise completion; those need observable event seams.
