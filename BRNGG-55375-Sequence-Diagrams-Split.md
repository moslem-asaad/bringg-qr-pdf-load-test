# Sequence diagrams — split by phase

Five diagrams instead of one, matching the phase blocks in the doc's ASCII flow (§3): Trigger + Eligibility + Claim, Render + Webhook, Driver Read, Roadside Scan, Retention.

---

## 1. Trigger, Eligibility Gate, Idempotent Claim

```mermaid
sequenceDiagram
    autonumber
    actor Driver
    participant Hagmonia as hagmonia
    participant Rabbit as RabbitMQ
    participant JS as hagmonia-js
    participant SD as service-data

    Driver->>Hagmonia: start route
    Hagmonia->>Hagmonia: Run#notify_run_started
    Hagmonia->>Rabbit: publish "run:started"
    Rabbit->>JS: consume "run:started"

    JS->>SD: read merchant/team documents_configurations
    SD-->>JS: config
    alt no matching trigger
        JS-->>JS: stop, nothing generated
    else trigger matches
        JS->>SD: read run's task_ids
        SD-->>JS: task_ids[]
        JS->>JS: redlock.lock(run_id + type)
        JS->>SD: check existing document_runs for this run
        alt already claimed
            SD-->>JS: existing document — return unchanged
        else not yet claimed
            JS->>SD: INSERT documents (token generated on save)
            JS->>SD: INSERT document_runs
        end
        JS->>JS: lock.unlock()
    end
```

---

## 2. Render, Upload, Webhook

```mermaid
sequenceDiagram
    autonumber
    participant JS as hagmonia-js
    participant Templates as templates-service
    participant PdfConv as HTML→PDF (mocked)
    participant UploadSvc as upload-service
    participant SD as service-data
    participant Webhook as Merchant webhook

    JS->>Templates: POST /render {task_ids, template_id}
    Templates->>Templates: build HTML from template_id
    Templates->>PdfConv: convert HTML → PDF (mocked, BRNGG-57374)
    PdfConv-->>Templates: PDF bytes
    Templates->>UploadSvc: store artifact
    UploadSvc-->>Templates: upload_id
    Templates-->>JS: upload_id

    JS->>SD: UPDATE documents SET upload_id (status → ready)
    JS->>Webhook: POST documents_ready
```

---

## 3. Driver Read (any time after generation)

```mermaid
sequenceDiagram
    autonumber
    actor Driver
    participant App as Driver App
    participant Hagmonia as hagmonia

    App->>Hagmonia: GET batch_get_with_open
    Hagmonia->>Hagmonia: Run.preload_for_serialization incl. documents
    Hagmonia-->>App: run payload incl. documents:[{id,type,status,url}]
    App->>App: persist payload locally (offline-capable)
    Driver->>App: open sidebar → render QR from url on-device
```

---

## 4. Roadside Scan (any time up to expiry)

```mermaid
sequenceDiagram
    autonumber
    actor Inspector
    participant Hagmonia as hagmonia
    participant Storage as Cloud Storage

    Inspector->>Hagmonia: GET /document/:token (scans QR)
    Hagmonia->>Hagmonia: documents.find_by(token)
    alt token unknown
        Hagmonia-->>Inspector: 404
    else past expires_at, or artifact not retrievable
        Hagmonia-->>Inspector: 410
    else valid + artifact retrievable
        Hagmonia->>Storage: sign fresh content URL
        Storage-->>Hagmonia: signed URL
        Hagmonia-->>Inspector: 302 redirect
        Inspector->>Storage: GET signed URL
        Storage-->>Inspector: PDF downloads directly
    end
```

---

## 5. Retention (run end)

```mermaid
sequenceDiagram
    autonumber
    participant Hagmonia as hagmonia
    participant Rabbit as RabbitMQ
    participant JS as hagmonia-js
    participant SD as service-data

    Hagmonia->>Rabbit: publish run-ended (existing event)
    Rabbit->>JS: consume (existing consumer, new side effect)
    JS->>SD: UPDATE documents SET expires_at = run_end + 7 days
```
