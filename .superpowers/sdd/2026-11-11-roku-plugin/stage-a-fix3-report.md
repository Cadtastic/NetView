# Stage A fix 3 report

## SEC-2 (plugins/roku/ecp.py)
- Changed: urllib_transport now builds a per-call proxy-less, no-redirect opener whose HTTPConnection subclass wraps the socket. Every send and every recv sets the socket timeout to max(0.001, deadline - now) and raises TimeoutError once the deadline has passed (connect included). Reads go through the socket's own makefile (so http.client keeps its close semantics) wrapped in a deadline-aware RawIOBase inside a BufferedReader. Body reads use the same deadline. Imports are still stdlib only.
- Tests: test_urllib_transport_deadline_covers_every_stage (raw socket server, 0.2 s per byte; cases status-line, header-line, body), each must raise OSError within 1.6 s for a 1.0 s timeout.
- RED: status-line case took about 7 s, header-line case failed too (2 failed, 1 passed; body case already held). GREEN: all 35 ecp tests pass, the existing slow-drip body tests too.

## SEC-3 (routes.py and tests)
- Changed: removed the route's own Content-Security-Policy from _ICON_HEADERS (only X-Content-Type-Options remains, with a comment that the host sets CSP). Deleted the bare-router test that claimed a route CSP. The full-app icon tests now assert content-security-policy == CSP imported from netview.presentation.api.security, plus nosniff. security.py untouched.
- RED/GREEN: no RED is possible, since the host middleware already overwrote the header with exactly that value; the exact-value assertions pass before and after. Ruff removed the three imports the deleted test left unused.

## NEW-1 (plugins/roku/document.py)
- Changed: parse_document refuses text over 1,000,000 characters first with DocumentError("The text is too long (over 1 MB)"). The fallback scan returns None (garbage) at the first RecursionError. Also added a cap of 200 attempted JSON starts: "[{" repeated raises JSONDecodeError, not RecursionError, and each failure costs time proportional to the text, so the scan was still quadratic (about 5 s per 100 KB). The cap is an addition beyond the stated fix.
- Tests: test_deeply_nested_input_is_refused_quickly (openers "[", '{"a":', "[{", 50,000 repeats, under 1 s each), test_text_over_one_megabyte_is_refused_up_front (1,000,001 gives the message; exactly 1,000,000 gives the garbage message), test_json_after_a_few_stray_brackets_is_still_found.
- RED: "[{" case took 5.6 s (failed the 1 s bound). With only the RecursionError stop it still failed; GREEN after the cap: 35 document tests pass in 0.1 s.

## Gate
uv run pytest -q: 1384 passed, 1 warning. npm test: 253 passed, 0 failed. ruff check src tests plugins: All checks passed. mypy src plugins/roku: no errors after removing an unused type: ignore. lint-imports: 7 kept, 0 broken.
