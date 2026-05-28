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
    'LG이노텍',
    '011070',
    '26년 패키지 솔루션 영업이익 증가 예상, 광통신 패키징 기술 수혜',
    688000,
    577000,
    '2026-04-28'
  ),
  (
    'LS',
    '006260',
    'AI 전력 인프라 자회사 가치 반영 전망, 주요 계열사 장기 성장 기대',
    505000,
    290500,
    '2026-03-19'
  ),
  (
    '한국금융지주',
    '071050',
    '레버리지 확대를 통한 ROE 개선, 수신 기반 확대로 IB 부문 성장 기대',
    250000,
    246500,
    '2026-02-12'
  ),
  (
    'HD현대일렉트릭',
    '267260',
    '전력기기 수요 증가와 북미 인프라 투자 확대 수혜',
    1306000,
    351000,
    '2026-01-30'
  ),
  (
    '삼성전자',
    '005930',
    'AI 서버 수요 회복과 메모리 가격 개선 기대',
    275750,
    76500,
    '2026-01-15'
  );
