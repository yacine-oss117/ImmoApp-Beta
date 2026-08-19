-- SigNoz local/dev retention hard cap: 15 minutes.
-- Applied by compose service `signoz-retention-init`.

ALTER TABLE signoz_analytics.rule_state_history_v0
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);

ALTER TABLE signoz_logs.logs_attribute_keys
    MODIFY TTL timestamp + toIntervalMinute(15);
ALTER TABLE signoz_logs.logs_resource_keys
    MODIFY TTL timestamp + toIntervalMinute(15);
ALTER TABLE signoz_logs.logs_v2
    MODIFY TTL toDateTime(timestamp / 1000000000) + toIntervalMinute(15);
ALTER TABLE signoz_logs.logs_v2_resource
    MODIFY TTL toDateTime(seen_at_ts_bucket_start) + toIntervalMinute(15);
ALTER TABLE signoz_logs.tag_attributes_v2
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_logs.usage
    MODIFY TTL timestamp + toIntervalMinute(15);

ALTER TABLE signoz_metadata.attributes_metadata
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);

ALTER TABLE signoz_meter.samples
    MODIFY TTL toDateTime(intDiv(unix_milli, 1000)) + toIntervalMinute(15);
ALTER TABLE signoz_meter.samples_agg_1d
    MODIFY TTL toDateTime(intDiv(unix_milli, 1000)) + toIntervalMinute(15);

ALTER TABLE signoz_metrics.exp_hist
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.metadata
    MODIFY TTL toDateTime(last_reported_unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.samples_v2
    MODIFY TTL toDateTime(timestamp_ms / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.samples_v4
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.samples_v4_agg_30m
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.samples_v4_agg_5m
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.time_series_v4
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.time_series_v4_1day
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.time_series_v4_1week
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.time_series_v4_6hrs
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_metrics.usage
    MODIFY TTL timestamp + toIntervalMinute(15);

ALTER TABLE signoz_traces.dependency_graph_minutes_v2
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.durationSort
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.signoz_error_index_v2
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.signoz_index_v2
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.signoz_index_v3
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.signoz_spans
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.span_attributes
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
ALTER TABLE signoz_traces.span_attributes_keys
    MODIFY TTL timestamp + toIntervalMinute(15);
ALTER TABLE signoz_traces.tag_attributes_v2
    MODIFY TTL toDateTime(unix_milli / 1000) + toIntervalMinute(15);
ALTER TABLE signoz_traces.top_level_operations
    MODIFY TTL time + toIntervalMinute(15);
ALTER TABLE signoz_traces.trace_summary
    MODIFY TTL toDateTime(end) + toIntervalMinute(15);
ALTER TABLE signoz_traces.traces_v3_resource
    MODIFY TTL toDateTime(seen_at_ts_bucket_start) + toIntervalMinute(15);
ALTER TABLE signoz_traces.usage
    MODIFY TTL timestamp + toIntervalMinute(15);
ALTER TABLE signoz_traces.usage_explorer
    MODIFY TTL toDateTime(timestamp) + toIntervalMinute(15);
