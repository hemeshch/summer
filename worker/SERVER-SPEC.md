# Channel API Specification

## Overview

A simple, real-time channel-based messaging API built on Cloudflare Workers and Durable Objects. Create channels, subscribe via WebSocket, and broadcast messages to all subscribers.

---

## API Endpoints

### 1. Create Channel

**POST /create_channel**

Create a new channel with an optional custom ID.

#### Request

**URL:** `https://your-worker.workers.dev/create_channel`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | No | Custom channel ID. If not provided, a UUID will be generated. |

#### Response

**Success (201):**
```json
{
  "success": true,
  "channelId": "my-channel",
  "websocketUrl": "wss://your-worker.workers.dev/channels/my-channel",
  "broadcastUrl": "https://your-worker.workers.dev/channels/my-channel/broadcast"
}
```

#### Examples

```bash
# Create channel with auto-generated ID
curl -X POST https://your-worker.workers.dev/create_channel

# Create channel with custom ID
curl -X POST https://your-worker.workers.dev/create_channel?id=my-channel
```

---

### 2. Subscribe to Channel

**GET /channels/{channelId}**

Subscribe to a channel via WebSocket. Messages sent to the WebSocket will be broadcasted to all other subscribers.

#### WebSocket Connection

**URL:** `wss://your-worker.workers.dev/channels/{channelId}`

**Protocol:** WebSocket

#### Behavior

| Event | Description |
|-------|-------------|
| **On Connect** | Successfully subscribed to the channel |
| **On Message** | Receives messages from other subscribers or HTTP broadcasts |
| **Send Message** | Your message is broadcasted to all other subscribers |
| **On Disconnect** | Unsubscribed from the channel |

#### Example

```javascript
// Connect to a channel
const ws = new WebSocket('wss://your-worker.workers.dev/channels/my-channel');

ws.onopen = () => {
  console.log('Connected to channel');

  // Send a message (will be broadcasted to all subscribers)
  ws.send('Hello from WebSocket!');
};

ws.onmessage = (event) => {
  console.log('Received:', event.data);
};
```

---

### 3. Broadcast to Channel

**POST /channels/{channelId}/broadcast**

Send a message to all WebSocket subscribers of a channel via HTTP.

#### Request

**URL:** `https://your-worker.workers.dev/channels/{channelId}/broadcast`

**Headers:**
```
Content-Type: text/plain (or application/json, or any content type)
```

**Body:** Any text or JSON data

#### Response

**Success (200):**
```json
{
  "success": true,
  "message": "Message broadcasted successfully",
  "subscribers": 5
}
```

**Error (400):**
```json
{
  "error": "Failed to broadcast message",
  "details": "Error description"
}
```

#### Examples

```bash
# Broadcast text message
curl -X POST https://your-worker.workers.dev/channels/my-channel/broadcast \
  -H "Content-Type: text/plain" \
  -d "Hello from HTTP!"

# Broadcast JSON message
curl -X POST https://your-worker.workers.dev/channels/my-channel/broadcast \
  -H "Content-Type: application/json" \
  -d '{"type":"notification","message":"Server update"}'
```

---

## Configuration

**File:** `wrangler.toml`

```toml
name = "channel-api"
main = "worker.js"
compatibility_date = "2024-01-01"

[[durable_objects.bindings]]
name = "CHANNEL"
class_name = "Channel"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["Channel"]
```

---

## CORS Policy

All endpoints support CORS with the following headers:

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

---

## Authentication

Currently **NO AUTHENTICATION** is implemented. All endpoints are publicly accessible.

**⚠️ Security Considerations:**
- Anyone with a channel ID can subscribe or broadcast to it
- Consider implementing API keys or tokens for production use
- Channel IDs should be treated as secrets if you need privacy

---

## Rate Limits & Constraints

| Constraint | Value |
|------------|-------|
| Max WebSocket connections per channel | Unlimited (memory bound) |
| Max message size | ~1MB (practical limit) |
| Channel ID format | Any URL-safe string |

---

## Use Cases

### Real-time Chat
Create a channel for each chat room. Users connect via WebSocket and send messages that are broadcasted to all participants.

### Live Updates
Broadcast server-side events (deployments, alerts, metrics) to all connected dashboards.

### Collaborative Tools
Sync state between multiple users working on the same document or project.

### IoT Communication
Devices publish sensor data to a channel, subscribers receive real-time updates.

---

## Complete Example

```javascript
// 1. Create a channel
const response = await fetch('https://your-worker.workers.dev/create_channel?id=room-123', {
  method: 'POST'
});
const { channelId, websocketUrl, broadcastUrl } = await response.json();

// 2. Subscribe via WebSocket
const ws = new WebSocket(websocketUrl);

ws.onopen = () => {
  console.log('Connected to channel:', channelId);

  // Send message via WebSocket
  ws.send(JSON.stringify({ user: 'Alice', message: 'Hello!' }));
};

ws.onmessage = (event) => {
  console.log('Received:', event.data);
};

// 3. Broadcast via HTTP (from server-side)
await fetch(broadcastUrl, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ type: 'system', message: 'New user joined' })
});
```

---

## Response Status Codes

| Code | Meaning | Used For |
|------|---------|----------|
| **101** | Switching Protocols | WebSocket upgrade |
| **200** | Success | Successful broadcast |
| **201** | Created | Channel created |
| **400** | Bad Request | Invalid request or broadcast failed |
| **404** | Not Found | Unknown endpoint |

---

## Notes

- Each channel is isolated - messages only go to subscribers of that specific channel
- WebSocket messages are broadcasted to **all** subscribers (including the sender)
- HTTP broadcasts are sent to all WebSocket subscribers
- Channels are created on-demand when first accessed
- No message history - subscribers only receive messages sent after they connect

---

*Last Updated: January 2025*
*Version: 2.0.0*
