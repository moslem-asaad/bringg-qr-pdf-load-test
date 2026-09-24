# BRNGG-55375 — QA Test Session Log

End-to-end manual verification of the DocumentsApp flow (Phase 5 smoke test) against the QA namespace
`api-moslem-asaad-1.qa.bringg.com`, merchant `60412`, run `101`.

> **Note (2026-08-31):** per code review on service-types#2141 (merged), the attachment-type string
> was renamed for casing consistency: `run_aggregation` → `runAggregation`. This log's `curl`
> commands below have been updated to the new value. The actual signed document URL and SQL query
> shown further down are left as originally captured with the old `run_aggregation` value, since
> they're a historical record of what was generated *before* the rename shipped — new test runs
> should use `runAggregation` throughout (see
> [BRNGG-55375-DocumentsApp-Test-Cases.md](BRNGG-55375-DocumentsApp-Test-Cases.md)).

## API calls made

### 1. Install `DocumentsApp` for merchant 60412

```bash
curl -X POST "https://api-moslem-asaad-1.qa.bringg.com/automation/application/add" \
  -H "Content-Type: application/json" \
  -d '{"merchant_id": 60412, "uuid": "33ef15a7-7d1b-4eec-b45f-a631ede1bb4f"}'
```

Response: `{"success":true}`

### 2. Set `documents_configurations` on merchant 60412's `MerchantConfiguration`

```bash
curl -X POST "https://api-moslem-asaad-1.qa.bringg.com/automation/merchant_configuration/upsert" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {"merchant_id": 60412},
    "attributes": {
      "documents_configurations": [{"trigger": "run_started", "documents": [{"type": "runAggregation"}]}]
    }
  }'
```

Response: 200, `MerchantConfiguration` id `52` updated with `documents_configurations` set.

### 3. Create a `WebhookDefinition` subscribing merchant 60412 to `documents_ready`

```bash
curl -X POST "https://api-moslem-asaad-1.qa.bringg.com/automation/webhook_definition/upsert" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {"merchant_id": 60414, "webhook_type": "documents_ready"},
    "attributes": {
      "merchant_id": 60414,
      "webhook_type": "documents_ready",
      "url": "https://webhooks-debug.bringg.dev/9af12ae8-c11a-4fc4-9139-e6de126b1178",
      "title": "BRNGG-55375 test receiver",
      "disabled": false
    }
  }'
```

Response: 200, `WebhookDefinition` id `1` created.

*Note: before this URL was provided, a throwaway `webhook.site` token
(`77dcbd2d-e94a-44a3-b905-bd35ad5a9337`, via `POST https://webhook.site/token`) was generated but
never wired into anything — discarded in favor of the internal debug URL above.*

### 4. Trigger `run:started` for run 101

```bash
curl -X PATCH "https://api-moslem-asaad-1.qa.bringg.com/automation/run/101" \
  -H "Content-Type: application/json" \
  -d '{"changes": {"started_at": "2026-08-30T13:30:00Z"}}'
```

Response: 200, `Run` 101 now has `started_at: "2026-08-30T13:30:00.000Z"`, `merchant_id: 60412`,
`team_id: 161448`.

## Webhook delivery

Sent to:

```
https://webhooks-debug.bringg.dev/8c27467f-2323-4443-b209-0caee01985a7
```

Payload included a signed document URL from the QA MinIO instance (stand-in for GCS in ephemeral QA
namespaces):

```
https://minio-moslem-asaad-1.qa.bringg.com/bringg-qa-uploads/upload-service/ephemeral/60412/20260830/run_aggregation/5d6787/3b56d1c0-5ce6-402e-9351-7f0cf564e24f.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260830%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260830T132856Z&X-Amz-Expires=86400&X-Amz-Signature=df948e1773aeb19f05842545591a6dbac94ab2622465b396445a0ba90a8348ec&X-Amz-SignedHeaders=host
```

## Verification query (not confirmed run)

To check `has_document` directly against hagmonia's Postgres (equivalent to
`run.run_attachment.present?` in `Driver::RunSerializer`):

```sql
SELECT EXISTS (
  SELECT 1 FROM uploads
  WHERE record_type = 'Run'
    AND record_id = 101
    AND attachment_type = 'runAggregation'
    AND stored_at IS NOT NULL
) AS has_document;
```

## Result

Full pipeline confirmed working end to end on this QA namespace:

`run:started` → `DocumentsApp.onRunStarted` → templates-service PDF render RPC → upload-service
storage (real `uploads` row) → `documents_ready` webhook delivered with a working signed document URL.
