# Resilient, behavior-focused Python tests

## Which test boundaries and doubles survive internal refactors?

### Takeaway
Prefer a stable application operation and an observable result over the choreography of its helpers. Use simple real collaborators where inexpensive, stateful fakes for external behavior, and request-level transport doubles for HTTP encoding; preserve interaction assertions when the interaction itself is a product obligation.

### Cited Findings
- Andrew Trenk's calculator example changes addition from an operator to a factory and helper objects while retaining the public `add` behavior. Assertions should survive this refactor, though constructing the subject may change. He explicitly allows narrower implementation assertions for obligations such as using a cache rather than a datastore. This is original practitioner guidance rather than an empirical universal rule. — [Google: Test Behavior, Not Implementation](https://testing.googleblog.com/2013/08/testing-on-toilet-test-behavior-not.html)
- Trenk contrasts a payment test configuring availability, transaction creation, payment, and balance mocks with a simpler test asserting the recorded charge. His criticism is that mock setup can expose implementation, complicate comprehension, and drift from real collaborators. His rough warning signs include configuring several classes or several methods, but these are diagnosis cues, not deletion thresholds. Hermetic services or in-memory implementations are alternatives when a real dependency is slow or remote. — [Google: Don't Overuse Mocks](https://testing.googleblog.com/2013/05/testing-on-toilet-dont-overuse-mocks.html)
- Fowler distinguishes a fake's working shortcut implementation from a stub's canned responses and a mock's prescribed interactions. He contrasts state verification with interaction verification and presents both classical and mockist testing approaches; the article does not justify a blanket prohibition on mocks. — [Martin Fowler: Mocks Aren't Stubs](https://martinfowler.com/articles/mocksArentStubs.html)
- HTTPX documents `MockTransport(handler)`, allowing actual client requests to receive controlled responses without network access; the handler receives the request object. Its ASGI transport can exercise an application directly. — [HTTPX: Transports](https://www.python-httpx.org/advanced/transports/)
- Fowler describes contract checks that periodically compare a double with an external service. He emphasizes contract format rather than frozen data values and notes that such checks can follow the provider's change cadence separately from normal builds. A static response fixture alone does not establish continued provider compatibility. — [Martin Fowler: Contract Test](https://martinfowler.com/bliki/ContractTest.html)

### Inferences
- Audit criterion: identify an explicit consumer-facing promise before flagging a mock assertion. A test verifying `_build_document` was called is normally weaker than asserting the submitted document or resulting fake product. However, asserting *no remote write on unchanged inputs*, sequential writes, retry count limits, or no credential read until required may directly protect this application's promises. [Basis: Test Behavior, Not Implementation](https://testing.googleblog.com/2013/08/testing-on-toilet-test-behavior-not.html)
- An application-specific **illustrative** before/after (not an observed repository finding):

```python
# Coupled: prescribes the internal route to a result.
with patch("application._resolve_variants") as resolve:
    apply_listing(listing)
    resolve.assert_called_once_with(listing.colors)

# Behavior: a public operation creates the intended external state.
client = FakePrintify()
apply_listing(listing, printify=client)
assert client.product(listing.product_id).enabled_colors == {"Black", "White"}
```

The proposed boundary is inferred from the original payment example, not prescribed by the author. Exact APIs must come from the audited repository. [Basis: Don't Overuse Mocks](https://testing.googleblog.com/2013/05/testing-on-toilet-dont-overuse-mocks.html)
- Keep layer responsibilities distinct: fake-client tests answer whether the workflow behaves correctly; real client plus request transport/cassette tests answer whether URL, headers, body, response decoding, and errors match the external interface; a small live check detects provider drift. Deleting one because another has the same scenario name would lose different validation. [Basis: HTTPX](https://www.python-httpx.org/advanced/transports/); [Contract Test](https://martinfowler.com/bliki/ContractTest.html)
- A private name is evidence of possible coupling, not proof of low value. A documented pure module boundary can be stable even without a top-level re-export. Conversely, an HTTP test which patches the entire application operation can prove HTTP adaptation but cannot prove the operation's business behavior. [Basis: Test Behavior, Not Implementation](https://testing.googleblog.com/2013/08/testing-on-toilet-test-behavior-not.html)

### Gaps
- No primary source establishes a universal acceptable mock count or fixture size. Evaluate by refactor sensitivity and unique regression protection, not numerical quotas.
- Provider compatibility cannot be inferred from a repository fake or stale cassette without evidence of provenance and refresh checks. [Contract Test](https://martinfowler.com/bliki/ContractTest.html)

## What makes an assertion independently valuable rather than tautological?

### Takeaway
Ask which plausible incorrect implementation the assertion would reject. Give each scenario a concrete oracle independent of the function being checked, and retain multiple assertions when they describe one coherent obligation.

### Cited Findings
- Alex Eagle contrasts source-like assertions and ordered collaborator calls with behavior validation. His example simply verifies that `firstPart.process` and `secondPart.process` occurred in the implementation's existing order; it encodes the same information again and fails after innocent refactors. He recommends rewriting or deleting these change detectors. This critique applies when the call order lacks an independent requirement, not when ordering is itself a safety obligation. — [Google: Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)
- Erik Kuefler's navigation example computes the expected path from a base URL and inadvertently produces a double slash. Stating the expected output directly exposes the mistake. The recommendation is to prefer concrete inputs and outputs over computations that can reproduce the implementation's error; complex shared test utilities may themselves need validation. — [Google: Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html)
- Kuefler separates purchase notification from low-balance email, even though one transaction method triggers both. A method and a behavior need not have a one-to-one relationship; splitting behaviors makes the relevant inputs clearer and reduces future accidental breakage. — [Google: Test Behaviors, Not Methods](https://testing.googleblog.com/2014/04/testing-on-toilet-test-behaviors-not.html)
- Google's focused-test example separates withdrawal within balance, rejection of overdraft, and allowed overdraft limit. Separate scenarios simplify setup and allow independent failures. It explicitly acknowledges that integration or end-to-end scenarios can require several operations. — [Google: Keep Tests Focused](https://testing.googleblog.com/2018/06/testing-on-toilet-keep-tests-focused.html)

### Inferences
- Flag `assert actual == build_expected_using_the_same_production_helper(...)` when that helper determines the behavior under examination. Prefer independently chosen literals or independent invariants. Equality between two production paths can still be useful for consistency but proves consistency, not correctness. [Basis: Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html)
- Illustrative Python oracle refactor:

```python
# Weak: repeats the operation's price algorithm.
expected = base_price + shipping + fee
assert price_listing(base_price, shipping, fee) == expected

# Concrete: a deliberate worked example.
assert price_listing(100, 20, 5) == 125
```

This is an adaptation of the navigation article, not a claim that every arithmetic expression in a test is harmful. An independently specified formula is valid when the formula itself is the specification. [Basis: Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html)
- Use a candidate mutation as a mental check: if implementation always returns a default, omits a save, skips a gate, or swaps output fields, does this assertion fail? Mark weak assertions as candidates to strengthen before deleting; status-code-only tests may protect routing or refusal adaptation but rarely validate mutation behavior. [Basis: Change-Detector Tests](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)
- A round-trip test `decode(encode(x)) == x` is not inherently tautological: it checks a coherent property but cannot prove the encoded external format independently. Preserve it where the round trip matters and add one golden/literal encoding example where interoperability matters. [Basis: Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html); [Contract Test](https://martinfowler.com/bliki/ContractTest.html)
- Idempotency and resume tests naturally involve multiple executions. Splitting away the second call can remove the very behavior under test. The unit of focus is one promise, not one method call or one assertion. [Basis: Test Behaviors, Not Methods](https://testing.googleblog.com/2014/04/testing-on-toilet-test-behaviors-not.html); [Keep Tests Focused](https://testing.googleblog.com/2018/06/testing-on-toilet-keep-tests-focused.html)
- A golden is valuable if the output itself is contractual, independently reviewed, and failures identify the faulty render behavior. An automatically accepted snapshot of internal object structure can instead fossilize implementation. [Basis: Change-Detector Tests](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)

### Gaps
- No measured mutation score or refactor history was obtained in this research. Mutation reasoning is an audit heuristic; statements that a repository assertion misses a bug need code evidence or a controlled experiment.
- Some Google full-page fetches were intermittently blocked; the behavior/method and logic articles were available with substantive original-author examples in indexed search content. Other cited articles were fetched successfully.

## How should setup, timing and concurrency be made cheaper and deterministic?

### Takeaway
Measure runtime rather than judging by labels. Minimize the resources needed for each promise, separate time-policy mathematics from orchestration, and coordinate real threads through explicit signals with bounded cleanup instead of guessed sleeps.

### Cited Findings
- pytest's fixture guide explains reusable, explicit fixtures and their scopes. A yield fixture's teardown does not run when setup fails before yielding; already completed fixtures still tear down. Its safe structure recommendation pairs each state-changing action with its cleanup. Wider scopes reuse expensive resources but also share the object between tests. — [pytest: How to use fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- pytest attributes flakiness to uncontrolled state, order dependencies, incomplete cleanup, and overly strict floating-point or timing assertions. Higher-level tests expose more state. It recommends eventually waiting on threads and avoiding pytest primitives such as `raises` and `warns` from multiple threads. Permanent non-strict xfail quarantine is described as dangerous. — [pytest: Flaky tests](https://docs.pytest.org/en/stable/explanation/flaky.html)
- Python documents `Event.set`/`wait` as inter-thread signaling: a bounded wait returns whether the signal occurred. `Thread.join(timeout)` must be followed by `is_alive()` to distinguish timeout. Barrier and Condition support other coordination patterns. — [Python 3.12: threading](https://docs.python.org/3.12/library/threading.html)
- pytest offers `--durations=N` and `--durations-min=seconds` for slow-test reporting; very short durations need `-vv` to appear. — [pytest: Profiling test execution duration](https://docs.pytest.org/en/stable/how-to/usage.html#profiling-test-execution-duration)

### Inferences
- Distinguish expensive fixture creation, operation execution, and teardown in measurements. An inexpensive assertion does not redeem a fixture that rebuilds an SPA or installs a package per case. Reuse genuinely immutable artifacts while creating fresh mutable listing/client state. [Basis: fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html); [duration profiling](https://docs.pytest.org/en/stable/how-to/usage.html#profiling-test-execution-duration)
- For retry policy, inject a recording sleeper and fixed/random-controlled clock at the documented dependency seam, then assert meaningful outcomes: retries stop at the limit, terminal failures do not retry, and server pacing is honored. Exact delay assertions are justified if a specified policy defines those delays; they are brittle if merely copied from today's loop. Avoid real multi-second sleeps in policy tests. [Basis: flaky tests](https://docs.pytest.org/en/stable/explanation/flaky.html); [Test Behavior, Not Implementation](https://testing.googleblog.com/2013/08/testing-on-toilet-test-behavior-not.html)
- Illustrative synchronization change:

```python
# Fragile: assumes background work has progressed by this wall time.
worker.start()
time.sleep(0.05)
assert run.state == "running"

# Controlled: the provider fake announces arrival and waits for release.
worker.start()
try:
    assert provider_entered.wait(timeout=2)
    assert run.state == "running"
finally:
    release_provider.set()
    worker.join(timeout=2)
assert not worker.is_alive()
```

This uses official synchronization primitives to control the relevant ordering; the two-second values are illustrative upper bounds, not recommendations for the project. [Basis: threading](https://docs.python.org/3.12/library/threading.html); [pytest thread cleanup](https://docs.pytest.org/en/stable/explanation/flaky.html)
- Do not replace every threaded test with a synchronous fake scheduler: that could erase race, cancellation, or exclusion validation. Push pure state transitions and fairness selection into unit tests, keeping a small number of controlled real-thread tests for exclusion, interruption, and lifecycle cleanup. [Basis: flaky tests](https://docs.pytest.org/en/stable/explanation/flaky.html); [threading](https://docs.python.org/3.12/library/threading.html)
- Fixture complexity is a signal to inspect the chosen layer. A business-rule assertion that requires filesystem trees, HTTP routing, render assets, and a worker may belong at a pure domain seam. A cross-component persistence assertion legitimately needs several of those resources; shortening its setup mechanically would lose assurance. [Basis: Don't Overuse Mocks](https://testing.googleblog.com/2013/05/testing-on-toilet-dont-overuse-mocks.html); [Keep Tests Focused](https://testing.googleblog.com/2018/06/testing-on-toilet-keep-tests-focused.html)

### Gaps
- Research supplies no repository timing baseline or proof of existing flakes. Actual audit recommendations must separate measured slow cases, statically visible sleeps/setup, and inferred maintenance burden.
- The primary sources do not prescribe a universal pyramid percentage or maximum unit-test duration. Use the user's required ordering of layer counts and justify each retained high-level case by a unique failure mode.
