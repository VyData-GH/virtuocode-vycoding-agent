-- =========================================
-- 1) DASHBOARD SUMMARY
-- =========================================
CREATE OR REPLACE VIEW dashboard_summary AS
SELECT 
    t.tasks_id AS task_id,
    t.title,
    t.monday_status,
    t.internal_status,
    t.priority,
    t.created_at,
    tr.status AS last_run_status,
    tr.current_node,
    tr.progress_percentage,
    pr.github_pr_url,
    pr.pr_status
FROM tasks t
LEFT JOIN LATERAL (
    SELECT * FROM task_runs r
    WHERE r.task_id = t.tasks_id
    ORDER BY r.started_at DESC
    LIMIT 1
) tr ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM pull_requests p
    WHERE p.task_id = t.tasks_id
    ORDER BY p.created_at DESC
    LIMIT 1
) pr ON TRUE
ORDER BY t.created_at DESC;

-- =========================================
-- 2) PERFORMANCE DASHBOARD
-- =========================================
CREATE OR REPLACE VIEW performance_dashboard AS
SELECT 
    DATE_TRUNC('day', t.created_at) AS date,
    COUNT(t.tasks_id) AS total_tasks,
    COUNT(*) FILTER (WHERE tr.status = 'completed') AS completed_tasks,
    COUNT(*) FILTER (WHERE tr.status = 'failed') AS failed_tasks,
    AVG(pm.total_duration_seconds) AS avg_duration,
    AVG(pm.total_ai_cost) AS avg_cost,
    AVG(pm.test_coverage_final) AS avg_coverage
FROM tasks t
LEFT JOIN LATERAL (
    SELECT * FROM task_runs r
    WHERE r.task_id = t.tasks_id
    ORDER BY r.started_at DESC
    LIMIT 1
) tr ON TRUE
LEFT JOIN performance_metrics pm ON pm.task_id = t.tasks_id
GROUP BY 1
ORDER BY 1 DESC;

-- =========================================
-- 3) VUES MATÉRIALISÉES SUPPLÉMENTAIRES
-- =========================================

-- A. Dashboard stats (dernier 7 jours)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dashboard_stats AS
SELECT 
    DATE_TRUNC('hour', created_at) AS hour_bucket,
    internal_status,
    COUNT(*) AS task_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) AS avg_duration_seconds
FROM tasks 
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2;

CREATE UNIQUE INDEX ON mv_dashboard_stats(hour_bucket, internal_status);

-- B. Monitoring temps réel
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_realtime_monitoring AS
SELECT 
    internal_status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (NOW() - started_at))/60) as avg_minutes_since_start
FROM tasks 
WHERE internal_status IN ('pending', 'processing', 'testing', 'debugging')
GROUP BY internal_status;

CREATE UNIQUE INDEX ON mv_realtime_monitoring(internal_status);

-- C. Analyse des coûts AI
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_cost_analysis AS
SELECT 
    DATE_TRUNC('day', recorded_at) as day,
    ai_provider,
    model_name,
    SUM(total_ai_cost) as daily_cost,
    COUNT(*) as runs_count,
    AVG(total_tokens_used) as avg_tokens
FROM performance_metrics pm
JOIN task_runs tr ON tr.tasks_runs_id = pm.task_run_id
WHERE recorded_at >= NOW() - INTERVAL '30 days'
GROUP BY 1, 2, 3;

CREATE UNIQUE INDEX ON mv_cost_analysis(day, ai_provider, model_name);

-- =========================================
-- 4) FONCTION D'AUDIT ET MONITORING
-- =========================================
CREATE OR REPLACE FUNCTION health_check() RETURNS TABLE(
    metric_name TEXT,
    metric_value NUMERIC,
    status TEXT
) AS $$
BEGIN
    -- Tâches en attente trop longtemps
    RETURN QUERY
    SELECT 'pending_tasks_old' as metric_name,
           COUNT(*)::NUMERIC as metric_value,
           CASE WHEN COUNT(*) > 100 THEN 'WARNING' ELSE 'OK' END as status
    FROM tasks 
    WHERE internal_status = 'pending' 
      AND created_at < NOW() - INTERVAL '1 hour';
    
    -- Utilisation de l'espace disque
    RETURN QUERY
    SELECT 'database_size_mb' as metric_name,
           pg_database_size(current_database())::NUMERIC / 1024 / 1024 as metric_value,
           'INFO' as status;
    
    -- Taux de succès des 24 dernières heures
    RETURN QUERY
    SELECT 'success_rate_24h' as metric_name,
           (COUNT(*) FILTER (WHERE tr.status = 'completed')::NUMERIC / NULLIF(COUNT(*), 0) * 100) as metric_value,
           CASE 
               WHEN (COUNT(*) FILTER (WHERE tr.status = 'completed')::NUMERIC / NULLIF(COUNT(*), 0) * 100) < 80 
               THEN 'WARNING' 
               ELSE 'OK' 
           END as status
    FROM tasks t
    LEFT JOIN task_runs tr ON tr.task_id = t.tasks_id AND tr.tasks_runs_id = t.last_run_id
    WHERE t.created_at >= NOW() - INTERVAL '24 hours';
    
END;
$$ LANGUAGE plpgsql;
