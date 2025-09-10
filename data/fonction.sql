-- =========================================
-- 1) FONCTION DE NETTOYAGE AUTOMATIQUE
-- =========================================
CREATE OR REPLACE FUNCTION cleanup_old_logs() RETURNS void AS $$
BEGIN
    -- Suppression des anciens webhooks et logs
    DELETE FROM webhook_events WHERE received_at < NOW() - INTERVAL '6 months';
    DELETE FROM application_logs WHERE ts < NOW() - INTERVAL '3 months';
END;
$$ LANGUAGE plpgsql;

-- =========================================
-- 2) TRIGGER GÉNÉRIQUE POUR updated_at
-- =========================================
CREATE OR REPLACE FUNCTION trg_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    -- Trigger pour tasks
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'touch_tasks_updated_at'
    ) THEN
        CREATE TRIGGER touch_tasks_updated_at
        BEFORE UPDATE ON tasks
        FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();
    END IF;

    -- Trigger pour system_config
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'touch_system_config_updated_at'
    ) THEN
        CREATE TRIGGER touch_system_config_updated_at
        BEFORE UPDATE ON system_config
        FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();
    END IF;
END $$;

-- =========================================
-- 3) TRIGGERS CRITIQUES POUR TASKS / RUNS
-- =========================================

-- A. Synchroniser last_run_id
CREATE OR REPLACE FUNCTION sync_task_last_run() RETURNS TRIGGER AS $$
BEGIN
    UPDATE tasks 
    SET last_run_id = NEW.tasks_runs_id,
        updated_at = NOW()
    WHERE tasks_id = NEW.task_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_sync_task_last_run
    AFTER INSERT OR UPDATE ON task_runs
    FOR EACH ROW 
    EXECUTE FUNCTION sync_task_last_run();

-- B. Calculer automatiquement la durée
CREATE OR REPLACE FUNCTION calculate_duration() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.completed_at IS NOT NULL AND OLD.completed_at IS NULL THEN
        NEW.duration_seconds = EXTRACT(EPOCH FROM (NEW.completed_at - NEW.started_at))::INTEGER;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_calculate_run_duration
    BEFORE UPDATE ON task_runs
    FOR EACH ROW 
    EXECUTE FUNCTION calculate_duration();

CREATE OR REPLACE TRIGGER tr_calculate_step_duration
    BEFORE UPDATE ON run_steps
    FOR EACH ROW 
    EXECUTE FUNCTION calculate_duration();

-- C. Synchroniser le statut des tâches selon les runs
CREATE OR REPLACE FUNCTION sync_task_status() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status != 'completed') THEN
        UPDATE tasks 
        SET internal_status = 'completed',
            completed_at = NEW.completed_at,
            updated_at = NOW()
        WHERE tasks_id = NEW.task_id;

    ELSIF NEW.status = 'failed' THEN
        UPDATE tasks 
        SET internal_status = 'failed',
            updated_at = NOW()
        WHERE tasks_id = NEW.task_id
          AND last_run_id = NEW.tasks_runs_id;

    ELSIF NEW.status = 'running' AND (OLD.status IS NULL OR OLD.status = 'started') THEN
        UPDATE tasks 
        SET internal_status = 'processing',
            started_at = COALESCE(started_at, NEW.started_at),
            updated_at = NOW()
        WHERE tasks_id = NEW.task_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_sync_task_status
    AFTER UPDATE ON task_runs
    FOR EACH ROW 
    EXECUTE FUNCTION sync_task_status();

-- =========================================
-- 4) TRIGGERS DE VALIDATION
-- =========================================
CREATE OR REPLACE FUNCTION validate_status_transition() RETURNS TRIGGER AS $$
DECLARE
    valid_transitions JSONB := '{
        "pending": ["processing", "failed"],
        "processing": ["testing", "debugging", "completed", "failed"],
        "testing": ["quality_check", "debugging", "completed", "failed"],
        "debugging": ["testing", "completed", "failed"],
        "quality_check": ["completed", "failed"],
        "completed": [],
        "failed": ["pending", "processing"]
    }'::JSONB;
BEGIN
    IF OLD.internal_status IS NOT NULL AND 
       NOT (valid_transitions->OLD.internal_status ? NEW.internal_status) THEN
        RAISE EXCEPTION 'Invalid status transition from % to %', 
            OLD.internal_status, NEW.internal_status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_validate_task_status
    BEFORE UPDATE ON tasks
    FOR EACH ROW 
    EXECUTE FUNCTION validate_status_transition();

-- =========================================
-- 5) TRIGGERS D'AUDIT ET LOGGING
-- =========================================
CREATE OR REPLACE FUNCTION log_critical_changes() RETURNS TRIGGER AS $$
BEGIN
    IF TG_TABLE_NAME = 'tasks' AND OLD.internal_status != NEW.internal_status THEN
        INSERT INTO application_logs (
            task_id, level, source_component, action, message, metadata
        ) VALUES (
            NEW.tasks_id, 'INFO', 'trigger', 'status_change',
            format('Task status changed from %s to %s', OLD.internal_status, NEW.internal_status),
            jsonb_build_object(
                'old_status', OLD.internal_status,
                'new_status', NEW.internal_status,
                'task_title', NEW.title
            )
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_log_task_changes
    AFTER UPDATE ON tasks
    FOR EACH ROW 
    EXECUTE FUNCTION log_critical_changes();

-- =========================================
-- 6) MAINTENANCE AUTOMATIQUE
-- =========================================
CREATE OR REPLACE FUNCTION auto_cleanup() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'completed' THEN
        DELETE FROM task_runs 
        WHERE task_id = NEW.task_id 
          AND status IN ('completed', 'failed')
          AND tasks_runs_id NOT IN (
              SELECT tasks_runs_id FROM task_runs 
              WHERE task_id = NEW.task_id 
              ORDER BY started_at DESC 
              LIMIT 10
          );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tr_auto_cleanup
    AFTER UPDATE ON task_runs
    FOR EACH ROW 
    EXECUTE FUNCTION auto_cleanup();

-- =========================================
-- 7) OPTIMISATION & HEALTH CHECK
-- =========================================
CREATE OR REPLACE FUNCTION optimize_database() RETURNS void AS $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN 
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public' 
          AND tablename IN ('tasks', 'task_runs', 'run_steps', 'ai_interactions')
    LOOP
        EXECUTE format('ANALYZE %I', table_name);
    END LOOP;

    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_dashboard_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_realtime_monitoring;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_cost_analysis;

    INSERT INTO application_logs (level, source_component, action, message)
    VALUES ('INFO', 'maintenance', 'optimize_database', 'Database optimization completed');
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION health_check() RETURNS TABLE(
    metric_name TEXT,
    metric_value NUMERIC,
    status TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 'pending_tasks_old', COUNT(*)::NUMERIC,
           CASE WHEN COUNT(*) > 100 THEN 'WARNING' ELSE 'OK' END
    FROM tasks WHERE internal_status = 'pending' 
      AND created_at < NOW() - INTERVAL '1 hour';

    RETURN QUERY
    SELECT 'database_size_mb', pg_database_size(current_database())::NUMERIC / 1024 / 1024, 'INFO';

    RETURN QUERY
    SELECT 'success_rate_24h',
           (COUNT(*) FILTER (WHERE tr.status = 'completed')::NUMERIC / NULLIF(COUNT(*), 0) * 100),
           CASE WHEN (COUNT(*) FILTER (WHERE tr.status = 'completed')::NUMERIC / NULLIF(COUNT(*), 0) * 100) < 80 THEN 'WARNING' ELSE 'OK' END
    FROM tasks t
    LEFT JOIN task_runs tr ON tr.task_id = t.tasks_id AND tr.tasks_runs_id = t.last_run_id
    WHERE t.created_at >= NOW() - INTERVAL '24 hours';
END;
$$ LANGUAGE plpgsql;

-- =========================================
-- FONCTIONS UTILITAIRES POUR REFRESH AUTO
-- =========================================

CREATE OR REPLACE FUNCTION refresh_critical_views() RETURNS void AS $$
BEGIN
    -- Refresh des vues critiques pour le monitoring temps réel
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_workflow_status;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_integration_health;
    
    -- Log du refresh
    INSERT INTO application_logs (level, source_component, action, message)
    VALUES ('INFO', 'view_refresh', 'refresh_critical_views', 'Critical materialized views refreshed');
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION refresh_analytics_views() RETURNS void AS $$
BEGIN
    -- Refresh des vues analytiques (moins fréquent)
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_ai_efficiency;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_code_quality;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_executive_dashboard;
    
    INSERT INTO application_logs (level, source_component, action, message)
    VALUES ('INFO', 'view_refresh', 'refresh_analytics_views', 'Analytics materialized views refreshed');
END;
$$ LANGUAGE plpgsql;