"""Universe and runtime configuration.

55 assets: 35 shares and 20 crypto. The shares span US large caps, the chip
supply chain, and Indian large caps — the last group because you are in Delhi,
so they are genuinely easier for you to buy and sell than US names, and because
they are less picked over by the funds competing on US mega caps.

Note what the US mega caps mean as a group: they are the most analysed, most
efficiently priced instruments in existence. A retail model beating them is a
strong claim. The Indian and mid-tier names are the more plausible hunting
ground, which is why they are here.

Every asset carries a one-line description of what the business does. That line
appears under any signal, so a name you do not recognise is never just a ticker.
Membership drifts — re-check the list quarterly rather than trusting it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .decide import Gates
from .types import Asset

# Descriptions are what the business does, not how it has been trading. A line
# about price would be stale the day after it was written; a line about the
# business stays true, which is the point of putting it under a signal.

US_LARGE = [
    Asset("NVDA", "nvidia", "equity", ("nvidia's",),
          "Designs the chips that most AI systems are trained and run on."),
    Asset("MSFT", "microsoft", "equity", ("msft", "azure"),
          "Windows, Office and Azure cloud. Large stake in OpenAI."),
    Asset("AAPL", "apple", "equity", ("iphone",),
          "iPhone, Mac and services. Most revenue still comes from the iPhone."),
    Asset("GOOGL", "alphabet", "equity", ("google", "gemini"),
          "Google search and ads, YouTube, Android and Google Cloud."),
    Asset("AMZN", "amazon", "equity", ("aws",),
          "Online retail plus AWS, the largest cloud computing provider."),
    Asset("META", "meta", "equity", ("facebook", "instagram"),
          "Facebook, Instagram and WhatsApp. Income is almost entirely advertising."),
    Asset("AVGO", "broadcom", "equity", (),
          "Networking and custom chips for data centres, plus enterprise software."),
    Asset("TSLA", "tesla", "equity", ("musk",),
          "Electric cars, batteries and energy storage."),
    Asset("BRK-B", "berkshire", "equity", ("buffett",),
          "Holding company owning insurance, railways, energy and large share stakes."),
    Asset("JPM", "jpmorgan", "equity", ("jpmorgan's",),
          "The largest US bank: lending, trading and asset management."),
    Asset("LLY", "eli lilly", "equity", ("lilly",),
          "Pharmaceuticals, best known now for weight-loss and diabetes drugs."),
    Asset("XOM", "exxon", "equity", ("exxonmobil",),
          "Oil and gas: production, refining and chemicals."),
    Asset("WMT", "walmart", "equity", (),
          "The largest retailer in the world by revenue, mostly groceries."),
    Asset("V", "visa", "equity", (),
          "Runs card payment rails and takes a small fee on each transaction."),
    Asset("UNH", "unitedhealth", "equity", (),
          "US health insurance and healthcare services."),
]

US_SEMIS_AND_TECH = [
    Asset("AMD", "amd", "equity", (),
          "Chips for PCs, servers and increasingly AI, competing with Nvidia."),
    Asset("TSM", "tsmc", "equity", ("taiwan semiconductor",),
          "Manufactures chips designed by others. Most advanced chips are made here."),
    Asset("MU", "micron", "equity", (),
          "Memory chips, the type AI servers need in large quantities."),
    Asset("ASML", "asml", "equity", (),
          "The only maker of the machines needed to print the most advanced chips."),
    Asset("QCOM", "qualcomm", "equity", (),
          "Mobile phone chips and the patents underneath most cellular networks."),
    Asset("ORCL", "oracle", "equity", (),
          "Databases and enterprise software, now renting out AI computing capacity."),
    Asset("CRM", "salesforce", "equity", (),
          "Customer relationship software sold to businesses by subscription."),
    Asset("PLTR", "palantir", "equity", (),
          "Data analysis software for governments, defence and large companies."),
    Asset("SMCI", "supermicro", "equity", ("super micro",),
          "Builds and assembles the servers that AI chips go into."),
    Asset("COIN", "coinbase", "equity", (),
          "US crypto exchange. Revenue tracks trading volumes closely."),
]

INDIA_LARGE = [
    Asset("RELIANCE.NS", "reliance", "equity", ("reliance industries", "ril"),
          "Refining, telecoms (Jio) and retail. India's largest listed company."),
    Asset("TCS.NS", "tcs", "equity", ("tata consultancy",),
          "IT services and outsourcing, mostly for Western clients."),
    Asset("INFY.NS", "infosys", "equity", (),
          "IT services and consulting, similar business to TCS."),
    Asset("HDFCBANK.NS", "hdfc bank", "equity", ("hdfc",),
          "India's largest private bank."),
    Asset("ICICIBANK.NS", "icici bank", "equity", ("icici",),
          "Large private bank: retail lending, corporate banking and insurance."),
    Asset("BHARTIARTL.NS", "bharti airtel", "equity", ("airtel", "bharti"),
          "Mobile network operator across India and Africa."),
    Asset("ITC.NS", "itc", "equity", (),
          "Cigarettes, packaged food, hotels and paper."),
    Asset("SBIN.NS", "sbi", "equity", ("state bank",),
          "State Bank of India, the largest government-owned bank."),
    Asset("LT.NS", "larsen toubro", "equity", ("l&t",),
          "Engineering and construction: infrastructure, power and defence."),
    # TATAMOTORS.NS was removed after Yahoo returned 404 for it on a live run.
    # No replacement is guessed here: an invented ticker fails silently every
    # day and wastes a board slot. Add the correct symbol back once you have
    # confirmed it resolves.
    Asset("BAJAJ-AUTO.NS", "bajaj auto", "equity", ("bajaj",),
          "Motorcycles and three-wheelers, sold in India and exported widely."),
]

CRYPTO = [
    Asset("BTC-USD", "bitcoin", "crypto", ("btc",),
          "The original cryptocurrency. Fixed supply, mostly held as a store of value."),
    Asset("ETH-USD", "ethereum", "crypto", ("eth", "ether"),
          "A programmable blockchain. Most other crypto projects are built on it."),
    Asset("XRP-USD", "xrp", "crypto", ("ripple",),
          "Built for cross-border payments between banks."),
    Asset("BNB-USD", "bnb", "crypto", ("binance",),
          "The token of the Binance exchange and its own blockchain."),
    Asset("SOL-USD", "solana", "crypto", ("sol",),
          "A fast, low-fee blockchain. Popular for trading apps and new tokens."),
    Asset("DOGE-USD", "dogecoin", "crypto", ("doge",),
          "Started as a joke. Price moves mostly on attention, not on usage."),
    Asset("ADA-USD", "cardano", "crypto", ("ada",),
          "A blockchain built around slow, research-led development."),
    Asset("TRX-USD", "tron", "crypto", ("trx",),
          "Carries a large share of stablecoin transfers, especially in Asia."),
    Asset("LINK-USD", "chainlink", "crypto", ("link",),
          "Feeds outside data, such as prices, into blockchain applications."),
    Asset("AVAX-USD", "avalanche", "crypto", ("avax",),
          "A blockchain that lets companies run their own connected networks."),
    Asset("DOT-USD", "polkadot", "crypto", ("dot",),
          "Connects separate blockchains so they can pass data between them."),
    Asset("MATIC-USD", "polygon", "crypto", ("matic",),
          "Makes Ethereum transactions cheaper by settling them in batches."),
    Asset("LTC-USD", "litecoin", "crypto", ("ltc",),
          "An early Bitcoin offshoot, built for faster and cheaper payments."),
    Asset("ATOM-USD", "cosmos", "crypto", ("atom",),
          "Toolkit for building blockchains that talk to each other."),
    Asset("NEAR-USD", "near", "crypto", (),
          "A blockchain aimed at making apps simple enough for ordinary users."),
    Asset("UNI-USD", "uniswap", "crypto", (),
          "The token of the largest exchange that runs without a company behind it."),
    Asset("AAVE-USD", "aave", "crypto", (),
          "Lending and borrowing of crypto without a bank in the middle."),
    Asset("ARB-USD", "arbitrum", "crypto", (),
          "Speeds up Ethereum by processing transactions separately, then settling."),
    Asset("OP-USD", "optimism", "crypto", (),
          "Another Ethereum speed-up layer, competing with Arbitrum."),
    Asset("SUI-USD", "sui", "crypto", (),
          "A newer blockchain built for high transaction volumes."),
]

EQUITIES = US_LARGE + US_SEMIS_AND_TECH + INDIA_LARGE

# 55 assets: 35 shares across US large caps, chipmakers and Indian large caps,
# plus 20 crypto. Wide on purpose — the screeners test every pair and reject
# almost all of them, so a name missing from this list is simply invisible.
UNIVERSE = EQUITIES + CRYPTO

# ---------------------------------------------------------------- pool -----
# The rolling 100 is drawn from here. Entry is structural: liquid enough to get
# in and out of, and covered enough to generate news. Nothing in this ordering
# is a forecast — ranking a pool by expected return before any outcome exists
# would be guessing with extra steps.
#
# The pool is larger than the list so rotation has somewhere to go. Names here
# without a hand-written description get a category line instead; a generic line
# is honest, a made-up specific one is not.

_POOL_EXTRA: dict[str, tuple[str, str]] = {
    # US shares, liquid and widely covered
    "GOOG": ("equity", "Alphabet's other share class. Same business as GOOGL."),
    "COST": ("equity", "Membership warehouse retailer."),
    "HD": ("equity", "Home improvement retail across the US."),
    "PG": ("equity", "Household and personal care brands."),
    "JNJ": ("equity", "Pharmaceuticals and medical devices."),
    "ABBV": ("equity", "Pharmaceuticals, largely immunology and cancer."),
    "MRK": ("equity", "Pharmaceuticals, best known for cancer treatments."),
    "PFE": ("equity", "Pharmaceuticals and vaccines."),
    "KO": ("equity", "Soft drinks, sold through bottlers worldwide."),
    "PEP": ("equity", "Soft drinks and snack foods."),
    "MCD": ("equity", "Fast food, mostly through franchised restaurants."),
    "NKE": ("equity", "Sportswear and footwear."),
    "DIS": ("equity", "Film and TV studios, streaming, and theme parks."),
    "NFLX": ("equity", "Subscription video streaming."),
    "BAC": ("equity", "Large US retail and commercial bank."),
    "WFC": ("equity", "US bank focused on retail lending and mortgages."),
    "GS": ("equity", "Investment bank: trading, advisory and asset management."),
    "MS": ("equity", "Investment bank and wealth manager."),
    "C": ("equity", "Global bank with a large international footprint."),
    "SCHW": ("equity", "Brokerage and wealth management."),
    "CVX": ("equity", "Oil and gas production and refining."),
    "COP": ("equity", "Oil and gas exploration and production."),
    "CAT": ("equity", "Construction and mining machinery."),
    "DE": ("equity", "Agricultural and construction machinery."),
    "BA": ("equity", "Commercial aircraft and defence systems."),
    "GE": ("equity", "Jet engines and energy equipment."),
    "RTX": ("equity", "Aerospace components and defence systems."),
    "LMT": ("equity", "Defence: aircraft, missiles and space systems."),
    "T": ("equity", "US telecoms: mobile and broadband."),
    "VZ": ("equity", "US mobile network operator."),
    "INTC": ("equity", "Designs and manufactures processors, mainly for PCs and servers."),
    "TXN": ("equity", "Analogue chips used across industrial and automotive products."),
    "AMAT": ("equity", "Machines used to manufacture semiconductors."),
    "LRCX": ("equity", "Equipment for etching and depositing layers on chips."),
    "KLAC": ("equity", "Inspection equipment that finds defects on chips."),
    "ARM": ("equity", "Licenses the chip designs used in most mobile phones."),
    "MRVL": ("equity", "Networking and storage chips for data centres."),
    "ANET": ("equity", "High-speed network switches for data centres."),
    "NOW": ("equity", "Workflow software for IT and HR departments."),
    "SNOW": ("equity", "Cloud data warehousing sold by usage."),
    "MDB": ("equity", "Database software sold to developers."),
    "NET": ("equity", "Content delivery and internet security services."),
    "DDOG": ("equity", "Monitoring software for cloud applications."),
    "PANW": ("equity", "Enterprise cybersecurity: firewalls and cloud security."),
    "CRWD": ("equity", "Endpoint security software delivered from the cloud."),
    "ADBE": ("equity", "Creative and document software by subscription."),
    "INTU": ("equity", "Tax and small business accounting software."),
    "SHOP": ("equity", "Software that lets merchants run online stores."),
    "UBER": ("equity", "Ride hailing and food delivery."),
    "ABNB": ("equity", "Short-term accommodation booking."),
    "MSTR": ("equity", "Software company holding a very large bitcoin position."),
    "MARA": ("equity", "Bitcoin mining."),
    "RIOT": ("equity", "Bitcoin mining and hosting."),
    "HOOD": ("equity", "Retail brokerage for shares and crypto."),
    # Indian shares
    "HINDUNILVR.NS": ("equity", "Soaps, detergents and packaged foods across India."),
    "MARUTI.NS": ("equity", "India's largest carmaker by volume."),
    "AXISBANK.NS": ("equity", "Private bank: retail and corporate lending."),
    "KOTAKBANK.NS": ("equity", "Private bank and financial services group."),
    "BAJFINANCE.NS": ("equity", "Consumer and small business lending."),
    "ASIANPAINT.NS": ("equity", "Decorative paints and coatings."),
    "SUNPHARMA.NS": ("equity", "India's largest pharmaceuticals maker."),
    "TITAN.NS": ("equity", "Jewellery, watches and eyewear retail."),
    "WIPRO.NS": ("equity", "IT services and consulting."),
    "HCLTECH.NS": ("equity", "IT services and software engineering."),
    "ADANIENT.NS": ("equity", "Infrastructure conglomerate: ports, energy and mining."),
    "NTPC.NS": ("equity", "India's largest power generator."),
    "ONGC.NS": ("equity", "State-owned oil and gas exploration."),
    "COALINDIA.NS": ("equity", "State-owned coal mining."),
    "POWERGRID.NS": ("equity", "Operates India's electricity transmission network."),
    # Index and sector funds. Liquid, heavily covered, and already referenced as
    # contagion dependents — leaving them out of the pool meant the board could
    # never contain something the models were actively predicting.
    "SPY": ("fund", "Tracks the S&P 500: the 500 largest US listed companies."),
    "QQQ": ("fund", "Tracks the Nasdaq 100, so mostly large technology companies."),
    "IWM": ("fund", "Tracks the Russell 2000: smaller US companies."),
    "SMH": ("fund", "Tracks semiconductor companies."),
    "XLF": ("fund", "Tracks US banks and financial firms."),
    "XLE": ("fund", "Tracks US oil, gas and energy companies."),
    "XLV": ("fund", "Tracks US healthcare and pharmaceutical companies."),
    "GLD": ("fund", "Holds physical gold; moves with the gold price."),
    "TLT": ("fund", "Holds long-dated US government bonds; moves with interest rates."),
    "EEM": ("fund", "Tracks large companies across emerging markets."),
    "INDA": ("fund", "Tracks large and mid-sized Indian companies."),
    "ARKK": ("fund", "Actively managed fund holding high-growth technology shares."),
    # Crypto
    "TON-USD": ("crypto", "A blockchain built to run inside Telegram."),
    "HBAR-USD": ("crypto", "A network aimed at enterprise and government use."),
    "ICP-USD": ("crypto", "Runs software directly on a decentralised network."),
    "FIL-USD": ("crypto", "Pays for decentralised file storage."),
    "INJ-USD": ("crypto", "A blockchain built specifically for trading applications."),
    "TIA-USD": ("crypto", "Supplies data availability to other blockchains."),
    "SEI-USD": ("crypto", "A fast blockchain aimed at trading."),
    "APT-USD": ("crypto", "A blockchain from former Meta engineers."),
    "RUNE-USD": ("crypto", "Swaps assets between different blockchains."),
    "GRT-USD": ("crypto", "Indexes blockchain data so apps can query it."),
    "ALGO-USD": ("crypto", "A blockchain focused on speed and low fees."),
    "XLM-USD": ("crypto", "Built for low-cost cross-border transfers."),
    "ETC-USD": ("crypto", "The original Ethereum chain after its 2016 split."),
    "BCH-USD": ("crypto", "A Bitcoin offshoot with larger blocks."),
    "VET-USD": ("crypto", "Supply chain tracking on a blockchain."),
    "FET-USD": ("crypto", "A network for AI agents to transact with each other."),
    "RENDER-USD": ("crypto", "Pays for distributed graphics rendering."),
    "IMX-USD": ("crypto", "Scales Ethereum for games and digital collectibles."),
    "STX-USD": ("crypto", "Brings smart contracts to Bitcoin."),
    "MKR-USD": ("crypto", "Governs the DAI stablecoin system."),
}

POOL = UNIVERSE + [
    Asset(sym, sym.split("-")[0].split(".")[0].lower(), kind, (), desc)
    for sym, (kind, desc) in _POOL_EXTRA.items()
]

DESCRIPTIONS = {a.symbol: a.description for a in POOL}


@dataclass(frozen=True)
class Settings:
    history_start: str = "2015-01-01"
    train_window: int = 750
    refit_step: int = 21
    equity_gates: Gates = Gates(prob_threshold=0.60, min_bin_n=40, cost_pct=0.0010)
    # Crypto trades 24/7 with wider spreads and no circuit breakers: charge more
    # and demand more before acting.
    crypto_gates: Gates = Gates(prob_threshold=0.62, min_bin_n=40, cost_pct=0.0035)
    news_score_threshold: float = 0.35
    shadow_db: str = os.environ.get("SIGBOT_DB", "shadow.db")
    watchlist_db: str = os.environ.get("SIGBOT_WATCHLIST_DB", "watchlist.db")

    def gates_for(self, asset: Asset) -> Gates:
        return self.crypto_gates if asset.kind == "crypto" else self.equity_gates


SETTINGS = Settings()


# Candidate dependents for the contagion screen (Model C). This list is a
# hypothesis space, not a set of beliefs: every pair is tested and almost all
# will be rejected. Add liberally — FDR control handles the multiple testing.
CONTAGION_CANDIDATES = [
    # semis / AI supply chain
    "AMD", "INTC", "MU", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "ARM", "MRVL",
    "SMCI", "DELL", "ANET", "VRT", "CRDO", "ALAB",
    # hyperscaler-adjacent software and infra
    "ORCL", "CRM", "NOW", "SNOW", "MDB", "PLTR", "NET", "DDOG",
    # Apple / consumer supply chain
    "QCOM", "SWKS", "QRVO", "CRUS", "JBL", "GLW",
    # Tesla / EV chain
    "RIVN", "LCID", "ALB", "PANW", "MBLY", "ON",
    # financials that move with JPM
    "BAC", "C", "WFC", "GS", "MS", "SCHW",
    # crypto-linked equities
    "COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "HUT", "CIFR",
    # sector and factor context
    "SPY", "QQQ", "SMH", "XLF", "XLK", "IWM", "GLD", "TLT", "UUP", "VIXY",
    # second-tier crypto that reacts to BTC/ETH
    "LTC-USD", "DOT-USD", "MATIC-USD", "ATOM-USD", "NEAR-USD", "APT-USD",
    "ARB-USD", "OP-USD", "INJ-USD", "SUI-USD", "TON-USD", "HBAR-USD",
]

# Delhi-based operation. These are facts to verify with a professional, not
# advice: India's Liberalised Remittance Scheme caps outward remittance per
# financial year, TCS applies above a threshold, gains on virtual digital
# assets are taxed at a flat rate with TDS on transfers, and direct foreign
# property purchase by residents is restricted under FEMA. Any "feasible
# investment opportunity" that ignores these is not feasible.
JURISDICTION_NOTE = (
    "Jurisdiction check (India): outward remittance limits under LRS, TCS on "
    "foreign remittance, flat-rate VDA taxation with TDS, and FEMA restrictions "
    "on direct overseas property purchase all bear on whether any of the above "
    "is actionable. Verify current rules with a qualified advisor before acting."
)
