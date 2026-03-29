# app/routes/monitor.py
"""
Server monitoring dashboard and metrics API
"""
import time
import logging
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from app.cache.redis_manager import get_redis
from app.services.websocket_service import connection_manager
from db.db_manager import get_database
import os

logger = logging.getLogger(__name__)
router = APIRouter()

START_TIME = time.time()


@router.get("/monitor/api")
async def monitor_api():
    """Lightweight metrics JSON for the dashboard (no auth)"""
    try:
        redis = get_redis()
        db = get_database()

        # Global counters
        total_requests = await redis.redis.get("metrics:total_requests") if redis.redis else None
        active_requests = await redis.redis.get("metrics:active_requests") if redis.redis else None
        total_errors = await redis.redis.get("metrics:errors:total") if redis.redis else None

        total_requests = int(total_requests or 0)
        active_requests = max(int(active_requests or 0), 0)
        total_errors = int(total_errors or 0)
        error_rate = round((total_errors / max(total_requests, 1)) * 100, 2)

        # Per-endpoint request counts
        endpoint_counts = {}
        if redis.redis:
            async for key in redis.redis.scan_iter(match="metrics:requests:*"):
                k = key.decode() if isinstance(key, bytes) else key
                val = await redis.redis.get(key)
                endpoint = k.replace("metrics:requests:", "")
                endpoint_counts[endpoint] = int(val or 0)

        # Sort by count, top 15
        top_endpoints = sorted(endpoint_counts.items(), key=lambda x: x[1], reverse=True)[:15]

        # Status code distribution
        status_dist = {}
        if redis.redis:
            for code in ["200", "201", "204", "301", "400", "401", "403", "404", "422", "429", "500", "502", "503"]:
                val = await redis.redis.get(f"metrics:status:{code}")
                if val and int(val) > 0:
                    status_dist[code] = int(val)

        # Average response times (from timing lists)
        avg_times = {}
        if redis.redis:
            async for key in redis.redis.scan_iter(match="metrics:timing:*"):
                k = key.decode() if isinstance(key, bytes) else key
                endpoint = k.replace("metrics:timing:", "")
                durations = await redis.redis.lrange(key, 0, 99)
                if durations:
                    nums = [float(d) for d in durations]
                    avg_times[endpoint] = round(sum(nums) / len(nums), 3)

        # Overall avg response time
        all_durations = list(avg_times.values())
        overall_avg = round(sum(all_durations) / max(len(all_durations), 1), 3) if all_durations else 0

        # Slow requests today
        slow_key = f"slow_requests:{datetime.utcnow().strftime('%Y-%m-%d')}"
        slow_requests = []
        if redis.redis:
            try:
                raw = await redis.redis.zrevrange(slow_key, 0, 9, withscores=True)
                slow_requests = [
                    {"endpoint": (r[0].decode() if isinstance(r[0], bytes) else r[0]), "duration": round(r[1], 3)}
                    for r in raw
                ]
            except Exception:
                pass

        # WebSocket connections
        ws_total = connection_manager.get_total_connections()
        ws_by_role = {
            role: connection_manager.get_role_connections_count(role)
            for role in ["customer", "delivery_partner", "admin"]
        }

        # Business stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        users_count = await db.count_documents("users", {})
        orders_today = await db.count_documents("orders", {"created_at": {"$gte": today_start}})

        revenue_pipeline = [
            {"$match": {"created_at": {"$gte": today_start}, "order_status": {"$nin": ["cancelled", "refunded"]}}},
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
        ]
        rev_result = await db.aggregate("orders", revenue_pipeline)
        revenue_today = round(rev_result[0]["total"], 2) if rev_result else 0

        # Uptime
        uptime_sec = int(time.time() - START_TIME)
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        return {
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec,
            "environment": os.getenv("ENVIRONMENT", "Development"),
            "total_requests": total_requests,
            "active_requests": active_requests,
            "total_errors": total_errors,
            "error_rate": error_rate,
            "avg_response_time": overall_avg,
            "top_endpoints": [{"endpoint": e, "count": c} for e, c in top_endpoints],
            "status_distribution": status_dist,
            "avg_times": dict(sorted(avg_times.items(), key=lambda x: x[1], reverse=True)[:10]),
            "slow_requests": slow_requests,
            "websocket": {"total": ws_total, "by_role": ws_by_role},
            "business": {
                "users_total": users_count,
                "orders_today": orders_today,
                "revenue_today": revenue_today,
            },
        }
    except Exception as e:
        logger.error(f"Monitor API error: {e}")
        return {"error": str(e)}


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_dashboard():
    """Self-contained HTML monitoring dashboard"""
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SmartBag Server Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .header { background: #1e293b; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
  .header h1 { font-size: 22px; font-weight: 700; }
  .header h1 span { color: #3b82f6; }
  .status { display: flex; align-items: center; gap: 12px; font-size: 14px; color: #94a3b8; }
  .status .dot { width: 10px; height: 10px; border-radius: 50%; background: #22c55e; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 24px; }
  .card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
  .card-title { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #64748b; margin-bottom: 8px; }
  .card-value { font-size: 32px; font-weight: 700; color: #f8fafc; }
  .card-sub { font-size: 12px; color: #64748b; margin-top: 4px; }
  .card-value.blue { color: #3b82f6; }
  .card-value.green { color: #22c55e; }
  .card-value.red { color: #ef4444; }
  .card-value.amber { color: #f59e0b; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #64748b; border-bottom: 1px solid #334155; }
  td { padding: 10px 12px; font-size: 13px; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #334155; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-green { background: #052e16; color: #22c55e; }
  .badge-red { background: #450a0a; color: #ef4444; }
  .badge-blue { background: #172554; color: #3b82f6; }
  .badge-amber { background: #451a03; color: #f59e0b; }
  .chart-container { position: relative; height: 280px; }
  .ws-grid { display: flex; gap: 16px; margin-top: 12px; }
  .ws-item { flex: 1; text-align: center; background: #0f172a; border-radius: 8px; padding: 12px; }
  .ws-item .num { font-size: 24px; font-weight: 700; color: #3b82f6; }
  .ws-item .lbl { font-size: 11px; color: #64748b; margin-top: 4px; }
  @media (max-width: 900px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } .grid-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="header">
  <h1><span>SmartBag</span> Server Monitor</h1>
  <div class="status">
    <div class="dot" id="statusDot"></div>
    <span id="statusText">Connecting...</span>
    <span id="envBadge" class="badge badge-blue">--</span>
    <span id="uptimeText" style="margin-left:8px;">--</span>
  </div>
</div>
<div class="container">
  <!-- KPI Cards -->
  <div class="grid-4">
    <div class="card">
      <div class="card-title">Total Requests</div>
      <div class="card-value blue" id="totalReqs">--</div>
      <div class="card-sub">Since server start</div>
    </div>
    <div class="card">
      <div class="card-title">Active Now</div>
      <div class="card-value green" id="activeReqs">--</div>
      <div class="card-sub">Concurrent requests</div>
    </div>
    <div class="card">
      <div class="card-title">Error Rate</div>
      <div class="card-value red" id="errorRate">--</div>
      <div class="card-sub" id="errorCount">0 errors</div>
    </div>
    <div class="card">
      <div class="card-title">Avg Response Time</div>
      <div class="card-value amber" id="avgTime">--</div>
      <div class="card-sub">Across all endpoints</div>
    </div>
  </div>

  <!-- Charts -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title">Requests by Endpoint</div>
      <div class="chart-container"><canvas id="endpointChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Status Code Distribution</div>
      <div class="chart-container"><canvas id="statusChart"></canvas></div>
    </div>
  </div>

  <!-- Tables & Stats -->
  <div class="grid-3">
    <div class="card">
      <div class="card-title">Slowest Endpoints Today</div>
      <table>
        <thead><tr><th>Endpoint</th><th>Duration</th></tr></thead>
        <tbody id="slowTable"></tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">Avg Response Times</div>
      <table>
        <thead><tr><th>Endpoint</th><th>Avg (s)</th></tr></thead>
        <tbody id="avgTable"></tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">Live Connections</div>
      <div class="ws-grid">
        <div class="ws-item"><div class="num" id="wsTotal">0</div><div class="lbl">Total</div></div>
        <div class="ws-item"><div class="num" id="wsCustomer">0</div><div class="lbl">Customers</div></div>
        <div class="ws-item"><div class="num" id="wsAdmin">0</div><div class="lbl">Admins</div></div>
        <div class="ws-item"><div class="num" id="wsDelivery">0</div><div class="lbl">Delivery</div></div>
      </div>
      <div style="margin-top:24px">
        <div class="card-title">Business Stats (Today)</div>
        <table>
          <tbody id="bizTable"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<script>
let endpointChart, statusChart;

function initCharts() {
  const common = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } } };
  endpointChart = new Chart(document.getElementById('endpointChart'), {
    type: 'bar',
    data: { labels: [], datasets: [{ label: 'Requests', data: [], backgroundColor: '#3b82f6', borderRadius: 4 }] },
    options: { ...common, indexAxis: 'y', scales: { x: { ticks: { color: '#64748b' }, grid: { color: '#1e293b' } }, y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } } }, plugins: { ...common.plugins, legend: { display: false } } }
  });
  statusChart = new Chart(document.getElementById('statusChart'), {
    type: 'doughnut',
    data: { labels: [], datasets: [{ data: [], backgroundColor: ['#22c55e','#3b82f6','#f59e0b','#ef4444','#8b5cf6'], borderWidth: 0 }] },
    options: { ...common, cutout: '65%', plugins: { ...common.plugins, legend: { position: 'right' } } }
  });
}

function fmt(n) { return n >= 1000 ? (n/1000).toFixed(1) + 'k' : n.toString(); }

async function fetchMetrics() {
  try {
    const res = await fetch('/monitor/api');
    const d = await res.json();
    if (d.error) { document.getElementById('statusText').textContent = 'Error'; return; }

    document.getElementById('statusDot').style.background = '#22c55e';
    document.getElementById('statusText').textContent = 'Online';
    document.getElementById('envBadge').textContent = d.environment;
    document.getElementById('uptimeText').textContent = d.uptime;
    document.getElementById('totalReqs').textContent = fmt(d.total_requests);
    document.getElementById('activeReqs').textContent = d.active_requests;
    document.getElementById('errorRate').textContent = d.error_rate + '%';
    document.getElementById('errorCount').textContent = d.total_errors + ' errors total';
    document.getElementById('avgTime').textContent = d.avg_response_time + 's';

    // Endpoint chart
    const ep = d.top_endpoints.slice(0, 10);
    endpointChart.data.labels = ep.map(e => e.endpoint.length > 30 ? e.endpoint.slice(0,30)+'...' : e.endpoint);
    endpointChart.data.datasets[0].data = ep.map(e => e.count);
    endpointChart.update('none');

    // Status chart
    const st = d.status_distribution;
    const statusLabels = Object.keys(st);
    const statusColors = statusLabels.map(c => {
      const n = parseInt(c);
      if (n < 300) return '#22c55e';
      if (n < 400) return '#3b82f6';
      if (n < 500) return '#f59e0b';
      return '#ef4444';
    });
    statusChart.data.labels = statusLabels.map(c => c + ' (' + st[c] + ')');
    statusChart.data.datasets[0].data = Object.values(st);
    statusChart.data.datasets[0].backgroundColor = statusColors;
    statusChart.update('none');

    // Slow requests table
    const slowTb = document.getElementById('slowTable');
    slowTb.innerHTML = d.slow_requests.length ? d.slow_requests.map(r =>
      `<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.endpoint}</td><td><span class="badge badge-red">${r.duration}s</span></td></tr>`
    ).join('') : '<tr><td colspan="2" style="color:#64748b">No slow requests today</td></tr>';

    // Avg times table
    const avgTb = document.getElementById('avgTable');
    const avgEntries = Object.entries(d.avg_times).slice(0, 8);
    avgTb.innerHTML = avgEntries.length ? avgEntries.map(([ep, t]) =>
      `<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${ep}</td><td><span class="badge ${t > 1 ? 'badge-red' : t > 0.5 ? 'badge-amber' : 'badge-green'}">${t}s</span></td></tr>`
    ).join('') : '<tr><td colspan="2" style="color:#64748b">No data yet</td></tr>';

    // WebSocket
    document.getElementById('wsTotal').textContent = d.websocket.total;
    document.getElementById('wsCustomer').textContent = d.websocket.by_role.customer || 0;
    document.getElementById('wsAdmin').textContent = d.websocket.by_role.admin || 0;
    document.getElementById('wsDelivery').textContent = d.websocket.by_role.delivery_partner || 0;

    // Business
    const biz = d.business;
    document.getElementById('bizTable').innerHTML = `
      <tr><td>Total Users</td><td style="font-weight:700;color:#3b82f6">${fmt(biz.users_total)}</td></tr>
      <tr><td>Orders Today</td><td style="font-weight:700;color:#22c55e">${biz.orders_today}</td></tr>
      <tr><td>Revenue Today</td><td style="font-weight:700;color:#f59e0b">Rs ${biz.revenue_today.toLocaleString()}</td></tr>
    `;
  } catch (e) {
    document.getElementById('statusDot').style.background = '#ef4444';
    document.getElementById('statusText').textContent = 'Offline';
  }
}

initCharts();
fetchMetrics();
setInterval(fetchMetrics, 5000);
</script>
</body>
</html>"""
