import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Search, TrendingUp } from "lucide-react";
import "./styles.css";

type Recommendation = {
  id: number;
  name: string;
  ticker: string;
  reason: string;
  currentPrice: number;
  recommendedPrice: number;
  recommendationDate: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatGain(item: Recommendation) {
  const diff = item.currentPrice - item.recommendedPrice;
  const rate = (diff / item.recommendedPrice) * 100;
  return {
    diff,
    rate: rate.toFixed(2),
  };
}

function App() {
  const [items, setItems] = useState<Recommendation[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    fetch(`${apiBaseUrl}/api/recommendations`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("추천 종목을 불러오지 못했습니다.");
        }
        return response.json();
      })
      .then((data: Recommendation[]) => {
        setItems(data);
        setErrorMessage("");
      })
      .catch((error: Error) => {
        setErrorMessage(error.message);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return items;
    }

    return items.filter((item) => {
      return (
        item.name.toLowerCase().includes(keyword) ||
        item.ticker.toLowerCase().includes(keyword) ||
        item.reason.toLowerCase().includes(keyword)
      );
    });
  }, [items, query]);

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">KT</span>
          <span>cloud demo</span>
        </div>
        <nav>
          <a>Cloud</a>
          <a>Platform</a>
          <a className="active">Demo Service</a>
          <a>Architecture</a>
          <a>Support</a>
        </nav>
      </header>

      <section className="subnav">
        <span>서비스 데모</span>
        <span>API Gateway</span>
        <span>Private Backend</span>
        <strong>주식 추천 서비스</strong>
      </section>

      <section className="content">
        <div className="titleRow">
          <div>
            <p className="eyebrow">KT Cloud Demo Architecture</p>
            <h1>대형주 추천종목</h1>
          </div>
          <label className="searchBox">
            <Search size={18} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="종목명, 코드, 추천사유 검색"
            />
          </label>
        </div>

        <div className="notice">
          <strong>Public Web, Private Backend, Private DB 구조를 보여주는 데모 화면입니다.</strong>
          <p>아래 추천 종목은 서비스 흐름 확인을 위한 임시 샘플 데이터입니다.</p>
        </div>

        {isLoading && <div className="state">추천 종목을 불러오는 중입니다.</div>}
        {errorMessage && <div className="state error">{errorMessage}</div>}

        {!isLoading && !errorMessage && (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>종목</th>
                  <th>추천사유</th>
                  <th>현재가(원)</th>
                  <th>추천가(원)</th>
                  <th>추천가대비</th>
                  <th>추천일</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => {
                  const gain = formatGain(item);
                  return (
                    <tr key={item.id}>
                      <td>
                        <div className="stockName">{item.name}</div>
                        <div className="ticker">({item.ticker})</div>
                      </td>
                      <td>{item.reason}</td>
                      <td>{formatCurrency(item.currentPrice)}</td>
                      <td>{formatCurrency(item.recommendedPrice)}</td>
                      <td className="gain">
                        <TrendingUp size={15} />
                        {formatCurrency(gain.diff)} ({gain.rate}%)
                      </td>
                      <td>{item.recommendationDate}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
