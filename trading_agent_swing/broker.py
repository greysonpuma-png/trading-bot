"""
Thin wrapper around the Alpaca Trading + Data APIs.

The same code works for paper and live — only the API keys and `paper=` flag change.
"""
import socket
# Set BEFORE constructing any HTTP clients below. alpaca-py has no built-in
# request timeout; without this, a stalled TCP connection hangs the bot's
# main loop indefinitely. Process-global, so Gemini and anything else that
# opens sockets in this process also get a sane default.
socket.setdefaulttimeout(60)

from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (MarketOrderRequest, TakeProfitRequest, StopLossRequest,
                                     TrailingStopOrderRequest)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import CONFIG


class Broker:
    def __init__(self):
        if not CONFIG.alpaca_api_key or not CONFIG.alpaca_secret_key:
            raise RuntimeError(
                "Alpaca credentials not set. Create a .env file from .env.example "
                "and add your paper trading keys from https://alpaca.markets"
            )
        self.trading = TradingClient(
            CONFIG.alpaca_api_key,
            CONFIG.alpaca_secret_key,
            paper=CONFIG.paper,
        )
        self.data = StockHistoricalDataClient(
            CONFIG.alpaca_api_key,
            CONFIG.alpaca_secret_key,
        )

    def get_account(self) -> dict:
        a = self.trading.get_account()
        return {
            "cash": float(a.cash),
            "equity": float(a.equity),
            "buying_power": float(a.buying_power),
            "daytrade_count": int(a.daytrade_count),
            "pattern_day_trader": bool(a.pattern_day_trader),
        }

    def get_positions(self) -> list:
        positions = self.trading.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]

    def get_quote(self, symbol: str) -> dict:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        resp = self.data.get_stock_latest_quote(req)
        q = resp[symbol]
        return {
            "symbol": symbol,
            "bid": float(q.bid_price),
            "ask": float(q.ask_price),
            "bid_size": int(q.bid_size),
            "ask_size": int(q.ask_size),
            "timestamp": q.timestamp.isoformat() if q.timestamp else None,
        }

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 30) -> list:
        tf_map = {
            "1Min":  TimeFrame.Minute,
            "5Min":  TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1Hour": TimeFrame.Hour,
            "1Day":  TimeFrame.Day,
            "1Week": TimeFrame.Week,
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)
        # Calendar days per bar so the start window is wide enough to hold `limit`
        # bars on each timeframe (otherwise weekly requests starve at 1.6 years).
        days_per_bar = {"1Min": 0.003, "5Min": 0.013, "15Min": 0.04,
                        "1Hour": 0.15, "1Day": 1, "1Week": 7}
        end = datetime.now()
        start = end - timedelta(days=max(int(limit * days_per_bar.get(timeframe, 1) * 2), 5))
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            limit=limit,
        )
        bars = self.data.get_stock_bars(req)
        return [
            {
                "timestamp": b.timestamp.isoformat(),
                "open":   float(b.open),
                "high":   float(b.high),
                "low":    float(b.low),
                "close":  float(b.close),
                "volume": int(b.volume),
            }
            for b in bars[symbol]
        ]

    def submit_order(self, symbol: str, qty: int, side: str) -> dict:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self.trading.submit_order(req)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": float(order.qty),
            "side": order.side.value,
            "status": order.status.value,
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        }

    def submit_bracket_order(self, symbol: str, qty: int, side: str,
                             stop_price: float, take_profit_price: float) -> dict:
        """Submit a BRACKET order: a market entry plus an automatic stop-loss leg
        and an automatic take-profit leg. The stop and target are held and enforced
        by Alpaca itself — they trigger even when this bot is offline or the Mac is
        asleep. Use this for entries (buys) so every position has built-in protection.
        """
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,          # GTC so the stop/target persist day-to-day
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(float(take_profit_price), 2)),
            stop_loss=StopLossRequest(stop_price=round(float(stop_price), 2)),
        )
        order = self.trading.submit_order(req)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": float(order.qty),
            "side": order.side.value,
            "status": order.status.value,
            "order_class": "bracket",
            "stop_price": round(float(stop_price), 2),
            "take_profit_price": round(float(take_profit_price), 2),
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        }

    def submit_trailing_entry(self, symbol: str, qty: int, side: str,
                              trail_percent: float) -> dict:
        """Market entry, then attach a server-side TRAILING-STOP sell once filled.

        The trailing stop lives at Alpaca and ratchets up with the position's
        high-water mark — protection survives bot crashes, just like brackets,
        but with no profit cap (cut losers, let winners run).

        Alpaca brackets cannot hold a trailing leg, so this is two orders. If the
        entry does not fill within ~30s it is cancelled — never leave a position
        unprotected or a stray sell order unbacked.
        """
        import time as _time

        entry_req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        entry = self.trading.submit_order(entry_req)

        filled = False
        for _ in range(15):                       # up to ~30s; market orders fill in ms
            o = self.trading.get_order_by_id(entry.id)
            if o.status.value == "filled":
                filled = True
                break
            _time.sleep(2)

        if not filled:
            self.trading.cancel_order_by_id(entry.id)
            return {
                "id": str(entry.id), "symbol": symbol, "qty": float(qty),
                "side": side, "status": "cancelled_unfilled",
                "error": "entry did not fill within 30s; cancelled to avoid an unprotected position",
            }

        trail_req = TrailingStopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,        # persists day-to-day at the broker
            trail_percent=round(float(trail_percent), 1),
        )
        trail = self.trading.submit_order(trail_req)

        return {
            "id": str(entry.id),
            "symbol": symbol,
            "qty": float(qty),
            "side": side,
            "status": "filled",
            "order_class": "trailing",
            "trail_percent": round(float(trail_percent), 1),
            "trail_order_id": str(trail.id),
            "submitted_at": entry.submitted_at.isoformat() if entry.submitted_at else None,
        }

    def close_all_positions(self) -> list:
        """Emergency kill-switch: flatten everything."""
        closed = self.trading.close_all_positions(cancel_orders=True)
        return [{"symbol": c.symbol, "status": c.status} for c in closed]

    def is_market_open(self) -> bool:
        return self.trading.get_clock().is_open

    def get_portfolio_history(self, period: str = "1M", timeframe: str = "1D") -> dict:
        """Account equity over time — used by the dashboard to benchmark against
        SPY buy-and-hold. Returns {'timestamp': [...], 'equity': [...]} or
        {'error': ...} on failure. Never raises.
        """
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest
            req = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
            h = self.trading.get_portfolio_history(req)
            ts = list(h.timestamp or [])
            eq = list(h.equity or [])
            pairs = [(int(t), float(e)) for t, e in zip(ts, eq) if e is not None]
            return {
                "timestamp": [p[0] for p in pairs],
                "equity":    [p[1] for p in pairs],
            }
        except Exception as e:
            return {"error": str(e)[:160]}

    def get_news(self, symbol: str, limit: int = 10, days_back: int = 14) -> list:
        """Recent news headlines for a symbol from Alpaca's news API.
        Returns an empty list (with an 'error' note) if the news endpoint isn't
        available or the call fails — never raises, so the agent can keep going.
        """
        try:
            from alpaca.data.historical.news import NewsClient
            from alpaca.data.requests import NewsRequest
        except ImportError:
            return [{"error": "news API not available in installed alpaca-py version"}]

        try:
            if not hasattr(self, "_news_client"):
                self._news_client = NewsClient(
                    CONFIG.alpaca_api_key,
                    CONFIG.alpaca_secret_key,
                )
            end = datetime.now()
            start = end - timedelta(days=max(days_back, 1))
            req = NewsRequest(
                symbols=symbol,
                start=start,
                end=end,
                limit=min(max(limit, 1), 50),
            )
            resp = self._news_client.get_news(req)
            items = getattr(resp, "news", None)
            if items is None and hasattr(resp, "data"):
                items = resp.data.get("news", []) if isinstance(resp.data, dict) else []
            items = items or []
            out = []
            for n in items:
                summary = (getattr(n, "summary", "") or "")
                out.append({
                    "headline":   getattr(n, "headline", ""),
                    "summary":    summary[:300],
                    "source":     getattr(n, "source", ""),
                    "created_at": getattr(n, "created_at", None).isoformat() if getattr(n, "created_at", None) else None,
                })
            return out
        except Exception as e:
            return [{"error": f"news fetch failed: {str(e)[:120]}"}]
