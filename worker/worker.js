import TEST_PAGE_HTML from './test-page.html';

// Channel Durable Object
// Manages WebSocket connections and broadcasting for a single channel
export class Channel {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.sessions = [];
  }

  async fetch(request) {
    const url = new URL(request.url);

    // WebSocket upgrade endpoint
    if (request.headers.get('Upgrade') === 'websocket') {
      return this.handleWebSocket(request);
    }

    // POST endpoint to broadcast data to all connected clients
    if (request.method === 'POST' && url.pathname === '/broadcast') {
      return this.handleBroadcast(request);
    }

    return new Response('Not found', { status: 404 });
  }

  async handleWebSocket(request) {
    const webSocketPair = new WebSocketPair();
    const [client, server] = Object.values(webSocketPair);

    server.accept();
    this.sessions.push(server);

    // Handle incoming messages from this WebSocket
    server.addEventListener('message', (event) => {
      // Broadcast incoming message to all other connected clients
      this.broadcast(event.data);
    });

    server.addEventListener('close', () => {
      this.sessions = this.sessions.filter(session => session !== server);
    });

    server.addEventListener('error', () => {
      this.sessions = this.sessions.filter(session => session !== server);
    });

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  async handleBroadcast(request) {
    try {
      const text = await request.text();

      // Broadcast to all connected WebSocket clients
      this.broadcast(text);

      return new Response(JSON.stringify({
        success: true,
        message: 'Message broadcasted successfully',
        subscribers: this.sessions.length
      }), {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      return new Response(JSON.stringify({
        error: 'Failed to broadcast message',
        details: error.message
      }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }
  }

  broadcast(message) {
    this.sessions = this.sessions.filter(session => {
      try {
        session.send(message);
        return true;
      } catch {
        return false; // Remove disconnected sessions
      }
    });
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Handle CORS preflight requests
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 200,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // GET / - Serve test page
    if (request.method === 'GET' && url.pathname === '/') {
      return new Response(TEST_PAGE_HTML, {
        headers: {
          'Content-Type': 'text/html',
        },
      });
    }

    // POST /create_channel - Create a new channel
    if (request.method === 'POST' && url.pathname === '/create_channel') {
      const providedId = url.searchParams.get('id');
      const channelId = providedId || crypto.randomUUID();

      // Determine protocol based on the request
      const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const httpProtocol = url.protocol;

      // 200 if joining existing channel (id provided), 201 if creating new (id generated)
      const statusCode = providedId ? 200 : 201;

      return new Response(JSON.stringify({
        success: true,
        channelId: channelId,
        websocketUrl: `${wsProtocol}//${url.host}/channels/${channelId}`,
        broadcastUrl: `${httpProtocol}//${url.host}/channels/${channelId}/broadcast`
      }), {
        status: statusCode,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }

    // GET /channels/<id> - WebSocket subscription
    // POST /channels/<id>/broadcast - Broadcast to channel
    const channelMatch = url.pathname.match(/^\/channels\/([^\/]+)(\/broadcast)?$/);
    if (channelMatch) {
      const channelId = channelMatch[1];
      const isBroadcast = channelMatch[2] === '/broadcast';

      // Get the Durable Object for this channel
      const id = env.CHANNEL.idFromName(channelId);
      const stub = env.CHANNEL.get(id);

      // Forward the request to the Durable Object
      if (isBroadcast) {
        // POST /channels/<id>/broadcast
        return stub.fetch(new Request(url.origin + '/broadcast', {
          method: request.method,
          headers: request.headers,
          body: request.body,
        }));
      } else {
        // GET /channels/<id> - WebSocket
        return stub.fetch(request);
      }
    }

    return new Response('Not found', {
      status: 404,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      }
    });
  },
};
