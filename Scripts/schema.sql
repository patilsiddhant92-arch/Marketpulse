CREATE TABLE IF NOT EXISTS security_reference_daily (
    symbol TEXT,
    effective_date DATE,
    source_date DATE,
    market_cap_cr DOUBLE,
    pe DOUBLE,
    adjusted_pe DOUBLE,
    price_band DOUBLE,
    band_remarks TEXT,
    high_52w DOUBLE,
    high_52w_date DATE,
    low_52w DOUBLE,
    low_52w_date DATE,
    source_checksum TEXT,
    PRIMARY KEY (symbol, effective_date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    symbol TEXT,
    ex_date DATE,
    action_type TEXT,
    ratio_from DOUBLE,
    ratio_to DOUBLE,
    cash_amount DOUBLE,
    description TEXT,
    source_checksum TEXT,
    PRIMARY KEY (symbol, ex_date, action_type, description)
);

CREATE TABLE IF NOT EXISTS price_adjustment_factors (
    symbol TEXT,
    trade_date DATE,
    price_factor DOUBLE,
    volume_factor DOUBLE,
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    trade_date DATE,
    index_name TEXT,
    previous_close DOUBLE,
    open_price DOUBLE,
    high_price DOUBLE,
    low_price DOUBLE,
    close_price DOUBLE,
    change_value DOUBLE,
    return_1d_pct DOUBLE,
    PRIMARY KEY (trade_date, index_name)
);

CREATE TABLE IF NOT EXISTS security_events (
    symbol TEXT,
    event_date DATE,
    event_type TEXT,
    headline TEXT,
    source_id TEXT,
    source_checksum TEXT,
    PRIMARY KEY (symbol, event_date, event_type, source_id)
);

CREATE TABLE IF NOT EXISTS candidate_daily (
    trade_date DATE,
    symbol TEXT,
    score_version TEXT,
    candidate_state TEXT,
    leadership_score DOUBLE,
    setup_score DOUBLE,
    participation_score DOUBLE,
    context_score DOUBLE,
    risk_score DOUBLE,
    total_score DOUBLE,
    rank_overall INTEGER,
    rank_in_sector INTEGER,
    why_now TEXT,
    latest_change TEXT,
    risk_summary TEXT,
    trigger_price DOUBLE,
    invalidation_price DOUBLE,
    first_resistance DOUBLE,
    distance_to_trigger_pct DOUBLE,
    initial_risk_pct DOUBLE,
    reward_to_risk DOUBLE,
    setup_first_seen DATE,
    setup_age_sessions INTEGER,
    event_risk TEXT,
    data_quality_flags TEXT,
    trigger_type TEXT,
    invalidation_type TEXT,
    market_regime TEXT,
    sector_state TEXT,
    industry_state TEXT,
    market_cap_cr DOUBLE,
    avg_traded_value_cr_20d DOUBLE,
    sector TEXT,
    industry TEXT,
    eligibility_status TEXT,
    blocking_reasons TEXT,
    warning_reasons TEXT,
    geometry_valid BOOLEAN,
    PRIMARY KEY (trade_date, symbol, score_version)
);

CREATE TABLE IF NOT EXISTS watchlist_candidates (
    symbol TEXT,
    score_version TEXT,
    first_seen_date DATE,
    last_seen_date DATE,
    candidate_state TEXT,
    state_reason TEXT,
    trigger_price DOUBLE,
    invalidation_price DOUBLE,
    first_resistance DOUBLE,
    setup_first_seen DATE,
    setup_age_sessions INTEGER,
    state_history JSON,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (symbol, score_version, first_seen_date)
);

CREATE TABLE IF NOT EXISTS signal_ledger (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT,
    setup_type TEXT,
    score_version TEXT,
    first_seen_date DATE,
    last_seen_date DATE,
    trigger_date DATE,
    invalidation_date DATE,
    expiry_date DATE,
    status TEXT,
    initial_score DOUBLE,
    peak_score DOUBLE,
    trigger_price DOUBLE,
    invalidation_price DOUBLE,
    market_regime TEXT,
    sector_state TEXT,
    industry_state TEXT,
    feature_snapshot JSON,
    state_history JSON
);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    signal_id TEXT,
    horizon_sessions INTEGER,
    as_of_date DATE,
    forward_return_pct DOUBLE,
    max_favourable_excursion_pct DOUBLE,
    max_adverse_excursion_pct DOUBLE,
    trigger_to_invalidation_return_pct DOUBLE,
    time_to_trigger_sessions INTEGER,
    time_to_failure_sessions INTEGER,
    resolved BOOLEAN,
    PRIMARY KEY (signal_id, horizon_sessions, as_of_date)
);

CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id TEXT PRIMARY KEY,
    start_date DATE,
    end_date DATE,
    status TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    application_version TEXT,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS ingested_reports (
    trade_date DATE,
    report_type TEXT,
    source_checksum TEXT,
    row_count BIGINT,
    manifest_path TEXT,
    batch_id TEXT,
    PRIMARY KEY (trade_date, report_type)
);

CREATE INDEX IF NOT EXISTS idx_reference_symbol_date ON security_reference_daily(symbol, effective_date);
CREATE INDEX IF NOT EXISTS idx_index_date_name ON index_daily(trade_date, index_name);
CREATE INDEX IF NOT EXISTS idx_candidate_date_score ON candidate_daily(trade_date, score_version, total_score);
CREATE INDEX IF NOT EXISTS idx_watchlist_state ON watchlist_candidates(candidate_state, last_seen_date);
CREATE INDEX IF NOT EXISTS idx_signal_symbol_status ON signal_ledger(symbol, status, last_seen_date);
CREATE INDEX IF NOT EXISTS idx_outcomes_signal_date ON signal_outcomes(signal_id, as_of_date);
