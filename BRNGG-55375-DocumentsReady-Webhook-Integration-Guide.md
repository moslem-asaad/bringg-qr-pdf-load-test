# Documents Ready Webhook — Integration Guide

## Overview

The **Documents Ready** webhook (`webhook_type: "documents_ready"`) fires once a route's compliance document has finished generating and is fully available to download.

This is part of Bringg's support for Spain's Sustainable Mobility Law 9/2025, which requires the transport document (DeCA) to be digital and scannable. For each qualifying route, Bringg aggregates every task on the run into a single PDF, stores it, and — once storage is confirmed complete — sends this webhook with a link to the file.

**When it fires:** a run-start event triggers document generation to begin. Once generation finishes and the document is fully stored, this webhook fires. A partially-generated document never triggers it.

**What it's for:** so your system can capture and archive a link to the compliance document as soon as it exists.

## Payload Schema

| Field | Type | Description |
|---|---|---|
| `webhook_type` | string | Always `"documents_ready"` |
| `merchant_id` | number | Bringg's internal ID for the merchant |
| `run.id` | number | Bringg's internal ID for the route |
| `run.external_id` | string | Your own ID for the route, as originally provided to Bringg |
| `run.tasks` | array | Every task (order/stop) on this route |
| `run.tasks[].id` | number | Bringg's internal ID for the task |
| `run.tasks[].external_id` | string | Your own ID for the task, as originally provided to Bringg |
| `documents` | array | The compliance document(s) generated for this route (currently always exactly one) |
| `documents[].id` | number | Bringg's internal ID for the stored file |
| `documents[].type` | string | Document type — currently always `"runAggregation"` (one PDF covering every task on the run) |
| `documents[].url` | string | Signed, temporary download link to the PDF — valid for up to 24 hours, see **Document URLs** below |

## Example Payload

```json
{
  "run": {
    "id": 65078,
    "external_id": "MA-STG2-RUN1K-477",
    "tasks": [
      {
        "id": 9748806,
        "external_id": "MA-STG2-ADEO1K-20260917-0953"
      },
      {
        "id": 9748807,
        "external_id": "MA-STG2-ADEO1K-20260917-0954"
      }
    ]
  },
  "documents": [
    {
      "id": 221,
      "type": "runAggregation",
      "url": "https://storage.googleapis.com/bringg-stg2-uploads/upload-service/ephemeral/60596/20260917/runAggregation/6130b5/c546543c-ec2c-4d77-ab85-9c9030063a7d.pdf?GoogleAccessId=stg2-app-uploader%40bringg-stg2.iam.gserviceaccount.com&Expires=1789735663&Signature=..."
    }
  ],
  "webhook_type": "documents_ready",
  "merchant_id": 60596
}
```

## Document URLs

The `url` in each `documents[]` entry is a **signed, temporary link** directly to the file in cloud storage — not a permanent, stable URL.

- **Validity:** up to 24 hours from when the webhook is delivered.
- **Recommendation:** download and store the file on your own side promptly after receiving the webhook, rather than keeping only the URL for later use. Once a signed link expires it stops working, and there's no way to refresh that same URL — a fresh one would need to be requested separately.
- **No authentication needed:** the link itself requires no Bringg credentials to fetch — the signature embedded in the URL is the access control.
