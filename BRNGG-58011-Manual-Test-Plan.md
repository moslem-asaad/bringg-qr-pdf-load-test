# BRNGG-58011 — Manual Test Steps

Manual verification for [BRNGG-58011](https://bringg.atlassian.net/browse/BRNGG-58011) (hagmonia: `documents_configurations` config + `run_attachment` lookup). Run in a hagmonia rails console: `bundle exec rails console`.

## What was built

| File | What it does |
| --- | --- |
| `db/migrate/20260826120000_add_documents_configurations_to_merchant_configurations.rb` | `documents_configurations` jsonb on `merchant_configurations`, default `[]`, not null. |
| `db/migrate/20260826120001_add_documents_configurations_to_team_configurations.rb` | Same column on `team_configurations` — **nullable, no default**, on purpose (see below). |
| `app/validators/documents_configuration_validation.rb` | JSON Schema describing a valid `documents_configurations` array. |
| `app/models/merchant_configuration.rb`, `app/models/team_configuration.rb` | Wire the schema validator to the new column on both models. |
| `app/models/run.rb` | `Run#run_attachment` — polymorphic lookup against `uploads`, only counts a file once it's actually stored. Plus: preload it for driver-payload serialization (avoids an N+1). |
| `app/serializers/driver/run_serializer.rb` | `has_document` boolean on the driver's run payload — `true` only once `run_attachment` resolves. |

Team column is nullable with no default deliberately: the team-overrides-merchant fallback (`team.documents_configurations ?? merchant.documents_configurations`, built in a later ticket) only falls through on `nil`. A default of `[]` would make every team's config "present" and the merchant's config would never apply.

## Steps

1. **Config validator — valid config saves.**
   ```ruby
   mc = MerchantConfiguration.first
   mc.update!(documents_configurations: [{"trigger" => "run_started", "documents" => [{"type" => "runAggregation"}]}])
   ```
   Should succeed with no error.

2. **Config validator — invalid config is rejected.**
   ```ruby
   mc.update!(documents_configurations: [{"trigger" => "bad_trigger"}])
   ```
   Should raise `ActiveRecord::RecordInvalid`.

3. **Pick a run to test against.**
   ```ruby
   run = Run.last
   ```

4. **Confirm no document exists yet.**
   ```ruby
   run.run_attachment   # => nil
   ```

5. **Simulate a stored upload for that run** (nothing upstream — hagmonia-js, templates-service — exists yet to create this for real, so insert it directly):
   ```ruby
   Upload.create!(merchant_id: run.merchant_id, record_type: 'Run', record_id: run.id,
                  attachment_type: 'runAggregation', file_name: 'test.pdf', stored_at: Time.current)
   ```

6. **Confirm the association now resolves.**
   ```ruby
   run.reload.run_attachment   # => the Upload row
   ```

7. **Confirm the serializer reflects it.**
   ```ruby
   JSON.parse(Driver::RunSerializer.new.preload(run).serialize_to_json(run))["has_document"]   # => true
   ```

8. **Confirm the scope actually filters — negative case.** Create a second upload for the same run that should NOT count: `stored_at: nil` (not yet stored) or a different `attachment_type`. Confirm `run.reload.run_attachment` still resolves to the upload from step 5, not the new one.

9. **N+1 guard, seen live (optional).**
   ```ruby
   ActiveRecord::Base.logger = Logger.new(STDOUT)
   Run.preload_for_serialization([run1, run2])   # two different runs
   ```
   Count the `SELECT ... FROM "uploads"` lines printed — should be exactly **one**, regardless of how many runs are in the array.
