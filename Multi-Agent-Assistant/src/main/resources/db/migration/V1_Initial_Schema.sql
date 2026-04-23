
-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Favorite companies
CREATE TABLE favorite_companies (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, ticker)
);

-- Chat sessions
CREATE TABLE chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_ticker VARCHAR(10) NOT NULL,
    context_type VARCHAR(50),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    session_context TEXT,
    related_strategy_id INTEGER
);

-- Chat messages
CREATE TABLE chat_messages (
   id SERIAL PRIMARY KEY,
   session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
   sender VARCHAR(50) NOT NULL,
   message TEXT NOT NULL,
   intent VARCHAR(50),
   nci_snapshot DOUBLE PRECISION,
   confidence_score DOUBLE PRECISION,
   metadata JSON,
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User strategies
CREATE TABLE user_strategies (
   id SERIAL PRIMARY KEY,
   user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   company_ticker VARCHAR(10) NOT NULL,
   company_name VARCHAR(255) NOT NULL,
   user_argument TEXT NOT NULL,
   nci_global DOUBLE PRECISION,
   nci_personalized DOUBLE PRECISION,
   f_consistency DOUBLE PRECISION,
   support_evidence TEXT,
   red_flags TEXT,
   market_sentiment DOUBLE PRECISION,
   final_conclusion TEXT,
   pdf_path VARCHAR(255),
   is_active BOOLEAN DEFAULT true,
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
   last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Strategy update logs - HADI M3NDHA 3ALA9A B LA TABLE alert , hadi pour suivre la strategie de chque user
CREATE TABLE strategy_update_logs (
   id SERIAL PRIMARY KEY,
   user_strategy_id INTEGER NOT NULL REFERENCES user_strategies(id) ON DELETE CASCADE,
   previous_nci_personalized DOUBLE PRECISION,
   new_nci_personalized DOUBLE PRECISION,
   price_change_percent DOUBLE PRECISION,
   sentiment_change DOUBLE PRECISION,
   update_reason VARCHAR(255),
   alert_triggered BOOLEAN,
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Saved reports
CREATE TABLE saved_reports (
   id SERIAL PRIMARY KEY,
   user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   ticker VARCHAR(10) NOT NULL,
   user_argument TEXT,
   pdf_path VARCHAR(255),
   nci_personalized DOUBLE PRECISION,
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX idx_chat_sessions_company_ticker ON chat_sessions(company_ticker);
CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_user_strategies_user_id ON user_strategies(user_id);
CREATE INDEX idx_user_strategies_is_active ON user_strategies(is_active);
CREATE INDEX idx_strategy_updates_user_strategy_id ON strategy_update_logs(user_strategy_id);