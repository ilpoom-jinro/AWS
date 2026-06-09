CREATE TABLE IF NOT EXISTS recommendations (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  ticker VARCHAR(20) NOT NULL,
  current_price INTEGER NOT NULL,
  recommended_price INTEGER NOT NULL,
  recommendation_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO recommendations
  (name, ticker, current_price, recommended_price, recommendation_date)
VALUES
  (
    'LG에너지솔루션',
    '373220',
    450000,
    500000,
    CURRENT_DATE
  ),
  (
    'LS',
    '006260',
    320000,
    350000,
    CURRENT_DATE
  ),
  (
    '한국금융지주',
    '071050',
    110000,
    130000,
    CURRENT_DATE
  ),
  (
    'HD현대일렉트릭',
    '267260',
    450000,
    520000,
    CURRENT_DATE
  ),
  (
    '삼성전자',
    '005930',
    85000,
    95000,
    CURRENT_DATE
  );
