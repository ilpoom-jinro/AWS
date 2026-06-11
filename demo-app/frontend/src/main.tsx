import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Search, TrendingUp } from "lucide-react";
import "./styles.css";

type Recommendation = {
  id: number;
  name: string;
  ticker: string;
  currentPrice: number;
  recommendedPrice: number;
  recommendationDate: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatGain(item: Recommendation) {
  const diff = item.recommendedPrice - item.currentPrice;
  const rate = (diff / item.currentPrice) * 100;

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
          throw new Error("Failed to load recommendations.");
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
        item.ticker.toLowerCase().includes(keyword)
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
        <span>Service Demo</span>
        <span>API Gateway</span>
        <span>Private Backend</span>
        <strong>Stock Recommendation Service</strong>
      </section>

      <section className="content">
        <div className="titleRow">
          <div>
            <p className="eyebrow">KT Cloud Demo Architecture</p>
            <h1>Stock Recommendations</h1>
          </div>
          <label className="searchBox">
            <Search size={18} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name or ticker"
            />
          </label>
        </div>

        <div className="notice">
          <strong>
            This demo shows a public web tier, private backend, and private
            database flow.
          </strong>
          <p>
            The recommendation rows are seeded sample data for service
            deployment checks.
          </p>
        </div>

        {isLoading && <div className="state">Loading recommendations...</div>}
        {errorMessage && <div className="state error">{errorMessage}</div>}

        {!isLoading && !errorMessage && (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Current Price</th>
                  <th>Recommended Price</th>
                  <th>Upside</th>
                  <th>Recommendation Date</th>
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
                      <td>{formatCurrency(item.currentPrice)}원</td>
                      <td>{formatCurrency(item.recommendedPrice)}원</td>
                      <td className="gain">
                        <TrendingUp size={15} />
                        {formatCurrency(gain.diff)}원 ({gain.rate}%)
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
