"""
Swing trading config. All risk limits and credentials live here.

Larger positions, wider stops, broader symbol universe than the day-trading variant.
Edit the defaults below or override via a .env file in the project root.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # === Alpaca credentials ===
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"

    # === Ollama ===
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model_name: str = os.getenv("MODEL_NAME", "qwen3:4b")

    # === Model provider: "ollama" (local, free) or "gemini" (cloud, fast) ===
    model_provider: str = os.getenv("MODEL_PROVIDER", "ollama").strip().lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # === HARD RISK LIMITS — tuned for SWING trading ===
    # Resized 2026-07-08: target ~60% of the $100k paper account deployed
    # (8 x $7,500 = $60k), unlevered — margin buying power is deliberately unused.
    # Cap is enforced PER SYMBOL (existing holding + new order), not per order.
    max_position_size_usd: float = 7500.0   # ~7.5% of equity per symbol
    max_daily_loss_usd: float = 1000.0      # ~1% of equity; halts new buys for the day
    max_open_positions: int = 8             # diversification across swing setups
    max_order_qty: int = 200                # raw share sanity cap (cheapest whitelist names ~$50)
    max_positions_per_sector: int = 3       # cap concentration: max open positions in one sector
    market_hours_only: bool = True

    # Approved proposals: True = the bot executes them autonomously; False = they
    # queue for human review via review.py. Toggle with AUTO_EXECUTE in the .env file.
    auto_execute_proposals: bool = os.getenv("AUTO_EXECUTE", "false").strip().lower() == "true"

    # Exit style for new buys (Exp4, 2026-06-11):
    #   "bracket"  — fixed stop + take-profit legs held at the broker (original)
    #   "trailing" — server-side trailing stop (trail_percent below the high-water
    #                mark), NO profit target: cut losers, let winners run.
    # Walk-forward train result for trailing: avg alpha -2.0% vs bracket's -10.7%
    # (still negative — forward paper trading is the live test of this config).
    exit_style: str = os.getenv("EXIT_STYLE", "bracket").strip().lower()
    trail_percent: float = float(os.getenv("TRAIL_PERCENT", "10"))

    # === Symbol whitelist — broader universe for swing trading ===
    # ETFs for sector/index exposure + large/mid caps with good liquidity and clear narratives
    allowed_symbols: List[str] = field(default_factory=lambda: [
        # Broad index / sector ETFs
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI",
        # Mega-cap tech
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
        # Other major tech / growth
        "TSLA", "AMD", "NFLX", "AVGO", "ORCL", "CRM", "ADBE",
        # Finance
        "JPM", "BAC", "GS", "MS", "V", "MA",
        # Consumer / industrial
        "DIS", "WMT", "COST", "HD", "CAT", "BA", "UNH", "JNJ",
        # Energy
        "XOM", "CVX",
    ])

    # Sector map — used by the risk layer to prevent piling into one correlated
    # sector. Broad index ETFs are tagged 'broad_index' and exempt from the cap.
    sector_map: dict = field(default_factory=lambda: {
        "SPY": "broad_index", "QQQ": "broad_index", "IWM": "broad_index", "DIA": "broad_index",
        "XLK": "technology", "AAPL": "technology", "MSFT": "technology", "NVDA": "technology",
        "GOOGL": "technology", "AMZN": "technology", "META": "technology", "AVGO": "technology",
        "ORCL": "technology", "CRM": "technology", "ADBE": "technology", "AMD": "technology",
        "NFLX": "technology",
        "XLF": "financials", "JPM": "financials", "BAC": "financials", "GS": "financials",
        "MS": "financials", "V": "financials", "MA": "financials",
        "XLY": "consumer", "TSLA": "consumer", "DIS": "consumer", "WMT": "consumer",
        "COST": "consumer", "HD": "consumer",
        "XLV": "healthcare", "UNH": "healthcare", "JNJ": "healthcare",
        "XLI": "industrials", "CAT": "industrials", "BA": "industrials",
        "XLE": "energy", "XOM": "energy", "CVX": "energy",
    })

    log_dir: str = "./logs"


CONFIG = Config()
