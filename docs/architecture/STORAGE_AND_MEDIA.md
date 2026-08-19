# Storage And Media

This document explains how object storage and media flows work in the repo.

## What It Owns

The storage subsystem owns:

- object metadata lifecycle
- presigned upload generation
- upload finalization
- download URL generation
- quota accounting
- deletion and purge lifecycle

The media layer builds on top of storage for:

- agency logo and signature assets
- offer photo attachments
- importer file staging

Storage is an infrastructure-facing subsystem. Media is the business-facing
surface that uses it.

## Main Server Facades

Storage public facade:

- `server/services/storage.py`

Storage implementation split:

- `server/services/storage_ops.py`
- `server/services/storage_ops_upload.py`
- `server/services/storage_ops_access.py`
- `server/services/storage_ops_maintenance.py`
- `server/services/storage_config.py`
- `server/services/storage_validation.py`
- `server/services/storage_scanning.py`

Media-specific facades:

- `server/services/media.py`
- `server/services/offer_photos.py`

## Persistence Owners

Primary storage metadata tables:

- `storage_objects`
- `storage_usage`
- `storage_events`
- `offer_photos`

Primary SQL owners:

- `core/data/storage_objects.py`
- `core/data/storage_events.py`
- `core/data/offer_photos_repository.py`

Important metadata lifecycle states visible in `storage_objects`:

- `pending`
- `ready`
- `failed`
- `deleted`
- `purged`

Quota checks depend on both ready and pending reservations, not only fully
completed objects.

## Public API Surface

Generic storage API:

- `storage/presign/`
- `storage/presign-upload/`
- `storage/complete-upload/`
- `storage/delete/`

Agency media API:

- `settings/agency/media/`
- `settings/agency/media/presign/`
- `settings/agency/media/complete/`

Offer photo attachment API is part of the offer surface:

- `offers/<offer_id>/photos/`

HTTP view owners:

- `server/api/views_storage.py`
- `server/api/views_agency.py`
- `server/api/views_offers.py`
- `server/api/views_listings_offers.py`

## Generic Upload Flow

Presigned upload flow:

1. client asks `storage/presign-upload/`
2. server creates `storage_objects` metadata in `pending`
3. server returns target URL, form fields, and `storage_id`
4. client uploads bytes directly to object storage
5. client calls `storage/complete-upload/`
6. server verifies the object and marks metadata `ready`

This is the canonical pattern for large or direct uploads.

Download flow:

1. client asks `storage/presign/`
2. server returns a short-lived download URL

Delete flow:

1. client asks `storage/delete/`
2. server marks metadata `deleted`
3. maintenance later purges the physical object

## Agency Media Flow

Agency logo/signature is a storage-backed settings feature.

Server owners:

- `server/services/media.py`
- `server/api/views_agency.py`

Client owner:

- `app/services/agency_media.py`

Behavior:

- GET can return a presigned URL or inline base64 content
- write path uses presigned upload
- the agency setting stores the `storage_id`, not raw bytes
- previous media is marked deleted when replaced
- desktop caches fetched media locally

Offline behavior exists on the client:

- pending agency media uploads are queued through `app/services/upload_queue.py`
- replay happens through `app/services/agency_media.py`
- queued media uses account-scoped local storage under the offline runtime

## Offer Photo Flow

Offer photos are also storage-backed, but they attach to offers after upload.
This is intentional domain language: the top-level listing is the owner/contact
record, while each offer is the marketed property/opportunity. User-facing UI
may say "Property Photos" inside an offer panel, but backend/storage/API names
remain `offer_photo` and `offer_photos`.

Server owners:

- `server/services/offer_photo_lifecycle.py`
- `server/services/offer_photos.py`
- `core/data/offer_photos_repository.py`

Client owner:

- `app/services/offer_photos.py`

Flow:

1. client requests `storage/presign-upload/` with `purpose=offer_photo`
2. object is uploaded and completed
3. client calls `offers/<offer_id>/photos/` with `storage_id`
4. server verifies same-agency ownership and `purpose=offer_photo`
5. attachment row is created in `offer_photos`

Supported offer-photo file types are PNG, JPG/JPEG, and BMP. WebP is not part
of the current contract. The default maximum size is controlled by
`STORAGE_MAX_OFFER_PHOTO_MB` and defaults to 10 MB.

Deletion behavior:

- deleting an individual offer photo is a manual delete; parent offer/listing
  restore does not reverse it
- cleanup only marks storage metadata deleted when no active photo references
  remain
- offer/listing delete soft-deletes only currently active attached photo rows
  with explicit parent delete provenance
- offer/listing restore restores only photo rows deleted by that same parent
  cascade and reactivates their non-purged storage metadata
- purged storage objects and purged parent photo rows are final and are not
  restored into active photo rows

Offline behavior:

- offer photo uploads are queue-backed
- the queue stores file path, parent local id, position, and later the `storage_id`
- parent references can be rewritten after offline entity reconciliation

Important client files:

- `app/services/offer_photos.py`
- `app/services/upload_queue.py`
- `app/services/network_sync.py`

## Importer Dependency

The importer depends on storage but does not reimplement it.

Import files are staged in object storage first, then parse tasks call:

- `server/services/storage.download_to_temp()`

That makes storage part of the importer runtime path too.

## Safety And Scope Rules

Important rules enforced in this subsystem:

- agency scope is enforced through DB tenant context
- destructive storage delete requires manager-level access in `views_storage.py`
- agency media writes require manager access in `views_agency.py`
- offer photo attachment checks storage purpose and agency scope before linking
- purge is delayed and maintenance-driven, not immediate data loss
- Postgres backup alone is insufficient for media recovery; object storage
  data, including the Docker `minio_data` volume or equivalent S3 bucket, must
  be backed up and restored with the database.

## Where To Debug

Presign/finalize failures:

- `server/api/views_storage.py`
- `server/services/storage_ops_upload.py`
- `server/services/storage_validation.py`

Agency logo/signature issues:

- `server/services/media.py`
- `server/api/views_agency.py`
- `app/services/agency_media.py`

Offer photo issues:

- `server/services/offer_photos.py`
- `app/services/offer_photos.py`
- `app/services/upload_queue.py`

Metadata/quota drift:

- `core/data/storage_objects.py`
- `core/data/storage_events.py`
- `server/services/storage_ops_maintenance.py`
