# TradeBot Backend

Flask + APScheduler trading bot backend. Deploys free on Render.com.

## Structure
```
tradebot-backend/
├── app.py                   ← Flask entry point
├── Procfile                 ← Render.com start command
├── requirements.txt
├── .env.example             ← Copy to .env and fill keys
├── services/
│   ├── ta_engine.py         ← RSI, MACD, EMA, Bollinger Bands
│   ├── broker.py            ← Alpaca / Binance / OANDA + paper trading
│   └── scheduler.py         ← Runs analysis every 30s, monitors SL/TP
└── routes/
    ├── signals.py           ← GET  /signals?market=ALL
    ├── trades.py            ← GET  /trades/active  /trades/history
    │                           POST /trades/open  /trades/close-all
    ├── portfolio.py         ← GET  /portfolio
    ├── backtest.py          ← POST /backtest
    ├── alerts.py            ← GET  /alerts/pending
    └── config.py            ← POST /config  /config/bot
```

## Run Locally
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your API keys
python app.py
```
Test at: http://localhost:5000

## Deploy to Render.com (free)
1. Push this folder to a GitHub repo
2. Go to render.com → New → Web Service
3. Connect your repo
4. Set Build Command: `pip install -r requirements.txt`
5. Set Start Command: `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT`
6. Add environment variables from .env.example
7. Deploy → copy your URL → paste into Android app Settings

## API Endpoints

| Method | Endpoint              | Description                    |
|--------|-----------------------|--------------------------------|
| GET    | /                     | Health check                   |
| GET    | /signals?market=ALL   | All TA signals (cached)        |
| GET    | /signals/BTC-USDT     | Single symbol signal           |
| GET    | /trades/active        | Open trades + live PnL         |
| GET    | /trades/history       | Closed trade history           |
| POST   | /trades/open          | Manually open a trade          |
| POST   | /trades/close-all     | Close all open trades          |
| GET    | /portfolio            | Balance, PnL, equity curve     |
| POST   | /backtest             | Run backtest on a symbol       |
| GET    | /alerts/pending       | Pending alerts (clears on read)|
| POST   | /config               | Update strategy config         |
| POST   | /config/bot           | Enable/disable bot             |

## No API Keys?
The bot works out of the box with:
- **Crypto prices**: Binance public API (no key needed)
- **Paper trading**: Simulated orders stored in memory
- **Forex/Stocks**: Synthetic data (realistic, for testing)

Add real keys in .env when ready for live trading.
