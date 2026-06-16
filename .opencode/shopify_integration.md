# Shopify Integration — Complete Reference

> **Type**: Integration (NOT a channel)  
> **Purpose**: Data enrichment — displays a contact's Shopify orders in the conversation sidebar  
> **Feature flag**: `shopify_integration` (disabled by default, `chatwoot_internal: true`)  
> **OAuth**: Yes — connects a Shopify store to a Chatwoot account  
> **Scope**: Account-level (one Shopify hook per account)

---

## 1. Architecture Overview

```
Shopify Admin API (REST v2025-01)
         ▲
         │ OAuth + API calls
         ▼
┌─────────────────────────────────────┐
│         Chatwoot (Rails)            │
│                                     │
│  Shopify::CallbacksController       │  ← OAuth callback
│  Api::V1::Integrations::ShopifyCtrl │  ← API endpoints
│  Webhooks::ShopifyController        │  ← Shopify→Chatwoot webhooks
│  Integrations::Hook (shopify)       │  ← stores OAuth token
│  Shopify::IntegrationHelper         │  ← token generation/verification
│                                     │
│  Integrations::App                  │  ← registry (active? / enabled?)
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      Frontend (Vue 3)               │
│                                     │
│  Shopify.vue           ← settings page  │
│  ShopifyOrdersList.vue ← sidebar widget │
│  ShopifyOrderItem.vue  ← single order   │
│  shopify.js            ← API client     │
└─────────────────────────────────────┘
```

---

## 2. Feature Flag

Defined in `config/features.yml:156`:

```yaml
- name: shopify_integration
  display_name: Shopify Integration
  enabled: false
  chatwoot_internal: true
```

- **`chatwoot_internal: true`** — hidden from the UI in self-hosted installations (only visible to Chatwoot cloud admins)
- Must be enabled on the account for the integration to appear
- Gated in `Integrations::App#shopify_enabled?`:

```ruby
def shopify_enabled?(account)
  account.feature_enabled?('shopify_integration') &&
    GlobalConfigService.load('SHOPIFY_CLIENT_ID', nil).present?
end
```

---

## 3. Environment Variables

| Variable | Required | Source |
|----------|----------|--------|
| `SHOPIFY_CLIENT_ID` | Yes | Shopify Partners → App → API Credentials |
| `SHOPIFY_CLIENT_SECRET` | Yes | Shopify Partners → App → API Credentials |
| `FRONTEND_URL` | Yes | Your Chatwoot frontend URL (used for OAuth redirect) |

Set via Super Admin → App Configs UI, or direct DB entry in `installation_configs`.

---

## 4. OAuth Flow (Connect a Store)

```
Agent clicks "Connect" in Settings → Integrations → Shopify
       │
       ▼
1. Modal prompts for store URL (e.g. "my-store.myshopify.com")
       │
       ▼
2. POST /api/v1/accounts/:id/integrations/shopify/auth
   { shop_domain: "my-store.myshopify.com" }
       │
       ▼
3. Chatwoot generates a JWT token encoding the account_id
   (signed with SHOPIFY_CLIENT_SECRET, HS256 algorithm)
       │
       ▼
4. Returns redirect_url:
   https://my-store.myshopify.com/admin/oauth/authorize?
     client_id={SHOPIFY_CLIENT_ID}&
     scope=read_customers,read_orders,read_fulfillments&
     redirect_uri={FRONTEND_URL}/shopify/callback&
     state={JWT}
       │
       ▼
5. User authorizes in Shopify → redirects back to:
   GET {FRONTEND_URL}/shopify/callback?code={code}&shop={shop}&state={JWT}
       │
       ▼
6. Shopify::CallbacksController#show
   - Verifies JWT state → extracts account_id
   - Exchanges code for access_token (OAuth2 client)
   - Creates/finds Integrations::Hook with:
     - app_id: 'shopify'
     - reference_id: shop domain (e.g. "my-store.myshopify.com")
     - access_token: Shopify API access token
     - status: 'enabled'
       │
       ▼
7. Redirects agent back to frontend:
   {FRONTEND_URL}/app/accounts/{id}/settings/integrations/shopify
```

### Required OAuth Scopes

```ruby
REQUIRED_SCOPES = %w[read_customers read_orders read_fulfillments].freeze
```

Defined in `app/helpers/shopify/integration_helper.rb:2`.

---

## 5. API Endpoints

All under `/api/v1/accounts/:account_id/integrations/shopify`.

### `POST auth`
| | |
|---|---|
| **Purpose** | Generate Shopify OAuth URL |
| **Params** | `shop_domain` (e.g. `my-store.myshopify.com`) |
| **Response** | `{ redirect_url: "https://..." }` |
| **Auth** | Admin only |
| **File** | `shopify_controller.rb:7-22` |

### `GET orders`
| | |
|---|---|
| **Purpose** | Fetch orders for a contact |
| **Params** | `contact_id` (Chatwoot contact ID) |
| **Response** | `{ orders: [...] }` |
| **Auth** | Admin only |
| **File** | `shopify_controller.rb:24-32` |
| **Logic** | Searches Shopify customer by contact's email OR phone → fetches orders by customer ID |

### `DELETE /`
| | |
|---|---|
| **Purpose** | Disconnect Shopify store |
| **Response** | `200 OK` |
| **File** | `shopify_controller.rb:34-39` |

---

## 6. Customer Lookup Flow (the core logic)

This is the most important part — how Chatwoot finds a Shopify customer by contact data.

```ruby
# app/controllers/api/v1/accounts/integrations/shopify_controller.rb:55-66
def fetch_customers
  query = []
  query << "email:#{contact.email}" if contact.email.present?
  query << "phone:#{contact.phone_number}" if contact.phone_number.present?

  shopify_client.get(
    path: 'customers/search.json',
    query: {
      query: query.join(' OR '),  # "email:john@example.com OR phone:+1234567890"
      fields: 'id,email,phone'
    }
  ).body['customers'] || []
end
```

### Two-step Shopify API flow

| Step | Shopify API Call | Returns |
|:----|:-----------------|:--------|
| 1 | `GET admin/api/2025-01/customers/search.json?query=email:X OR phone:Y&fields=id,email,phone` | Customer ID, email, phone |
| 2 | `GET admin/api/2025-01/customers/{customer_id}/orders.json?status=any&fields=id,email,created_at,total_price,currency,fulfillment_status,financial_status` | Full order list |

### Response format (orders)

Each order includes an `admin_url` field for deep-linking:

```ruby
order.merge('admin_url' => "https://#{shop_domain}/admin/orders/#{order['id']}")
```

Returned fields: `id`, `email`, `created_at`, `total_price`, `currency`, `fulfillment_status`, `financial_status`, `admin_url`.

### Contact validation guard

```ruby
# shopify_controller.rb:105-110
def validate_contact
  return unless contact.blank? || (contact.email.blank? && contact.phone_number.blank?)
  render json: { error: 'Contact information missing' }, status: :unprocessable_entity
end
```

If the contact has neither email nor phone, the request is rejected early.

---

## 7. Frontend Rendering Flow

```
ContactPanel.vue (conversation sidebar)
       │
       │  checks: useFunctionGetter('integrations/getIntegration', 'shopify').enabled
       │       && feature name === 'shopify_orders'
       ▼
AccordionItem "Shopify Orders"
       │
       ▼
ShopifyOrdersList.vue
  ├── Watches contactId
  ├── Checks if contact has email OR phone_number
  ├── Calls ShopifyAPI.getOrders(contactId)
  │     └── GET /api/v1/accounts/:id/integrations/shopify/orders?contact_id={id}
  └── Renders list of:
        └── ShopifyOrderItem.vue (per order)
              ├── Order ID (links to Shopify admin)
              ├── Date (formatted)
              ├── Total price + currency
              ├── Financial status (paid/refunded/voided)
              └── Fulfillment status (fulfilled/partial/unfulfilled)
```

### UI states handled

- No contact email/phone → "No orders found"
- Loading → Spinner
- API error → Error message
- Empty orders → "No orders found"
- Has orders → Order list with admin links

---

## 8. Webhook from Shopify

`POST /webhooks/shopify` → `Webhooks::ShopifyController#events`

### Supported topics

| Topic | Handler | Action |
|-------|---------|--------|
| `shop/redact` | `handle_shop_redact` | Destroys all `Integrations::Hook` records matching the `shop_domain` (store uninstall cleanup) |

### HMAC verification

All webhooks are verified using `X-Shopify-Hmac-SHA256` header:

```ruby
secret = GlobalConfigService.load('SHOPIFY_CLIENT_SECRET', nil)
computed = Base64.strict_encode64(OpenSSL::HMAC.digest('SHA256', secret, request_body))
# compared with secure_compare
```

---

## 9. Shopify Admin API Limitations

### Phone search is unreliable

The `customers/search.json?query=phone:...` endpoint **does support phone** as a search field, but it's inconsistent:

| Phone format | May work | May fail |
|:-------------|:--------:|:--------:|
| `+1-555-123-4567` | | ✅ (likely fails) |
| `+15551234567` | ✅ | |
| `15551234567` | ✅ | |
| `(555) 123-4567` | | ✅ (likely fails) |

The issue is confirmed in Shopify community threads — the exact format stored in Shopify must match what's sent. No consistent normalization is documented.

### Cannot search orders directly by phone

| API | Phone filter? |
|-----|:-------------:|
| `REST admin/api/*/orders.json` | ❌ Not supported |
| `GraphQL orders(query:)` | ❌ Not supported |
| `REST customers/search.json` | ✅ Supported (but unreliable) |
| `REST customers/{id}/orders.json` | ✅ By customer ID only |

### Workaround (already implemented)

The two-step approach Chatwoot uses is the **only reliable way**:
1. Find customer by phone/email
2. Get orders by customer ID

---

## 10. Shopify API Version

`config/integration/apps.yml` references `apps.yml` for integration metadata.

```ruby
# shopify_controller.rb:90
api_version: '2025-01'.freeze
```

---

## 11. Complete File Inventory

### Backend

| File | Role |
|------|------|
| `app/controllers/api/v1/accounts/integrations/shopify_controller.rb` | API endpoints: auth, orders, destroy |
| `app/controllers/shopify/callbacks_controller.rb` | OAuth callback handler |
| `app/controllers/webhooks/shopify_controller.rb` | Receives Shopify→Chatwoot webhooks (shop/redact) |
| `app/helpers/shopify/integration_helper.rb` | JWT token generation/verification, `REQUIRED_SCOPES` |
| `app/models/integrations/app.rb` | Registry: `shopify_enabled?` gating |
| `app/models/integrations/hook.rb` | Stores OAuth token, settings, reference_id (shop domain) |
| `config/integration/apps.yml` (shopify entry) | Integration metadata, hook_type: account |
| `config/initializers/00_init.rb` | Loads `APPS_CONFIG` |
| `config/features.yml:156` | Feature flag definition |

### Frontend

| File | Role |
|------|------|
| `app/javascript/dashboard/routes/dashboard/settings/integrations/Shopify.vue` | Settings page — connect/disconnect store |
| `app/javascript/dashboard/routes/dashboard/settings/integrations/integrations.routes.js` | Route: `settings_integrations_shopify` |
| `app/javascript/dashboard/components/widgets/conversation/ShopifyOrdersList.vue` | Sidebar widget — fetches and lists orders |
| `app/javascript/dashboard/components/widgets/conversation/ShopifyOrderItem.vue` | Single order display card |
| `app/javascript/dashboard/api/integrations/shopify.js` | API client — `getOrders(contactId)` |
| `app/javascript/dashboard/api/integrations.js` | Base API — `connectShopify({ shopDomain })` |
| `app/javascript/dashboard/routes/dashboard/conversation/ContactPanel.vue` | Conditional rendering of Shopify accordion |

### Assets

| File | Role |
|------|------|
| `public/dashboard/images/integrations/shopify.png` | Light mode icon |
| `public/dashboard/images/integrations/shopify-dark.png` | Dark mode icon |

### Locales

| File | Key |
|------|-----|
| `config/locales/en.yml:385` | `integration_apps.shopify` — name, short_description, description |

### Routes (`config/routes.rb`)

| Path | Method | Action |
|------|--------|--------|
| `POST /api/v1/accounts/:id/integrations/shopify/auth` | `auth` | OAuth redirect URL |
| `GET /api/v1/accounts/:id/integrations/shopify/orders` | `orders` | Fetch contact orders |
| `DELETE /api/v1/accounts/:id/integrations/shopify` | `destroy` | Disconnect |
| `GET /shopify/callback` | `Shopify::CallbacksController#show` | OAuth callback |
| `POST /webhooks/shopify` | `Webhooks::ShopifyController#events` | Shopify webhooks |

### Specs

| File | Tests |
|------|-------|
| `spec/controllers/api/v1/accounts/integrations/shopify_controller_spec.rb` | Auth, orders, destroy endpoints |
| `spec/controllers/shopify/callbacks_controller_spec.rb` | OAuth callback flow |
| `spec/helpers/shopify/integration_helper_spec.rb` | Token generation/verification |
| `spec/models/integrations/app_spec.rb` | `shopify_enabled?` checks |
| `spec/factories/integrations/hooks.rb` (trait: :shopify) | Test factory |

---

## 12. Testing the Integration Locally

### Setup

```bash
# 1. Enable the feature flag on your account (Rails console)
account = Account.find(1)
account.enable_features!('shopify_integration')

# 2. Set env vars via Super Admin → App Configs (or in installation_configs table)
#    SHOPIFY_CLIENT_ID
#    SHOPIFY_CLIENT_SECRET

# 3. Run the rails server + frontend
overmind start -f Procfile.dev
```

### Manual test flow

1. Navigate to Settings → Integrations → Shopify
2. Enter store URL (e.g. `my-test-store.myshopify.com`)
3. Complete OAuth in Shopify
4. Open a conversation with a contact that has an email/phone saved
5. Verify "Shopify Orders" accordion appears in the sidebar

---

## 13. Future: AI_BRAIN Integration Design (Placeholder)

To make AI_BRAIN auto-fetch Shopify order data, the following would be needed:

### Missing pieces

| Piece | What's needed |
|:------|:-------------|
| **1. Auth token** | AI_BRAIN needs a `CHATWOOT_BOT_TOKEN` env var to authenticate API calls back to Chatwoot |
| **2. Contact→Shopify lookup** | AI_BRAIN calls `GET /api/v1/accounts/{id}/integrations/shopify/orders?contact_id={id}` using the bot token |
| **3. Prompt injection** | Inject order data into LLM system prompt before generating reply |

### Possible flow

```
WhatsApp customer: "Tell me my order details"
       │
       ▼
AI_BRAIN receives message_created webhook
  ├── contact has phone_number: "+1234567890"
  │
  ├── AI_BRAIN calls:
  │   GET /api/v1/accounts/{id}/integrations/shopify/orders?contact_id={id}
  │   Authorization: Bearer {CHATWOOT_BOT_TOKEN}
  │
  ├── Chatwoot internally:
  │   ├── GET customers/search.json?query=phone:+1234567890
  │   └── GET customers/{id}/orders.json
  │
  ├── AI_BRAIN receives orders[]
  │
  ├── System prompt enriched with:
  │   "Customer's Shopify orders: [{id: 1001, total: $49.99, status: delivered}, ...]"
  │
  └── AI responds with order info
```

### Phone search reliability note

The phone number format in WhatsApp (`+1234567890`) may not match Shopify's stored format (`1234567890` or `+1-234-567-890`). Before calling the API, normalize the phone format, or query both with `OR`.

---

## 14. Key Takeaways

1. **Shopify is NOT a channel** — it doesn't send/receive messages. It's data enrichment in the sidebar.
2. **Customer lookup is two-step**: search by phone/email → fetch orders by customer ID.
3. **Phone search works but is unreliable** — format matching matters.
4. **No automated AI flow exists today** — an agent must manually click the sidebar.
5. **AI_BRAIN integration is possible** but needs: bot token, API call, prompt injection.
6. **The integration stores one OAuth token per account** — `Integrations::Hook` with `app_id: 'shopify'`.
