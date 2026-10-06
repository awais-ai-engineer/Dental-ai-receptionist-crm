# Aves Dental backend event automation

This directory contains an importable n8n workflow for consuming the signed domain events produced by the FastAPI transactional outbox.

## Architecture

```text
FastAPI business transaction
  -> PostgreSQL outbox event
  -> signed HTTPS request
  -> n8n Webhook
  -> HMAC and replay validation
  -> durable event-ID lookup
  -> explicit event switch
  -> SMTP notification or audit-only branch
  -> durable processed marker
  -> HTTP acknowledgement
```

n8n sends notifications only. It does not connect to the application database or change CRM state.

## Prerequisites

Use an n8n release that includes the Webhook 2.2, Code 2, Data Table 1, Switch 3.2, Respond to Webhook 1.4, and Send Email 2.1 nodes. The workflow uses the built-in Node `crypto` module and environment expressions. For self-hosted n8n, configure:

```env
N8N_WEBHOOK_SECRET=replace-with-the-same-long-random-secret-used-by-the-backend
AVES_FROM_EMAIL=reception@example.test
NODE_FUNCTION_ALLOW_BUILTIN=crypto
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

Restart n8n after changing environment variables. Do not place the secret in workflow JSON.

Create an n8n Data Table named `aves_event_dedupe` with these columns:

| Column | Type |
| --- | --- |
| `event_id` | String |
| `clinic_id` | String |
| `event` | String |
| `processed_at` | Date or String |

The workflow looks up and inserts rows by this exact table name. The processed row is inserted only after required notification delivery succeeds. Backend event IDs are stable across retries.

## Import and configure

1. In n8n, import `aves-backend-events.json` from file.
2. Open **Check Event Deduplication** and **Mark Event Processed** and verify both resolve the `aves_event_dedupe` table.
3. Open **Send Notification Email** and select an SMTP credential from n8n credential management.
4. Confirm the sender address resolves from `AVES_FROM_EMAIL`.
5. Save and activate the workflow.
6. Copy the production webhook URL ending in `/webhook/aves-backend-events`.

The SMTP credential may use Gmail, Google Workspace, Outlook SMTP, or another SMTP provider. Store its password only in n8n credential management.

## Backend configuration

Configure the FastAPI backend with the production webhook URL and the same secret:

```env
N8N_WEBHOOK_ENABLED=true
N8N_WEBHOOK_URL=https://your-n8n.example/webhook/aves-backend-events
N8N_WEBHOOK_SECRET=replace-with-the-shared-random-secret
```

The backend continues to own appointments, patients, clinics, conversations, and escalations.

## Signature and replay validation

The Webhook node captures the exact raw request body as binary data. **Verify Signature and Envelope** computes:

```text
HMAC_SHA256(N8N_WEBHOOK_SECRET, X-Aves-Timestamp + "." + raw_request_body)
```

It validates the hexadecimal signature with Node's constant-time `timingSafeEqual`, requires the header event ID to match the envelope, and rejects header timestamps more than five minutes from n8n's clock. Keep backend and n8n hosts synchronized with NTP.

The envelope must contain a supported event name, UUID `event_id`, UUID `clinic_id`, valid timestamp, and object `data`. Invalid requests receive controlled HTTP 400 or 401 responses before dedupe lookup or email delivery.

## Event routing

| Event | Automation |
| --- | --- |
| `patient.created` | Durable audit marker only |
| `appointment.requested` | Email backend-supplied receptionist recipients; fails if none are supplied |
| `appointment.approved` | Email patient when `patient_email` exists; otherwise safely skip |
| `appointment.confirmed` | Email patient when `patient_email` exists; otherwise safely skip |
| `appointment.cancelled` | Email patient when `patient_email` exists; otherwise safely skip |
| `appointment.rescheduled` | Email patient when `patient_email` exists; otherwise safely skip |
| `conversation.handoff_requested` | Email backend-supplied receptionist recipients; fails if none are supplied |
| `escalation.created` | Deduplicate and email backend-supplied recipients; n8n does not recalculate severity |
| `escalation.acknowledged` | Durable audit marker only |
| `escalation.resolved` | Durable audit marker only |

Required SMTP failures stop the workflow before the dedupe row and success response. The backend receives a non-2xx response and retries its stable event ID. Optional patient branches with no email are marked processed without sending.

Recipient lists are deduplicated before email delivery. Templates use only event payload values and do not invent clinic details, fees, refunds, diagnoses, or appointment confirmation.

## Responses

Processed event:

```json
{"ok":true,"event_id":"...","status":"processed"}
```

Previously processed event:

```json
{"ok":true,"event_id":"...","status":"duplicate"}
```

Invalid authentication or envelope data receives a non-2xx JSON response without secret material.

## End-to-end test

1. Import and configure the workflow and Data Table.
2. Configure and test the SMTP credential inside n8n.
3. Activate the workflow and copy its production webhook URL.
4. Set the backend `N8N_*` variables and restart FastAPI.
5. Trigger a real backend action such as creating an appointment request.
6. Authenticate as the clinic admin.
7. Call `POST /api/v1/outbox/process?limit=20` with the admin bearer token.
8. Verify the n8n production execution passed signature, dedupe, and the expected Switch branch.
9. Verify the email or audit-only branch completed.
10. Call `GET /api/v1/outbox?event_type=appointment.requested` and verify the event is `delivered`.
11. Manually retry the same signed request only in a controlled development environment and verify n8n returns `duplicate` without another email.

This is the final integration test. Sending unsigned sample payloads directly to the production webhook should fail by design.

## Development payloads

These examples are for inspecting mappings and templates. They are not proof of signed backend integration and will be rejected by the active production webhook without valid headers and signatures.

### Appointment requested

```json
{"event":"appointment.requested","event_id":"11111111-1111-4111-8111-111111111111","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"appointment_id":"22222222-2222-4222-8222-222222222222","patient_name":"Jane Doe","patient_email":"jane@example.test","patient_phone":"+15551230000","doctor_name":"Dr Sara","start_time":"2026-10-09T15:00:00Z","status":"requested","recipients":[{"role":"receptionist","email":"frontdesk@example.test"}]}}
```

### Appointment confirmed

```json
{"event":"appointment.confirmed","event_id":"11111111-1111-4111-8111-111111111112","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"appointment_id":"22222222-2222-4222-8222-222222222222","patient_email":"jane@example.test","doctor_name":"Dr Sara","start_time":"2026-10-09T15:00:00Z","status":"confirmed"}}
```

### Appointment cancelled

```json
{"event":"appointment.cancelled","event_id":"11111111-1111-4111-8111-111111111113","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"appointment_id":"22222222-2222-4222-8222-222222222222","patient_email":"jane@example.test","doctor_name":"Dr Sara","start_time":"2026-10-09T15:00:00Z","status":"cancelled"}}
```

### Appointment rescheduled

```json
{"event":"appointment.rescheduled","event_id":"11111111-1111-4111-8111-111111111114","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"appointment_id":"22222222-2222-4222-8222-222222222222","patient_email":"jane@example.test","doctor_name":"Dr Sara","previous_start_time":"2026-10-09T15:00:00Z","new_start_time":"2026-10-10T15:00:00Z","status":"requested"}}
```

### Human handoff

```json
{"event":"conversation.handoff_requested","event_id":"11111111-1111-4111-8111-111111111115","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"conversation_id":"33333333-3333-4333-8333-333333333333","patient_id":"44444444-4444-4444-8444-444444444444","source":"patient","recipients":[{"role":"receptionist","email":"frontdesk@example.test"}]}}
```

### Critical escalation

```json
{"event":"escalation.created","event_id":"11111111-1111-4111-8111-111111111116","clinic_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","timestamp":"2026-10-06T12:00:00Z","data":{"escalation_id":"55555555-5555-4555-8555-555555555555","severity":"critical","reason":"Explicit emergency phrase reported","summary":"Staff review required","conversation_id":"33333333-3333-4333-8333-333333333333","patient":{"name":"Jane Doe","email":"jane@example.test","phone":"+15551230000"},"recipients":[{"role":"receptionist","email":"frontdesk@example.test"},{"role":"admin","email":"admin@example.test"},{"role":"doctor","email":"doctor@example.test"}]}}
```

## Troubleshooting

- **Raw request body is unavailable:** confirm Raw Body remains enabled on the Webhook node.
- **`crypto` cannot be loaded:** set `NODE_FUNCTION_ALLOW_BUILTIN=crypto` and restart self-hosted n8n.
- **Environment access is blocked:** set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, or replace environment references with an approved n8n secret-management method.
- **Signature fails:** confirm both services use the same secret, preserve the raw body, and have synchronized clocks.
- **Data Table cannot be found:** create `aves_event_dedupe` with the exact name and columns above, then reselect it in both Data Table nodes.
- **SMTP delivery fails:** verify the selected n8n credential, sender authorization, and SMTP provider policy.
- **Backend event stays failed:** inspect the safe backend `last_error` and the corresponding n8n execution, correct the workflow, then use the admin retry endpoint.

## Idempotency limitation

The Data Table marker is durable across restarts and is written only after successful automation. The backend serializes ordinary delivery attempts for a given outbox row. n8n Data Table lookup plus insert is not a cross-execution atomic compare-and-set, so two independently submitted, simultaneous copies of a previously unseen event could both pass the lookup. If the deployment accepts webhook requests from sources other than this backend or runs unusually long notification executions beyond backend timeout windows, place the webhook behind a serialized queue or replace the two Data Table nodes with a durable store that provides a unique constraint or atomic claim on `event_id`.
