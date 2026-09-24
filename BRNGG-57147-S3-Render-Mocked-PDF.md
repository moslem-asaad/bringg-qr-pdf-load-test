# BRNGG-57147 (S3) — run-scoped render + mocked PDF conversion

Part of [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375). Full rationale in [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §2b. **Rewritten 2026-08-22 after a dedicated deep-research pass** — this version is implementation-ready: exact control flow, exact insertion points, and every edge case found has a concrete resolution below, not just a question.

**Repo:** `templates-service`. **Depends on:** nothing — start immediately, fully independent of the other repos. **Blocks:** BRNGG-57148 (S4) needs this to call, or a stub during dev.

## What's already there — don't rebuild it

The "one call, many task_ids, one document" shape **already works today**. Both entry points share one handler:
- **HTTP:** `POST /v1/print-order/render` ([`app/controllers/v1/print_order.ts:23-33`](templates-service/app/controllers/v1/print_order.ts:23)) calls `renderHtml` directly and streams HTML back — **it never touches the upload path**, so it's irrelevant to this story except as a caller that must keep working unchanged.
- **RPC (the one that matters here):** `RENDER_PRINT_ORDER` ([`app/services/service_bus.ts:44`](templates-service/app/services/service_bus.ts:44)) → `PrintOrderHandler.render`.

## Exact control flow today (`app/services/print_order_handler.ts`)

```
render(event, logMeta)                                    // line 75
  ├─ renderHtml(event, logMeta)                            // line 76
  │    ├─ validate task_ids/merchant_id (throws 400 if empty)   // lines 52-57
  │    ├─ dedupe + cap at MAX_TASK_IDS_PER_RENDER_REQUEST = 500 // lines 32, 59-63
  │    ├─ in parallel: getCompiledTemplate(merchantId), Merchant, currency  // lines 65-69
  │    ├─ enrichAllTasks(...)                              // line 70
  │    └─ compiled({ tasks }) → HTML string                // line 72
  ├─ requestId ||= fresh UUID                               // line 77
  ├─ new UploadClient(requestId)                            // line 78
  └─ branch on event.existing_upload_id                     // lines 80-88
       ├─ present → overrideExistingUpload (uploadClient.update)  // lines 123-142
       └─ absent  → createNewUpload (uploadClient.create)          // lines 102-121
  → returns { upload_id }                                   // line 99
```

**Where content-type/extension are set today — both hardcoded, both need to become conditional:**
- `PRINT_ORDER_FILE_EXTENSION = 'html'` — line 34, used at line 113.
- `content_type: 'text/html; charset=utf-8'` — hardcoded **separately** at line 116 (`createNewUpload`) *and* line 137 (`overrideExistingUpload`) — duplicated, not a shared constant. Don't miss the second one.
- Don't confuse this with `PRINT_ORDER_CONTENT_TYPE` (line 36) — that's the content-type of the **Handlebars source template** being looked up, unrelated to the output file's MIME type.

Nothing transforms the HTML string between `renderHtml`'s output and `Buffer.from(renderedHtml)` (lines 117, 138) today — **this is exactly the seam where `htmlToPdf` gets inserted.**

## How `template_id` resolves — it doesn't exist as a caller parameter today

Confirmed: `RenderPrintOrderRequest` ([`node_modules/@bringg/types/types/templates.d.ts:109-113`](templates-service/node_modules/@bringg/types/types/templates.d.ts:109)) has no `template_id` field:
```ts
export type RenderPrintOrderRequest = {
    task_ids: number[];
    merchant_id: number;
    existing_upload_id?: number;
};
```
Today's template resolution (`getCompiledTemplate`, lines 175-210) looks up "the one print_order template configured for this merchant" by `{merchant_id, type, content_type}` — never by an explicit ID — falling back to a hardcoded default template if none exists. **`template_id` as a caller-supplied, explicit selector is a wholly new concept for this render path.** It exists nowhere adjacent to it.

But the *pattern* to reuse already exists elsewhere in this service, in the template-management CRUD code: [`app/services/templates_service.ts:299-310`](templates-service/app/services/templates_service.ts:299), `findTemplate(id, merchantId)`:
```ts
private async findTemplate(id: number, merchantId: number) {
    const templateMerchant = await this.templateMerchantRepository.findOneBy(
        { template_id: id, merchant_id: merchantId },
        { withRelated: ['template.template_languages'] }
    );
    if (isNil(templateMerchant?.template)) {
        throw new RouteNoDataFoundError(Template);
    }
    return templateMerchant.template;
}
```
This is the exact shape to adapt for the new path — it already enforces "this template belongs to this merchant" via the compound `{template_id, merchant_id}` lookup, and throws a 404-class error rather than silently falling back. **Use this pattern, not the existing print-receipt fallback-to-default behavior** — see edge case (b) below for why.

## Isolation mechanism — additive field, not a new handler class

**Decision: add optional fields to `RenderPrintOrderRequest`, branch inside the existing `render()`/`getCompiledTemplate()` — do not duplicate `PrintOrderHandler`.** Reasoning: both flows share 100% of the enrichment pipeline (`enrichAllTasks`/`enrichSingleTask`, lines 214-418) unchanged — the only new logic is (a) template resolution by ID instead of by merchant-default, and (b) a conversion step before upload. Duplicating the class would mean keeping two copies of the enrichment code in sync, which is a bigger regression surface than two guarded `if` branches. This also matches precedent: `existing_upload_id?: number` was already added to this same type as an optional, additive field without disturbing callers that don't set it (line 111) — do the same thing again.

```ts
export type RenderPrintOrderRequest = {
    task_ids: number[];
    merchant_id: number;
    existing_upload_id?: number;
    template_id?: number;   // NEW — presence of this field is the discriminator, see below
};
```

**Use presence of `template_id` as the branch discriminator — don't add a separate `type`/`document_type` field.** The tech design doc's own sequence diagram sketches `POST /render {task_ids, template_id}` without a discriminator field, which left this genuinely unresolved; the research settled it: existing callers (the dashboard's HTTP route, any current RPC callers) never set `template_id`, so `event.template_id ? runAggregationBranch() : existingBranch()` is fully backward-compatible and needs no new field. This is a deliberate call, not an oversight — write it down so it doesn't get "fixed" into a redundant field later.

## The mocked PDF step

**No PDF library exists in this repo's dependencies at all** — re-verified (`package.json`, and a scan for `puppeteer|pdf|gotenberg|chrome|headless|wkhtml`). Everything today terminates at `text/html`.

**Model the stub on the existing analogous precedent**, [`app/services/printer_handler.ts:9-66`](templates-service/app/services/printer_handler.ts:9) (`retryableZplPrintCall` — ZPL in, PDF/PNG bytes out via an external call) — not wired into `PrintOrderHandler` today, but the shape a real Gotenberg call will eventually take.

**New file: `app/helpers/html_to_pdf.ts`** (matches this repo's convention — `app/helpers/` for pure transforms, `app/services/` for handler/RPC-bound classes; a bare function belongs in `helpers/`):
```ts
// TODO(BRNGG-57374): replace with real Gotenberg-backed HTML→PDF conversion once that ticket lands.
export async function htmlToPdf(html: string): Promise<Buffer> {
  return Buffer.from(html); // mock: passthrough, not a real PDF
}
```
One exported async function — the future swap is a one-function-body change, no re-plumbing of `PrintOrderHandler`'s call site.

**`UploadClient` needs zero changes to accept this** — confirmed `application/pdf` ↔ `.pdf` is already in both directions of `CONTENT_TYPE_TO_EXTENSION`/`EXTENSION_TO_CONTENT_TYPE` ([`upload_client.js:88-103`](templates-service/node_modules/@bringg/service-utils/lib/rpc_clients/upload/upload_client.js:88)).

## New requirement not in the original plan: the 5MB size ceiling

**Confirmed: nothing checks output size anywhere today.** `UploadClient`'s only size constant, `max_download_bytes: 50MB` ([`upload_client.js:68`](templates-service/node_modules/@bringg/service-utils/lib/rpc_clients/upload/upload_client.js:68)), governs fetching a *source URL*, not a `Buffer` passed directly (which is what this handler does). This is genuinely new validation to add — the epic's §Segundo.1 5MB ceiling isn't enforced by anything upstream or downstream of this code.

**Where and how:** check the size of whatever `htmlToPdf` returns, in `render()`, right after calling it and before `createNewUpload`/`overrideExistingUpload`. Doing it here (not inside `htmlToPdf` itself) keeps the check correct and stable across the eventual mock→real swap — and per edge case (c) below, checking the mock's *passthrough* output is actually a conservative proxy (real PDF bytes are typically smaller than the source HTML for text-heavy documents), so a check written against the mock today will still make sense once BRNGG-57374 lands.

## Edge cases — each with a concrete resolution, not just a question

**(a) `task_ids` is empty for a `run_aggregation` call.** Does *not* silently render an empty document — `renderHtml` throws a 400 before any template/enrichment code runs (lines 52-54), already covered by an existing test (`test/app/services/v1/print_order_handler.test.ts:81-85`). **Resolution: keep this guard as-is for `run_aggregation` too.** Don't special-case "empty run → empty PDF" here — whether to skip generation for a zero-task run is a decision that belongs to the caller (S4/Phase 3), which controls whether it calls this endpoint at all. templates-service continuing to reject with a clear 400 requires zero new code and is the least surprising behavior.

**(b) `template_id` doesn't exist, or belongs to a different merchant.** No existing behavior to break here since no such lookup exists in the render path today — but **do not fall back to the default template the way the existing print-receipt flow does** (lines 182-189, 193-200). That fallback is fine for its own use case ("merchant hasn't set up a custom receipt yet") but actively wrong here: `template_id` is caller-supplied, so a mismatch signals a real bug or stale config upstream (e.g. a stale ID in `documents_configurations`), and silently rendering with the wrong template on a compliance document is a correctness failure with legal consequences, not a graceful degradation. **Resolution: mirror `templates_service.ts:299-310`'s `findTemplate` exactly — a compound `{template_id, merchant_id}` lookup, throw a clear 4xx (`RouteNoDataFoundError` or equivalent) on no match.** Never fall through to `DEFAULT_PRINT_ORDER_TEMPLATE` for this path.

**(c) Mocked `htmlToPdf` called with a large/many-task route.** Since it's a passthrough stub, correctness doesn't depend on size — but this is actually a *useful* property, not a gap: real HTML is already the dominant byte cost before any PDF compression, so a size check against the mock's output is a conservative (pessimistic) stand-in for the real thing — if it passes against the bloated mock, it will pass against real PDF bytes too. **Resolution: implement the 5MB check now, against the mock's output, per the section above — it doesn't need to change when the real conversion lands.**

**(d) `existing_upload_id` for `run_aggregation`.** S5 (regeneration) is out of scope for this build — the epic's own tech design doc confirms "a run's document is generated once at route start and never amended" for this pass, and the sequence diagram's `POST /render {task_ids, template_id}` never includes `existing_upload_id`. **Resolution: leave this branch (lines 80-88) completely unused for `run_aggregation` — every call goes through `createNewUpload`.** This isn't an inconsistent code path; it's the exact same behavior any first-time print-receipt caller already gets today (covered by an existing test, `test/app/services/v1/print_order_handler.test.ts:598-605`). If S5 is ever picked up later, it reuses this same branch (passing the previously-stored `upload_id` back in) rather than inventing a new one — `overrideExistingUpload` is already content-type-agnostic.

## Tests

- Rendering with N task_ids from one run produces one document, mocked PDF conversion runs, `upload_id` returned, stored as `application/pdf`/`.pdf`.
- Existing print-receipt flow (HTML, `.html`, no `template_id`) is **completely unaffected** — explicit regression test, since `render()`/`createNewUpload`/`overrideExistingUpload` are shared code.
- Empty `task_ids` → 400, same as today (regression guard, not new behavior).
- Unknown or wrong-merchant `template_id` → clear 4xx, never a silent fallback to the default template.
- Output over the 5MB ceiling → rejected with a clear error, not silently uploaded.
- `existing_upload_id` omitted for `run_aggregation` → always calls `uploadClient.create`, never `.update`.

## Acceptance criteria

1. One call with a run's `task_ids` + `template_id` produces one rendered document, converted (mocked) to PDF, stored via the existing `UploadClient` as `application/pdf`, and returns `upload_id`.
2. The mocked conversion step is isolated in one function (`app/helpers/html_to_pdf.ts`), clearly marked for the future Gotenberg swap.
3. The existing per-task print-receipt flow (no `template_id`) has zero behavior change — verified by regression test, not just by inspection.
4. A `template_id` that doesn't exist or belongs to another merchant fails loudly (4xx), never silently renders with the wrong template.
5. Output over 5MB is rejected before upload.
