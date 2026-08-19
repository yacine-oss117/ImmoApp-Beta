import exec from 'k6/execution';
import http from 'k6/http';
import { Counter, Rate, Trend } from 'k6/metrics';
import { check, sleep } from 'k6';

const BASE_URL = (__ENV.PERF_BASE_URL || 'http://web:8000').replace(/\/+$/, '');
const USERS_FILE = __ENV.PERF_USERS_FILE || '/perf_outputs/perf_users.json';
const READ_RATE = Number(__ENV.PERF_READ_RATE || 30);
const READ_DURATION = __ENV.PERF_DURATION || '180s';
const READ_PRE_VUS = Number(__ENV.PERF_READ_PREALLOCATED_VUS || 30);
const READ_MAX_VUS = Number(__ENV.PERF_READ_MAX_VUS || 120);
const REBUILD_VUS = Number(__ENV.PERF_REBUILD_VUS || 2);
const ACTIVE_MANAGERS = Number(__ENV.PERF_ACTIVE_MANAGERS || 60);
const ACTIVE_OWNERS = Number(__ENV.PERF_ACTIVE_OWNERS || 10);
const MAX_FAILED_RATE = Number(__ENV.PERF_HTTP_FAILED_RATE || 0.01);
const READ_P95_MS = Number(__ENV.PERF_READ_P95_MS || 300);
const READ_P99_MS = Number(__ENV.PERF_READ_P99_MS || 600);
const REQUEST_HOST_HEADER = __ENV.PERF_HOST_HEADER || 'localhost';
const USERS_PAYLOAD = JSON.parse(open(USERS_FILE));
const SUMMARY_FILE = __ENV.PERF_SUMMARY_FILE || '/perf_outputs/k6_summary.json';
const AUTH_RETRY_MAX = Number(__ENV.PERF_AUTH_RETRY_MAX || 5);
const AUTH_RETRY_SLEEP_SEC = Number(__ENV.PERF_AUTH_RETRY_SLEEP_SEC || 1.0);
const SETUP_TIMEOUT = __ENV.PERF_SETUP_TIMEOUT || '120s';
const WARMUP_READ_CACHE = String(__ENV.PERF_WARMUP_READ_CACHE || '1').toLowerCase() !== '0';

const READ_ENDPOINT_TRENDS = {
  clients: new Trend('read_clients_duration'),
  listings: new Trend('read_listings_duration'),
  users: new Trend('read_users_duration'),
  invites: new Trend('read_invites_duration'),
  notifications: new Trend('read_notifications_duration'),
};
const READ_REQ_FAILED = new Rate('read_req_failed');
const REBUILD_REQ_FAILED = new Rate('rebuild_req_failed');
const READ_STATUS_NON_200_TOTAL = new Counter('read_status_non_200_total');
const REBUILD_STATUS_NON_ACCEPTED_TOTAL = new Counter('rebuild_status_non_accepted_total');
const READ_STATUS_TOTAL = new Counter('read_status_total');
const REBUILD_STATUS_TOTAL = new Counter('rebuild_status_total');

function loginToken(username, password) {
  for (let attempt = 1; attempt <= AUTH_RETRY_MAX; attempt += 1) {
    const res = http.post(
      `${BASE_URL}/api/auth/token/`,
      JSON.stringify({ username, password }),
      {
        headers: { 'Content-Type': 'application/json', Host: REQUEST_HOST_HEADER },
        tags: { kind: 'auth' },
        timeout: '30s',
        responseType: 'text',
        responseCallback: http.expectedStatuses({ min: 200, max: 204 }, 429, 500, 502, 503, 504),
      },
    );
    const statusOk = check(
      res,
      {
        'auth status 200': (r) => r.status === 200,
      },
      { kind: 'auth' },
    );
    if (statusOk) {
      const body = res.json();
      const tokenOk = check(
        body,
        {
          'auth access token': (b) => b && typeof b.access === 'string' && b.access.length > 16,
        },
        { kind: 'auth' },
      );
      if (tokenOk) {
        return body.access;
      }
      throw new Error(`Auth token missing for ${username}: body=${res.body || ''}`);
    }
    if (res.status === 429 || res.status >= 500) {
      sleep(AUTH_RETRY_SLEEP_SEC * attempt);
      continue;
    }
    throw new Error(
      `Auth failed for ${username}: status=${res.status} error=${res.error || ''} body=${res.body || ''}`,
    );
  }
  throw new Error(`Auth retry budget exhausted for ${username}`);
}

function pickByVu(items) {
  const vu = exec.vu.idInTest || 1;
  return items[(vu - 1) % items.length];
}

export const options = {
  discardResponseBodies: true,
  setupTimeout: SETUP_TIMEOUT,
  scenarios: {
    read_mix: {
      executor: 'constant-arrival-rate',
      exec: 'uiReadFlow',
      rate: READ_RATE,
      timeUnit: '1s',
      duration: READ_DURATION,
      preAllocatedVUs: READ_PRE_VUS,
      maxVUs: READ_MAX_VUS,
    },
    rebuild_contention: {
      executor: 'constant-vus',
      exec: 'rebuildFlow',
      vus: REBUILD_VUS,
      duration: READ_DURATION,
      startTime: '10s',
    },
  },
  thresholds: {
    read_req_failed: [`rate<${MAX_FAILED_RATE}`],
    'http_req_duration{kind:read}': [`p(95)<${READ_P95_MS}`, `p(99)<${READ_P99_MS}`],
    'checks{kind:read}': ['rate>0.99'],
    'checks{kind:rebuild}': ['rate>0.99'],
    'read_status_total{status:200}': ['count>=0'],
    'read_status_total{status:401}': ['count>=0'],
    'read_status_total{status:403}': ['count>=0'],
    'read_status_total{status:404}': ['count>=0'],
    'read_status_total{status:429}': ['count>=0'],
    'read_status_total{status:500}': ['count>=0'],
    'rebuild_status_total{status:202}': ['count>=0'],
    'rebuild_status_total{status:403}': ['count>=0'],
    'rebuild_status_total{status:429}': ['count>=0'],
    'rebuild_status_total{status:500}': ['count>=0'],
  },
};

export function setup() {
  const payload = USERS_PAYLOAD;
  const managerCreds = (payload.managers || []).slice(0, ACTIVE_MANAGERS);
  const ownerCreds = (payload.owners || []).slice(0, ACTIVE_OWNERS);
  if (managerCreds.length === 0) {
    throw new Error(`No manager credentials in ${USERS_FILE}`);
  }
  if (ownerCreds.length === 0) {
    throw new Error(`No owner credentials in ${USERS_FILE}`);
  }

  const managerTokens = managerCreds.map((item) => ({
    agency_id: item.agency_id,
    token: loginToken(item.username, item.password),
  }));
  const ownerTokens = ownerCreds.map((item) => ({
    agency_id: item.agency_id,
    token: loginToken(item.username, item.password),
  }));

  if (WARMUP_READ_CACHE) {
    for (const actor of managerTokens) {
      warmupRequest(actor.token, '/api/v1/clients/?limit=50&offset=0');
      warmupRequest(actor.token, '/api/v1/listings/?limit=50&offset=0');
      warmupRequest(actor.token, '/api/v1/users/?limit=50');
      warmupRequest(actor.token, '/api/v1/users/invites/?limit=50');
      warmupRequest(actor.token, '/api/v1/notifications/?limit=100&offset=0');
    }
  }

  return {
    managerTokens,
    ownerTokens,
  };
}

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/json',
    Host: REQUEST_HOST_HEADER,
  };
}

function warmupRequest(token, path) {
  const res = http.get(`${BASE_URL}${path}`, {
    headers: authHeaders(token),
    tags: { kind: 'warmup' },
    timeout: '30s',
    responseType: 'text',
    responseCallback: http.expectedStatuses(200),
  });
  check(
    res,
    {
      'warmup status 200': (r) => r.status === 200,
    },
    { kind: 'warmup' },
  );
}

function readRequest(token, path, endpointTag) {
  const res = http.get(`${BASE_URL}${path}`, {
    headers: authHeaders(token),
    tags: { kind: 'read', endpoint: endpointTag },
    timeout: '30s',
    responseCallback: http.expectedStatuses(200),
  });
  const statusOk = check(
    res,
    {
      'read status 200': (r) => r.status === 200,
    },
    { kind: 'read' },
  );
  READ_REQ_FAILED.add(!statusOk);
  READ_STATUS_TOTAL.add(1, { status: String(res.status), endpoint: endpointTag });
  if (!statusOk) {
    READ_STATUS_NON_200_TOTAL.add(1);
  }
  const endpointTrend = READ_ENDPOINT_TRENDS[endpointTag];
  if (endpointTrend) {
    endpointTrend.add(res.timings.duration);
  }
}

export function uiReadFlow(data) {
  const actor = pickByVu(data.managerTokens);
  const roll = Math.floor(Math.random() * 5);
  if (roll === 0) {
    readRequest(actor.token, '/api/v1/clients/?limit=50&offset=0', 'clients');
  } else if (roll === 1) {
    readRequest(actor.token, '/api/v1/listings/?limit=50&offset=0', 'listings');
  } else if (roll === 2) {
    readRequest(actor.token, '/api/v1/users/?limit=50', 'users');
  } else if (roll === 3) {
    readRequest(actor.token, '/api/v1/users/invites/?limit=50', 'invites');
  } else {
    readRequest(actor.token, '/api/v1/notifications/?limit=100&offset=0', 'notifications');
  }
  sleep(0.1 + Math.random() * 0.4);
}

export function rebuildFlow(data) {
  const actor = pickByVu(data.ownerTokens);
  const res = http.post(
    `${BASE_URL}/api/v1/cache/match/rebuild/dirty/`,
    null,
    {
      headers: authHeaders(actor.token),
      tags: { kind: 'rebuild', endpoint: 'match_cache_rebuild_dirty' },
      timeout: '60s',
      responseCallback: http.expectedStatuses(202, 429),
    },
  );
  const accepted = check(
    res,
    {
      'rebuild accepted/backpressured': (r) => r.status === 202 || r.status === 429,
    },
    { kind: 'rebuild' },
  );
  REBUILD_REQ_FAILED.add(!accepted);
  REBUILD_STATUS_TOTAL.add(1, { status: String(res.status) });
  if (!accepted) {
    REBUILD_STATUS_NON_ACCEPTED_TOTAL.add(1);
  }
  sleep(1.0 + Math.random() * 2.0);
}

export function handleSummary(data) {
  if (data && Object.prototype.hasOwnProperty.call(data, 'setup_data')) {
    delete data.setup_data;
  }
  return {
    [SUMMARY_FILE]: JSON.stringify(data, null, 2),
  };
}
