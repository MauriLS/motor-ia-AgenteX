# Carga k6 — motor-ia-agenteX

## Por qué un stub en vez de la API real de DeepSeek

`DEEPSEEK_API_URL` es configurable por entorno (ver `main.py`). Sin esto, un
k6 real golpearía la API real de DeepSeek en cada request de la carga —igual
que `/api/chat/message` quedó excluido de la carga k6 del frontend— gastando
tokens reales sin importar el entorno. `tests/load/stub_server.py` imita las
dos dependencias externas (DeepSeek y el ERP) con respuestas fijas, así el
k6 mide la capacidad real del worker FastAPI (validación, loop de
tool-calling, manejo de errores) sin costo de IA.

## Cómo correrlo

Tres procesos, en tres terminales separadas (PowerShell):

**1. Stub (DeepSeek + ERP simulados) en :9000**
```powershell
.\venv\Scripts\python.exe -m uvicorn tests.load.stub_server:app --port 9000
```

**2. Motor real en :8001, apuntando al stub**
```powershell
$env:DEEPSEEK_API_URL = "http://127.0.0.1:9000/v1/chat/completions"
$env:DEEPSEEK_API_KEY = "k6-fake-key"
$env:INTERNAL_SECRET  = "k6-load-secret"
.\venv\Scripts\python.exe -m uvicorn main:app --port 8001
```

**3. k6**
```powershell
$env:BASE_URL = "http://127.0.0.1:8001"
$env:INTERNAL_SECRET = "k6-load-secret"
$env:ERP_URL = "http://127.0.0.1:9000/erp/articulos"
k6 run tests/load/motor-ia.k6.js
```

## Diseño del script

Mismos 4 escenarios secuenciales que la carga k6 del frontend
(`Front-AgenteX-/src/test/load/frontend-api.k6.js`): 10 VUs, 50 VUs, 100 VUs
constantes (30s cada uno) y un escenario de estrés con rampa 0→200 VUs, que
se auto-aborta si `http_req_failed{scenario:escenario_estres}` supera 5%
sostenido. Cada iteración hace el flujo más caro posible del motor: un
request con `allowed_tools` activo, que fuerza 2 round-trips al stub de
DeepSeek + 1 al stub de ERP (el stub responde `tool_calls` en el primer
turno y la respuesta final en el segundo, ver `stub_server.py`).

## Resultado de la corrida real (2026-06-20, Windows local)

```
THRESHOLDS
  http_req_duration   ✗ p(95)<300    -> p(95)=57.75s
  http_req_failed     ✗ rate<0.05    -> rate=14.94%
  http_req_failed{scenario:escenario_estres} ✗ rate<0.05 -> rate=100.00%

TOTAL RESULTS
  checks_succeeded: 100% (148/148 — todo lo que SÍ completó fue correcto)
  http_req_duration: avg=30.18s  p(90)=55.72s  p(95)=57.75s
  iterations: 74 completas, 284 interrumpidas por el abort del escenario de estrés
```

El test abortó dentro del escenario de estrés (~161/200 VUs) por el
threshold de error rate. **No es un problema de la API de DeepSeek ni del
ERP** (son stubs locales triviales) — es un cuello de botella real del
propio microservicio bajo concurrencia. Ver hallazgo de performance
documentado en `CONTEXTO_TESTING_AGENTEX.md` (sección 2.1, Capa 7): cada
llamada saliente (`main.py` a DeepSeek, `tools.py` al ERP) abre un
`httpx.AsyncClient()` nuevo en vez de reusar uno compartido, lo que bajo
alta concurrencia generó una tormenta de apertura/cierre de sockets — visible
en los logs del motor como `ConnectionResetError` repetidos en
`_ProactorBasePipeTransport._call_connection_lost` (bug conocido de
asyncio + Proactor event loop en Windows ante alta tasa de conexiones
efímeras).
