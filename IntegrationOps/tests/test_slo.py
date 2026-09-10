from datetime import datetime, timezone

def test_slo_endpoint_reports_targets(client):
    r=client.post('/api/integrations',json={'name':'SLO API','endpoint':'https://example.com/health','availability_target_pct':99.9,'p95_latency_target_ms':500})
    assert r.status_code==201
    iid=r.json()['id']
    body=client.get(f'/api/integrations/{iid}/slo').json()
    assert body['availability_target_pct']==99.9
    assert body['p95_latency_target_ms']==500
    assert body['checks']==0
