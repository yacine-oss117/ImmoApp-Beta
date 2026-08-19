# CRM Lifecycle

This document explains the operational CRM surface in the repo.

## What It Owns

In this repo, the CRM surface is not just contacts. It is the business
lifecycle around:

- clients
- demandes
- listings
- offers
- visits
- contracts
- contract articles and standard clauses

The follow-up specific UI surface is mainly visits and contracts. The broader
entity lifecycle still spans the client side and listing side of the product.

## Main Server Facades

Entity services:

- `server/services/clients.py`
- `server/services/demandes.py`
- `server/services/listings.py`
- `server/services/offers.py`

Follow-up/CRM facade:

- `server/services/crm.py`

Follow-up submodules:

- `server/services/crm_contracts.py`
- `server/services/crm_visits.py`
- `server/services/crm_articles.py`

Important behavior:

- writes run through the psycopg UoW layer
- list/detail reads are mostly SQL-backed, not ORM-backed
- dashboard cache invalidation happens after CRM writes
- contract lifecycle changes can trigger matching cache invalidation

## Main API Surface

Core business entities:

- `server/api/views_clients_list.py`
- `server/api/views_clients_detail.py`
- `server/api/views_clients_demandes.py`
- `server/api/views_demandes.py`
- `server/api/views_listings_list.py`
- `server/api/views_listings_detail.py`
- `server/api/views_listings_offers.py`
- `server/api/views_offers.py`

Follow-up entities:

- `crm/contracts/`
- `crm/contracts/deleted/`
- `crm/contracts/<contract_id>/`
- `crm/contracts/<contract_id>/restore/`
- `crm/contracts/<contract_id>/purge/`
- `crm/contracts/<contract_id>/print/`
- `crm/contracts/<contract_id>/activate/`
- `crm/contracts/<contract_id>/cancel/`
- `crm/contracts/<contract_id>/articles/`
- `crm/contracts/<contract_id>/articles/renumber/`
- `crm/contracts/<contract_id>/clauses/`
- `crm/articles/<article_id>/`
- `crm/visits/`
- `crm/visits/deleted/`
- `crm/visits/<visit_id>/`
- `crm/visits/<visit_id>/restore/`
- `crm/visits/<visit_id>/purge/`

Route/view owners:

- `server/api/views_crm_contracts.py`
- `server/api/views_crm_articles.py`
- `server/api/views_crm_visits.py`

## Desktop Client Surface

UI containers:

- `app/views/clients_v2.py`
- `app/views/listings_v2.py`
- `app/views/crm.py`
- `app/views/crm_contracts.py`
- `app/views/crm_visits.py`

Client facades:

- `app/services/client_repository.py`
- `app/services/demande_repository.py`
- `app/services/listing_repository.py`
- `app/services/offer_repository.py`
- `app/services/crm_repository.py`
- `app/services/crm_contracts.py`
- `app/services/crm_visits.py`
- `app/services/crm_articles.py`

Offline support is real here. The desktop client can queue or overlay local
mutations through:

- `app/services/offline_entity_mutations.py`
- `app/services/offline_projection.py`
- `app/services/offline_reconciler.py`

That means the UI may show a merged local+server picture for contracts, visits,
and articles even when the server is not yet updated.

## Persistence Owners

Core SQL modules:

- `core/data/client_repo_read.py`
- `core/data/client_repo_write.py`
- `core/data/demande_repository.py`
- `core/data/listing_repo_read.py`
- `core/data/listing_repo_write.py`
- `core/data/offer_repository.py`

Follow-up SQL modules:

- `core/data/crm_contracts.py`
- `core/data/crm_contracts_read.py`
- `core/data/crm_contracts_write.py`
- `core/data/crm_contracts_status.py`
- `core/data/crm_visits.py`
- `core/data/contract_articles_repository.py`

Typed model surface:

- `core/models_client.py`
- `core/models_demande.py`
- `core/models_listing.py`
- `core/models_offer.py`
- `core/models_crm.py`
- `app/models.py`

## Contract Lifecycle

The contract subsystem is the strongest example of business side effects.

Write path:

1. desktop uses `app/services/crm_contracts.py`
2. request lands in `server/api/views_crm_contracts.py`
3. service layer uses `server/services/crm_contracts.py`
4. SQL writes go through `core/data/crm_contracts_*`
5. dashboard cache is invalidated
6. match cache dirtiness may be updated

Important contract actions:

- create
- update
- soft delete
- restore
- purge
- print
- activate
- cancel

Important side effect of `activate_contract()` and `cancel_contract()`:

- client match cache is marked dirty
- listing wilaya cache impact is marked dirty

This makes contract status changes visible to the matching system.

## Visit Lifecycle

Visit operations are simpler than contract operations.

They support:

- create
- update
- list/filter
- soft delete
- restore
- purge

They still invalidate dashboard cache after writes.

## Contract Articles

Contract articles are dynamic text rows attached to a contract.

They support:

- create
- update
- delete
- renumber
- copy standard clauses into a contract

Key files:

- `server/services/crm_articles.py`
- `core/data/contract_articles_repository.py`
- `app/services/crm_articles.py`

## Relationship To Matching And Import

CRM is tightly connected to other subsystems:

- importer can create/update the root business entities that CRM operates on
- matching reads demandes and offers created through CRM surfaces
- contract activation/cancellation feeds back into matching cache state

So CRM should be read as a lifecycle layer across the client side and listing
side, not as an isolated follow-up tab.

## Where To Debug

Client/listing entity write behavior:

- `server/services/clients.py`
- `server/services/demandes.py`
- `server/services/listings.py`
- `server/services/offers.py`

Contract/visit/article behavior:

- `server/api/views_crm_*.py`
- `server/services/crm*.py`
- `core/data/crm_*`
- `core/data/contract_articles_repository.py`

Offline projection issues:

- `app/services/offline_entity_mutations.py`
- `app/services/offline_projection.py`
- `app/services/offline_reconciler.py`
