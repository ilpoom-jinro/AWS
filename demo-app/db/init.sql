CREATE TABLE IF NOT EXISTS recommendations (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  ticker VARCHAR(20) NOT NULL,
  reason TEXT NOT NULL,
  current_price INTEGER NOT NULL,
  recommended_price INTEGER NOT NULL,
  recommendation_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO recommendations
  (name, ticker, reason, current_price, recommended_price, recommendation_date)
VALUES
  (
    'LG Energy Solution',
    '011070',
    'Battery packaging demand and operating margin recovery are expected to improve.',
    688000,
    577000,
    '2026-04-28'
  ),
  (
    'LS',
    '006260',
    'AI power infrastructure demand may support long-term cable and equipment growth.',
    505000,
    290500,
    '2026-03-19'
  ),
  (
    'Korea Financial Group',
    '071050',
    'Capital efficiency and investment banking earnings are expected to recover.',
    250000,
    246500,
    '2026-02-12'
  ),
  (
    'HD Hyundai Electric',
    '267260',
    'Grid equipment demand and infrastructure investment remain favorable.',
    1306000,
    351000,
    '2026-01-30'
  ),
  (
    'Samsung Electronics',
    '005930',
    'AI server demand and memory pricing recovery may improve earnings.',
    275750,
    76500,
    '2026-01-15'
  );
