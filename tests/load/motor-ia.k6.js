// Carga k6 para motor-ia-agenteX (POST /api/ia/process).
//
// Corre contra un uvicorn real del microservicio, apuntando DEEPSEEK_API_URL
// y erp_url al stub local (stub_server.py) — sin tocar la API real de
// DeepSeek ni gastar tokens. Mide la capacidad real del worker FastAPI:
// validación pydantic, loop de tool-calling, llamada al ERP, serialización.
//
// Requisitos antes de correr (ver tests/load/README.md):
//   1. Stub en :9000      -> uvicorn tests.load.stub_server:app --port 9000
//   2. Motor en :8001     -> DEEPSEEK_API_URL=http://127.0.0.1:9000/v1/chat/completions
//                             INTERNAL_SECRET=k6-load-secret uvicorn main:app --port 8001
//   3. k6 run tests/load/motor-ia.k6.js
import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8001';
const INTERNAL_SECRET = __ENV.INTERNAL_SECRET || 'k6-load-secret';
const ERP_URL = __ENV.ERP_URL || 'http://127.0.0.1:9000/erp/articulos';

const ERP_MAPPING = {
  id: 'id', sku: 'sku', nombre: 'articulo',
  precio: 'precio_tienda', stock: 'stock_min', categoria: 'categoria',
};

export const options = {
  scenarios: {
    escenario_10: {
      executor: 'constant-vus', vus: 10, duration: '30s',
      exec: 'flujoChat', startTime: '0s',
    },
    escenario_50: {
      executor: 'constant-vus', vus: 50, duration: '30s',
      exec: 'flujoChat', startTime: '35s',
    },
    escenario_100: {
      executor: 'constant-vus', vus: 100, duration: '30s',
      exec: 'flujoChat', startTime: '70s',
    },
    escenario_estres: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 200 },
        { duration: '60s', target: 200 },
        { duration: '15s', target: 0 },
      ],
      exec: 'flujoChat',
      startTime: '105s',
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.05'],
    'http_req_duration': ['p(95)<300'],
    'http_req_failed{scenario:escenario_estres}': [
      { threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '5s' },
    ],
  },
};

export function flujoChat() {
  const body = JSON.stringify({
    tenant_id: 1,
    user_message: '¿qué productos tienen stock crítico?',
    system_prompt: 'Eres un agente de soporte B2B.',
    erp_url: ERP_URL,
    erp_mapping: ERP_MAPPING,
    allowed_tools: ['consultar_inventario_erp'],
  });

  const res = http.post(`${BASE_URL}/api/ia/process`, body, {
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': INTERNAL_SECRET,
    },
  });

  check(res, {
    'status 200': (r) => r.status === 200,
    'success true': (r) => {
      try { return r.json('success') === true; } catch (_) { return false; }
    },
  });
}
