CREATE TABLE IF NOT EXISTS recommendations (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  ticker VARCHAR(20) NOT NULL,
  recommended_price INTEGER NOT NULL,
  recommendation_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO recommendations
  (name, ticker, recommended_price, recommendation_date)
VALUES
  (
    'LG에너지솔루션',
    '373220',
    450000,
    '2026-04-28'
  ),
  (
    'LS',
    '006260',
    320000,
    '2026-03-19'
  ),
  (
    '한국금융지주',
    '071050',
    110000,
    '2026-02-12'
  ),
  (
    'HD현대일렉트릭',
    '267260',
    450000,
    '2026-01-30'
  ),
  (
    '삼성전자',
    '005930',
    85000,
    '2026-01-15'
  );
