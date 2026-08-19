# Task 1 System Audit Report

## 1. Changes made

The reviewer interface is now intentionally simple. It uses the short title **Job ingestion.**, a white background, black text, red actions, and a San Francisco-style system font stack. The long product subtitle and the phrase `Built for inspection, not illusion.` were removed. Internal run IDs such as `lXMxTGcu7BDiGq` are no longer shown in the user-facing heading or history cards.

When a run finishes, the active-run state is cleared, the progress animation stops, and the overview refreshes so the latest jobs are shown. Run history entries are explicitly labeled as ingestion runs, not tests. A reviewer can select a newly tracked run to inspect its associated rows. Older records created before run-level row tracking existed no longer expose a misleading run identifier; they show a neutral empty state when no exact row association is available.

The visible dashboard presents the first 20 jobs for readability, while fetched, inserted, total, and audit metrics continue to represent the full run. The unused chatbot component and other confirmed template-only UI files were removed after checking that the active application did not import them. Framework files required by the existing project scaffold were not removed.

The ingestion system still follows the same end-to-end path: permitted RemoteOK request, pacing and bounded retry, validation, normalization, source-ID deduplication, persistence, run audit, progress events, and dashboard refresh. The `ingestion_run_jobs` table now links newly created runs to their exact normalized job rows.

## 2. Verification and evidence

| Check | Result |
|---|---|
| TypeScript check | Passed after removing unused UI files and updating selected-run behavior |
| Vitest suite | 7 tests passed, including selected-run query coverage |
| Python suite | 11 tests passed in the existing Python implementation |
| Python syntax compilation | Passed |
| Completed-run behavior | Implemented so terminal progress clears the active state and refreshes the dashboard |
| Visible internal IDs | Removed from active Node and Python dashboard copy |
| Run history meaning | Clarified as ingestion runs, not tests |
| New selected-run rows | Available for runs created after run-level row tracking was added |
| Older history rows | Neutral no-rows state instead of a misleading internal ID |
| Desktop preview | Verified clean after the cleanup changes |
| Mobile preview | Verified after the final cleanup; no overflow observed |

The correct reviewer demonstration is straightforward. Start a run, observe the red progress animation, wait for the terminal success state, confirm that the animation disappears, and confirm that the overview refreshes. Then open Run history. A history item is one ingestion attempt with fetched, inserted, and error counts; it is not a test result. Select a newly created run to view its associated job rows.

## 3. Remaining limitations and audit conclusion

The current managed preview remains the original Node/tRPC runtime from the initial project scaffold. The Python FastAPI application and root Dockerfile are the intended published runtime. These two runtimes should not be treated as identical until the Python container is published and tested directly.

The Python implementation remains SQLite-first for laptop and demo simplicity. It is not yet a durable production database design for autoscaled deployment. A managed PostgreSQL or MySQL-compatible database should be connected before claiming production persistence. The scheduled callback also requires an external scheduler, and the deployed callback has not been independently verified against the live source.

Run IDs still exist internally because they are necessary for database correlation, progress polling, and audit tracing. They are not customer-facing content and are now hidden from the main interface. The progress indicator is a visual animation backed by polling; it is not a durable worker queue or guaranteed server-side streaming system.

The final audit conclusion is that this is a clear, explainable Task 1 shortlisting demonstration with improved completion behavior, cleaner reviewer presentation, auditable run records, controlled failure tests, and selected-run inspection for newly tracked runs. It should be presented honestly as a strong demo rather than as a fully production-hardened ingestion platform. The next acceptance gates are publication of the Python runtime, managed database persistence, and a deployed manual-plus-scheduled smoke test.
