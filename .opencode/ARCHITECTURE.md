# Chatwoot Architecture Reference

> **Purpose**: This document is the single source of truth for Chatwoot's architecture. AI coding agents should read this first before implementing any new feature. It covers the patterns, conventions, and extension points needed to make correct, idiomatic changes.

---

## 1. Tech Stack & Setup

| Layer | Technology |
|-------|-----------|
| Backend | Ruby 3.x, Rails 7.x |
| Frontend | Vue 3 (Composition API, `<script setup>`) + Vite |
| Database | PostgreSQL |
| Cache/Queue | Redis (Sidekiq / GoodJob for async jobs) |
| Styling | Tailwind CSS only (no custom CSS, no scoped CSS, no inline styles) |
| Testing | RSpec (Ruby), Vitest (JavaScript) |
| Linting | RuboCop (Ruby), ESLint (JS/Vue) |

**Key commands** (from `AGENTS.md`):
- `bundle exec rubocop -a` — Lint Ruby
- `pnpm eslint:fix` — Lint JS/Vue
- `bundle exec rspec spec/path/to/file_spec.rb` — Run Ruby tests
- `pnpm test` — Run JS tests
- `bundle exec rails db:seed` — Seed test data

### Project Files at a Glance

| Path | Role |
|------|------|
| `app/` | Rails application code (models, controllers, services, jobs, listeners, policies, serializers) |
| `enterprise/` | Enterprise Edition overlay — mirrors `app/` structure, extends/overrides OSS code |
| `lib/` | Shared utilities, custom exceptions, event types |
| `config/` | Rails config, routes, initializers |
| `db/` | Migrations, schema |
| `spec/` | Test suite (mirrors `app/` structure) |
| `app/javascript/` | Vue 3 frontend (dashboard, widgets, shared composables) |
| `swagger/` | API documentation (OpenAPI) |

**Enterprise overlay** (`enterprise/`):
- Mirrors `app/` paths exactly (e.g., `enterprise/app/services/...` extends `app/services/...`)
- Uses `prepend_mod_with` and `include_mod_with` to mix enterprise behavior into OSS classes
- Example: `WhatsappCloudService.prepend_mod_with('Whatsapp::Providers::WhatsappCloudService')` at the bottom of the OSS file
- When adding/modifying core logic, **always check** `enterprise/` for corresponding files

---

## 2. Directory Structure — Key Files & Their Roles

### 2a. Models (`app/models/`)

| File | Role |
|------|------|
| `app/models/account.rb` | Tenant — a Chatwoot installation has many accounts |
| `app/models/inbox.rb` | A communication channel container. Has a `channel` polymorphic association |
| `app/models/conversation.rb` | A thread of messages between a contact and agents |
| `app/models/message.rb` | A single message (incoming/outgoing). Has `source_id` (external platform ID), `status` (sent/delivered/read/failed), `message_type` |
| `app/models/contact.rb` | A person the business communicates with |
| `app/models/contact_inbox.rb` | Links a contact to a specific inbox with a `source_id` (e.g., WhatsApp phone number) |
| `app/models/channel/whatsapp.rb` | WhatsApp channel — stores provider config, delegates to `provider_service` |
| `app/models/channel/facebook_page.rb` | Facebook Messenger channel |
| `app/models/channel/email.rb` | Email channel |
| `app/models/channel/web_widget.rb` | Website widget channel |
| `app/models/channel/api.rb` | API / webhook channel |

**Channel Polymorphism**: `inbox.channel` returns the specific channel record. `channel_type` stores the class name string (`'Channel::Whatsapp'`, etc.). This is the core extensibility pattern.

### 2b. Controllers (`app/controllers/`)

| File | Role |
|------|------|
| `app/controllers/api/v1/accounts/conversations_controller.rb` | CRUD + `toggle_typing_status`, `update_last_seen`, `unread` |
| `app/controllers/api/v1/accounts/messages_controller.rb` | Message creation |
| `app/controllers/webhooks/whatsapp_controller.rb` | Entry point for WhatsApp webhook POSTs |
| `app/controllers/concerns/meta_token_verify_concern.rb` | Shared Meta webhook signature verification |

### 2c. Services (`app/services/`)

Services are the workhorses. They follow a consistent pattern:

```
# Pattern
class SomeService
  pattr_initialize [:required_dep!]
  
  def perform
    # main logic
  end
end
```

Key service directories:

| Path | Role |
|------|------|
| `app/services/whatsapp/providers/` | Provider implementations (polymorphic API clients) |
| `app/services/whatsapp/incoming_message_base_service.rb` | Base class for processing incoming WhatsApp messages |
| `app/services/whatsapp/incoming_message_whatsapp_cloud_service.rb` | Cloud API override |
| `app/services/whatsapp/incoming_message_service.rb` | 360dialog override |
| `app/services/whatsapp/send_on_whatsapp_service.rb` | Sends outgoing messages to WhatsApp |
| `app/services/base/send_on_channel_service.rb` | Abstract base for all channel send services |
| `app/services/conversations/typing_status_manager.rb` | Dispatches typing events |

### 2d. Listeners & Dispatchers

See Section 4 (Event System) for full details.

### 2e. Jobs (`app/jobs/`)

| File | Role |
|------|------|
| `app/jobs/webhooks/whatsapp_events_job.rb` | Async processing of incoming WhatsApp webhooks |
| `app/jobs/send_reply_job.rb` | Sends outgoing messages for any channel |
| `app/jobs/conversations/update_message_status_job.rb` | Updates message status (sent/delivered/read) when agent views conversation |
| `app/jobs/event_dispatcher_job.rb` | Async event dispatch to async listeners |

---

## 3. Channel Architecture — The Core Pattern

This is the single most important architectural pattern in Chatwoot. Every communication channel (WhatsApp, Facebook, Email, Web Widget, Twilio SMS, API, etc.) follows this pattern:

### 3a. The Polymorphic Channel

```ruby
# app/models/inbox.rb
belongs_to :channel, polymorphic: true, dependent: :destroy

# Usage:
inbox.channel          # => #<Channel::Whatsapp>
inbox.channel_type     # => "Channel::Whatsapp"
```

Each channel model stores provider-specific config in a JSONB column and implements a `provider_service` method that returns the appropriate service object.

### 3b. Provider Pattern (Virtual Interface)

Every channel that talks to an external API uses a **Provider** pattern:

```
BaseService (abstract)
  ├── WhatsappCloudService (WhatsApp Cloud API)
  ├── Whatsapp360DialogService (360dialog)
  └── (future: other WhatsApp providers)
```

**Base class** defines the interface contract with abstract methods:
```ruby
class Whatsapp::Providers::BaseService
  pattr_initialize [:whatsapp_channel!]

  def send_message(_phone_number, _message)      # raise 'abstract'
  def send_template(_phone_number, _template...)  # raise 'abstract'  
  def sync_templates                              # raise 'abstract'
  def validate_provider_config                    # raise 'abstract'
  def toggle_typing_status(_typing, **)           # raise 'abstract'
  def read_messages(_messages, **)                # raise 'abstract'
end
```

**Channel model delegates** to the provider:
```ruby
class Channel::Whatsapp < ApplicationRecord
  def provider_service
    if provider == 'whatsapp_cloud'
      Whatsapp::Providers::WhatsappCloudService.new(whatsapp_channel: self)
    else
      Whatsapp::Providers::Whatsapp360DialogService.new(whatsapp_channel: self)
    end
  end

  delegate :send_message, to: :provider_service
  delegate :send_template, to: :provider_service
  delegate :toggle_typing_status, to: :provider_service
  delegate :read_messages, to: :provider_service
end
```

**Callers** go through the channel, never the provider directly:
```ruby
inbox.channel.send_message(phone, message)
inbox.channel.read_messages(messages)
inbox.channel.toggle_typing_status(:on, last_message: msg)
```

**To add a new provider method**:
1. Add abstract method to `BaseService`
2. Add implementation to each concrete provider (`WhatsappCloudService`, `Whatsapp360DialogService`)
3. Add `delegate` to the channel model

### 3c. Message Processing Pattern

**Incoming** (per channel type):
```
Webhook Controller → Job → IncomingMessageService → DB
```
- Each channel has its own webhook controller and incoming message service
- Base class (`IncomingMessageBaseService`) handles common logic: dedup, contact resolution, conversation creation, message creation, attachment handling
- Channel-specific subclasses override `processed_params` and `download_attachment_file`

**Outgoing** (per channel type):
```
Message.create → after_create_commit → SendReplyJob → SendOnChannelService → provider
```
- `Base::SendOnChannelService` validates and delegates
- Channel-specific subclass (e.g., `Whatsapp::SendOnWhatsappService`) formats and sends via provider

---

## 4. Event / Listener System

This is how different parts of the app react to state changes without tight coupling.

### 4a. Event Types

Defined in `lib/events/types.rb`:
```ruby
module Events::Types
  CONVERSATION_CREATED  = 'conversation.created'
  CONVERSATION_READ     = 'conversation.read'
  CONVERSATION_TYPING_ON  = 'conversation.typing_on'
  CONVERSATION_TYPING_OFF = 'conversation.typing_off'
  MESSAGE_CREATED       = 'message.created'
  # ... etc
end
```

### 4b. Dispatching Events

```ruby
# From anywhere in the app:
Rails.configuration.dispatcher.dispatch(event_name, timestamp, data)
```

Events are dispatched from:
- **Models** via `after_commit` callbacks (e.g., `Conversation#notify_status_change`)
- **Services** (e.g., `TypingStatusManager#toggle_typing_status`)
- **Controllers** (various actions)

### 4c. Dispatcher Architecture

```
Dispatcher (singleton)
  ├── SyncDispatcher  (runs inline in same process)
  │   └── listeners: ActionCableListener, AgentBotListener, WhatsappListener
  └── AsyncDispatcher (runs via EventDispatcherJob)
      └── listeners: AutomationRuleListener, CampaignListener, CsatSurveyListener,
                     HookListener, NotificationListener, ParticipationListener,
                     WebhookListener, ReportingEventListener, UnreadCountsListener
```

**Sync vs Async**: Sync listeners run immediately in the same request/process. Async listeners run in a background job. Choose sync for real-time UI updates (ActionCable broadcasts, WhatsApp typing indicators). Choose async for side-effects (webhooks, notifications, automations).

**File**: `app/dispatchers/sync_dispatcher.rb` and `app/dispatchers/async_dispatcher.rb`

### 4d. Adding a New Listener

1. Create `app/listeners/my_listener.rb` inheriting `BaseListener`
2. Include `Events::Types` for event constants
3. Define methods matching event names (e.g., `def message_created(event)`)
4. Use `extract_conversation_and_account(event)` etc. from `BaseListener`
5. Register in the appropriate dispatcher's `listeners` method

```ruby
# Example listener
class MyListener < BaseListener
  include Events::Types

  def conversation_created(event)
    conversation = extract_conversation_and_account(event)[0]
    # do something
  end
end

# Register in sync_dispatcher.rb or async_dispatcher.rb
def listeners
  [..., MyListener.instance]
end
```

### 4e. Existing Listeners Reference

| Listener | Dispatcher | Handles Events |
|----------|-----------|----------------|
| `ActionCableListener` | Sync | `notification_*`, `conversation_*`, `message_created`, `typing_on/off` |
| `AgentBotListener` | Sync | `conversation_*`, `message_*`, `webwidget_triggered` |
| `WhatsappListener` | Sync | `conversation_typing_on`, `message_created` |
| `WebhookListener` | Async | `conversation_*`, `message_*`, `typing_on/off` |
| `HookListener` | Async | `message_*`, `contact_*`, `conversation_*` |
| `NotificationListener` | Async | `message_created`, `conversation_*` |
| `AutomationRuleListener` | Async | `conversation_*`, `message_*` |
| `CampaignListener` | Async | `campaign_triggered` |

---

## 5. Full Message Lifecycle (WhatsApp Example)

### 5a. Incoming WhatsApp Message

```
1. Meta sends POST to /webhooks/whatsapp/:phone_number
2. Webhooks::WhatsappController#process_payload
   - Verifies signature (whatsapp_cloud provider)
   - Enqueues Webhooks::WhatsappEventsJob.perform_later(params)
   - Returns 200 OK immediately
3. Webhooks::WhatsappEventsJob#perform
   - Finds channel by phone_number
   - Acquires Redis mutex (dedup per inbox_id + sender_id)
   - Calls #process_events
4. Process events routes to:
   - channel.provider == 'whatsapp_cloud' → IncomingMessageWhatsappCloudService
   - channel.provider == 'default' (360dialog) → IncomingMessageService (base)
5. IncomingMessageBaseService#perform
   - process_statuses: update message status (sent/delivered/read/failed)
   - OR process_messages:
     - Dedup via MessageDedupLock (Redis SET NX on source_id)
     - set_contact → set_conversation → create_messages
     - Message.create fires after_create_commit
6. Message after_create_commit:
   - dispatch_create_events → MESSAGE_CREATED event
   - send_reply → SendReplyJob (for outgoing agent replies only)
7. MESSAGE_CREATED event fires:
   - Sync: ActionCableListener broadcasts to UI
   - Sync: AgentBotListener sends to agent bot URLs
   - Sync: WhatsappListener#message_created → marks messages as read (if outgoing reply)
   - Async: WebhookListener sends to account webhooks
   - Async: NotificationListener creates notifications for agents
   - Async: AutomationRuleListener checks automation rules
```

### 5b. Outgoing WhatsApp Message (Agent Reply)

```
1. Agent sends reply in Chatwoot UI
2. POST /api/v1/accounts/:id/conversations/:id/messages
3. MessagesController creates the message
4. Message.create → after_create_commit:
   - send_reply → SendReplyJob.perform_later(message.id)
   - MESSAGE_CREATED event (handled by listeners above)
5. SendReplyJob → Whatsapp::SendOnWhatsappService#perform
6. Base::SendOnChannelService#perform → perform_reply
7. SendOnWhatsappService:
   - Can reply? → send_session_message
     channel.send_message(contact_source_id, message)
   - No reply / template? → send_template_message
     channel.send_template(...)
8. channel.send_message delegates to provider_service.send_message
   - WhatsappCloudService: POST {phone_id_path}/messages
   - Whatsapp360DialogService: POST {api_base_path}/messages
9. Message ID from response stored in message.source_id
```

---

## 6. Implemented Features

### 6a. Mark as Read (WhatsApp)

**Purpose**: When an agent or AI bot has seen/processed an incoming WhatsApp message, send a read receipt to Meta so the user sees blue double-checks.

**WhatsApp API**: `POST /{phone_number_id}/messages`
```json
{"messaging_product": "whatsapp", "message_id": "wamid.XXX", "status": "read"}
```

**Provider layer**:
- `Whatsapp::Providers::BaseService#read_messages(messages, **kwargs)` — abstract
- `Whatsapp::Providers::WhatsappCloudService#read_messages` — uses `phone_id_path('v23.0')`
- `Whatsapp::Providers::Whatsapp360DialogService#read_messages` — uses `api_base_path`

**Three trigger points**:

| Trigger | File | How |
|---------|------|-----|
| Agent views conversation | `conversations_controller.rb` | `after_action :send_whatsapp_read_receipt, only: [:update_last_seen, :show]` |
| AI/bot sends a reply | `whatsapp_listener.rb` | `message_created` handler detects outgoing WhatsApp message and calls `read_messages` |
| AI/bot types | `whatsapp_listener.rb` | `toggle_typing_status` payload also includes `status: 'read'` (combined call) |

**Files changed**:
- `app/services/whatsapp/providers/base_service.rb` — abstract method
- `app/services/whatsapp/providers/whatsapp_cloud_service.rb` — Cloud API impl (v23.0)
- `app/services/whatsapp/providers/whatsapp_360_dialog_service.rb` — 360dialog impl
- `app/models/channel/whatsapp.rb` — delegation
- `app/listeners/whatsapp_listener.rb` — `message_created` handler
- `app/controllers/api/v1/accounts/conversations_controller.rb` — `after_action` hook

### 6b. Typing Indicator (WhatsApp)

**Purpose**: Show "typing..." to the WhatsApp user when an agent or AI bot is composing a reply.

**WhatsApp API**: `POST /{phone_number_id}/messages`
```json
{
  "messaging_product": "whatsapp",
  "message_id": "wamid.XXX",
  "status": "read",
  "typing_indicator": {"type": "text"}
}
```

**Note**: The payload combines both `status: "read"` and `typing_indicator` — marking the message as read while showing the typing indicator. The typing indicator lasts up to 25 seconds or until a message is sent.

**Trigger**:
1. Agent/bot calls `POST /api/v1/accounts/:id/conversations/:id/toggle_typing_status` with `typing_status: "on"`
2. `Conversations::TypingStatusManager` dispatches `CONVERSATION_TYPING_ON`
3. `WhatsappListener#conversation_typing_on` picks it up
4. Calls `channel.toggle_typing_status(CONVERSATION_TYPING_ON, last_message: last_msg)`
5. Provider sends the typing indicator payload to Meta

**Files changed**:
- `app/services/whatsapp/providers/base_service.rb` — abstract method
- `app/services/whatsapp/providers/whatsapp_cloud_service.rb` — Cloud API impl
- `app/services/whatsapp/providers/whatsapp_360_dialog_service.rb` — 360dialog impl
- `app/models/channel/whatsapp.rb` — delegation
- `app/listeners/whatsapp_listener.rb` — `conversation_typing_on` handler
- `app/dispatchers/sync_dispatcher.rb` — registered `WhatsappListener.instance`

---

## 7. Enterprise Overlay Pattern

The `enterprise/` directory adds paid features on top of the OSS codebase without modifying OSS files.

### How it works

At the **bottom of OSS files**, you'll find:
```ruby
Whatsapp::Providers::WhatsappCloudService.prepend_mod_with('Whatsapp::Providers::WhatsappCloudService')
Api::V1::Accounts::ConversationsController.prepend_mod_with('Api::V1::Accounts::ConversationsController')
AsyncDispatcher.prepend_mod_with('AsyncDispatcher')
```

The enterprise file at `enterprise/app/services/...` defines a **module** with the same name and prepends it:
```ruby
# enterprise/app/services/enterprise/whatsapp/providers/whatsapp_cloud_service.rb
module Enterprise::Whatsapp::Providers::WhatsappCloudService
  def initiate_call(to_phone_number, sdp_offer)
    # enterprise-only logic, can call super
  end
end
```

### Checklist when modifying OSS code

1. Search `enterprise/` for related files: `rg -n "ClassName" app enterprise`
2. Does enterprise need an override? Add a module in `enterprise/app/services/...`
3. Does enterprise need a new extension point? Add a hook or config flag in OSS
4. Keep response contracts stable across OSS and Enterprise
5. Add enterprise specs under `spec/enterprise/`

---

## 8. Extension Cookbook

### 8a. Add a new provider method (e.g., `send_csat_survey`)

```ruby
# 1. BaseService — abstract
def send_csat_survey(_phone_number, **_kwargs)
  raise 'Overwrite this method in child class'
end

# 2. WhatsappCloudService — implement
def send_csat_survey(phone_number, **_kwargs)
  response = HTTParty.post("#{phone_id_path}/messages", headers: api_headers, body: {...}.to_json)
  process_response(response, @message)
end

# 3. Whatsapp360DialogService — implement (same pattern)

# 4. Channel — delegate
delegate :send_csat_survey, to: :provider_service

# 5. Call via channel
inbox.channel.send_csat_survey(phone, ...)
```

### 8b. Add a new event + listener

```ruby
# 1. Add event type to lib/events/types.rb
CUSTOM_EVENT = 'custom.event'

# 2. Dispatch it
Rails.configuration.dispatcher.dispatch(Events::Types::CUSTOM_EVENT, Time.zone.now, data)

# 3. Create listener
class CustomListener < BaseListener
  def custom_event(event)
    # handle it
  end
end

# 4. Register in dispatcher
# sync_dispatcher.rb or async_dispatcher.rb
def listeners
  [..., CustomListener.instance]
end
```

### 8c. Add enterprise-only behavior

```ruby
# 1. Add prepend_mod_with to OSS file if not present
MyService.prepend_mod_with('MyService')

# 2. Create enterprise module
# enterprise/app/services/enterprise/my_service.rb
module Enterprise::MyService
  def perform
    if account.feature_enabled?('enterprise_feature')
      # enterprise logic
    else
      super
    end
  end
end
```

### 8d. Add a new channel type

1. Create channel model `app/models/channel/my_channel.rb`
2. Create provider base + implementation in `app/services/my_channel/providers/`
3. Create incoming message service
4. Create send_on service (`app/services/my_channel/send_on_my_channel_service.rb`)
5. Create webhook controller
6. Add to `inbox.rb` channel types if needed
7. Add routes
8. Add UI components in `app/javascript/`

---

## 9. Quick File Index

### WhatsApp Channel

| File | Lines | Role |
|------|-------|------|
| `app/models/channel/whatsapp.rb` | 151 | Model, provider delegation, voice calling |
| `app/controllers/webhooks/whatsapp_controller.rb` | 74 | Meta webhook verification + payload ingestion |
| `app/jobs/webhooks/whatsapp_events_job.rb` | 164 | Async webhook processing, routing to services |
| `app/services/whatsapp/incoming_message_base_service.rb` | 217 | Shared incoming message processing logic |
| `app/services/whatsapp/incoming_message_whatsapp_cloud_service.rb` | 29 | Cloud API param parsing + media download |
| `app/services/whatsapp/incoming_message_service.rb` | 5 | 360dialog override (inherits base) |
| `app/services/whatsapp/incoming_message_service_helpers.rb` | 85 | Shared helpers (content extraction, dedup) |
| `app/services/whatsapp/incoming_message_identifier_helper.rb` | 108 | Contact/conversation resolution from payload |
| `app/services/whatsapp/message_dedup_lock.rb` | 19 | Redis-based dedup lock |
| `app/services/whatsapp/send_on_whatsapp_service.rb` | 48 | Outgoing reply dispatch |
| `app/services/whatsapp/providers/base_service.rb` | 114 | Abstract provider interface |
| `app/services/whatsapp/providers/whatsapp_cloud_service.rb` | 263 | Cloud API implementation (messages, templates, media) |
| `app/services/whatsapp/providers/whatsapp_360_dialog_service.rb` | 158 | 360dialog implementation |
| `app/services/whatsapp/webhook_setup_service.rb` | 125 | Register/unregister webhooks on Meta |
| `app/services/whatsapp/webhook_teardown_service.rb` | — | Cleanup on channel deletion |
| `app/services/whatsapp/facebook_api_client.rb` | 127 | Low-level Graph API client for WABA mgmt |
| `app/services/whatsapp/health_service.rb` | 95 | Phone number health data |
| `app/listeners/whatsapp_listener.rb` | 31 | Sync listener: typing indicators + auto read-receipt |
| `enterprise/app/services/enterprise/whatsapp/providers/whatsapp_cloud_service.rb` | 112 | Enterprise: calling API (initiate/accept/reject/terminate) |
| `enterprise/app/jobs/enterprise/webhooks/whatsapp_events_job.rb` | 60 | Enterprise: route call events |
| `enterprise/app/services/whatsapp/incoming_call_service.rb` | — | Process incoming call webhooks |
| `enterprise/app/services/whatsapp/call_service.rb` | — | Call actions |

### Core Framework Files

| File | Role |
|------|------|
| `app/dispatchers/dispatcher.rb` | Singleton, routes to sync + async dispatchers |
| `app/dispatchers/sync_dispatcher.rb` | Inline listeners (ActionCable, AgentBot, Whatsapp) |
| `app/dispatchers/async_dispatcher.rb` | Background listeners (Webhook, Notification, Hook, etc.) |
| `app/listeners/base_listener.rb` | Extract helpers for event.data |
| `lib/events/types.rb` | All event name constants |
| `app/services/base/send_on_channel_service.rb` | Abstract base for outgoing channel messages |
| `app/jobs/send_reply_job.rb` | Routes outgoing messages to correct channel sender |
| `app/controllers/api/v1/accounts/conversations_controller.rb` | Conversation CRUD, typing, read status |

---

## 10. Development Guidelines (from AGENTS.md)

- **MVP focus**: Least code change, happy-path only
- **No unnecessary defensive programming**
- **Prefer minimal, readable code** over elaborate abstractions
- **Tailwind only**: no custom CSS, no scoped CSS, no inline styles
- **Translations**: only update `en.yml` (backend) and `en.json` (frontend)
- **After implementing**: run lint (`bundle exec rubocop -a`, `pnpm eslint:fix`)
- **Don't commit unless explicitly asked**
- **Use `prepend_mod_with`** for enterprise extensions, not hard forks
