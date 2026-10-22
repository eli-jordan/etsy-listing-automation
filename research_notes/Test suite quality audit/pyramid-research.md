# Test pyramid, durable boundaries, and moving validation down the stack

## What should the pyramid measure?

### Takeaway
Use the pyramid to favor numerous focused, fast checks and a smaller number of expensive workflows. Judge actual scope, dependencies, runtime, and unique validation rather than imposing a numerical quota or trusting a folder name.

### Cited Findings
- Mike Cohn's original calculator example moves multiplication/division case matrices out of repeated UI journeys into service tests; repeated UI cases unnecessarily exercise the same button wiring and display code. The middle layer means operations tested independently of the UI, not a requirement for service-oriented architecture. — [Mike Cohn, The Forgotten Layer of the Test Automation Pyramid](https://www.mountaingoatsoftware.com/agile/the-forgotten-layer-of-the-test-automation-pyramid).
- Martin Fowler distinguishes sociable unit tests using real collaborators from solitary tests replacing them. Some apparent disputes over the pyramid are disagreements about these labels. He emphasizes useful failures, clear boundaries, reliability, and speed over percentage debates. — [Fowler, On the Diverse And Fantastical Shapes of Testing](https://martinfowler.com/articles/2021-test-shapes.html).

### Inferences
- For this audit, count backend unit, behavior, contract, golden, browser, e2e, and frontend component tests separately; also explain their real scopes. A small tempfile test or frontend component test need not resemble a full-stack integration journey merely because it involves more than one function.
- Candidate prioritization should combine lost refactoring freedom, duplicate validation, measured runtime, and regression risk. Do not infer a test is slow solely from its layer.
- Favor the user's pyramid direction while preserving narrow integration tests that verify boundaries no pure test exercises.

### Gaps
- These sources do not supply a universal ideal ratio or application-specific runtime target. Any numerical quota would be an audit policy choice, not established evidence.

## How can tests move down without losing validation?

### Takeaway
Move repeated decision matrices into stable domain/application interfaces, then retain focused checks for each distinct HTTP, browser, filesystem, or provider boundary. Deletion is justified only after identifying equivalent lower-level protection and the absence of a unique higher-level failure mode.

### Cited Findings
- Ham Vocke recommends removing higher tests whose conditions are already covered below while retaining tests for extra confidence. His controller example distinguishes direct logic checks from HTTP checks: invoking a controller cannot prove its route responds. He recommends observable outputs over internal call choreography, and extraction when private logic requires awkward setup. — [Vocke, The Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html#AvoidTestDuplication).
- Fowler describes narrow integration tests as exercising the external-service interaction code against a faithful double. Contract tests check fidelity; a limited real-system smoke test can cover remaining uncertainty. — [Fowler, Integration Test](https://martinfowler.com/bliki/IntegrationTest.html).
- FastAPI's official examples instantiate `TestClient(app)` and assert HTTP status and JSON behavior, covering transport-level behavior through pytest. — [FastAPI, Testing](https://fastapi.tiangolo.com/tutorial/testing/).

### Inferences
- Audit criterion: write the specific regression this test detects, identify its lowest sufficient seam, list equivalent tests, and explicitly name any validation that would disappear.
- Illustrative before/after, not a claim about existing tests: twelve browser cases checking invalid prices become a unit parameter table for the pricing rule; retain one server response-mapping test and one component error-display test. Keep a browser path if it uniquely proves save/autosave wiring.
- Illustrative before/after: full remote deployment runs for every retry/status combination become transport tests with scripted HTTP responses plus fake-client engine behavior tests. Retain a small live-provider smoke for actual authentication/API compatibility.
- A cassette proves the client interprets the recorded protocol; it does not establish that today's live API still obeys it. Avoid describing cassette replay alone as complete provider verification.
- Do not remove endpoint validation tests whose distinct assertion is request decoding or HTTP error mapping simply because the same domain rejection is unit-tested.

### Gaps
- Research cannot establish which application tests are redundant; that requires matching concrete test assertions and interface coverage in the repository. No replacement should be credited before it exists.

## Which boundaries and fixtures remain durable?

### Takeaway
Replace expensive uncontrolled dependencies at natural interfaces, using fakes with coherent state; avoid hooks inside implementation internals. UI assertions should observe behavior through user-facing contracts and waiting mechanisms.

### Cited Findings
- Google's documented terms-of-service case initially intercepted internal RPC calls. Those hooks were brittle and failed with multiple server processes. Faking backends at their interfaces, sharing coherent in-memory state, and retaining one tightly coupled real backend yielded faster, more reliable integration tests. The same UI scenarios worked with fake and real systems, allowing duplicated e2e cases to be deleted. — [Alan Myrvold, Fixing a Test Hourglass](https://testing.googleblog.com/2020/11/fixing-test-hourglass.html).
- Playwright recommends user-visible behavior, isolated tests, controlled third-party responses, and locators based on user-facing attributes or explicit contracts. Its example locates Submit by role/name rather than DOM structure. — [Playwright, Best Practices](https://playwright.dev/docs/best-practices).
- Playwright automatically checks actionability; retrying assertions express conditions expected to become true rather than requiring manual waits. — [Playwright, Writing Tests](https://playwright.dev/docs/writing-tests).
- FastAPI documents `app.dependency_overrides` for replacing dependencies during tests, including expensive external authentication. — [FastAPI, Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/).

### Inferences
- Strong positive examples to look for: stateful fake clients that expose actual remote-write effects; public application operations exercised through real workspace persistence; browser tests checking decoded render output and saved YAML; role/name locators; explicit completion conditions rather than arbitrary sleeps.
- Low-value signs to investigate, not automatic deletion rules: patching internal helper locations, asserting complete method-call order, singleton/mock identity checks, CSS/layout coupling, scenario setup that reimplements application logic, and long waits used to prove a quick business rule.
- A call-count assertion can be valuable at a genuine boundary when it expresses idempotency or prohibited remote writes. Classifying every spy as implementation coupling would erase the application's central safety property.
- For async coordinators, injecting a provider that blocks on an event can expose cancel/deploy behavior deterministically; avoid replacing the coordinator state machine itself merely to shorten a test.

### Gaps
- These are author/framework recommendations, not controlled estimates of savings. Proposed runtime improvements must be presented as projections unless durations are measured.
