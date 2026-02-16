# MemeSeer — Autonomous Memecoin Launching AI Agent

MemeSeer is a fully autonomous on-chain AI agent that observes crypto market signals, decides when to launch memecoins, deploys them on nad.fun (Monad mainnet), and manages positions without human intervention.

It does not trade narratives.
It creates them.

---

## 🏆 Hackathon Track

**Moltiverse Hackathon — Main Track (Agent + Token)**

Token launched on nad.fun (Monad mainnet):

```
Contract Address: 0x17De1C1346EA528B4BEBF8711d1DDAb5B9157777
Network: Monad Mainnet
Trade on nad.fun: https://nad.fun/tokens/0x17De1C1346EA528B4BEBF8711d1DDAb5B9157777
```

Example transaction: 

```
https://monadvision.com/tx/0xead52dc2aa92d8a94f4e2dfbdfce9e793ad311f739b502dad36cc543bdc97e01
```

---

# 🧠 What MemeSeer Does

MemeSeer operates in a continuous autonomous loop:

1. Ingests live market data (Twitter + Dex signals)
2. Extracts market signals:

   * trend
   * sentiment
   * novelty
   * liquidity
   * competition
3. Computes market edge
4. Selects strategy using UCB1 multi-armed bandit learning
5. Decides whether to launch
6. Generates token concept via LLM
7. Generates AI logo
8. Deploys token on nad.fun (Monad mainnet)
9. Manages position via bonding curve trading
10. Applies buyback logic to CORE (SEER)
11. Publishes ritual logs
12. Updates persistent memory

No manual trigger is required after startup.

The agent owns a wallet and executes transactions independently.

---

# ⚙️ Autonomous Decision Model

MemeSeer is not rule-based.
It is policy-driven and learning-based.

### Market Edge Calculation

Signals → Edge Score → Bucket:

* 🔴 Bad
* 🟡 Neutral
* 🟢 Good

### Policy Selection

Uses UCB1 (Upper Confidence Bound) multi-armed bandit to select among:

* conservative
* balanced
* growth
* signal
* aggressive
* no_launch

The agent learns which strategy works best per market bucket.

### Gating Layers

Launch is blocked if:

* Portfolio is full
* Economy constraints fail
* Daily cooldown active
* CORE guard triggered
* LLM disabled
* Kill switch active

This ensures capital discipline.

---

# 🏗 Architecture

High-level flow:

```
External Feed
     ↓
Observe()
     ↓
Compute Edge
     ↓
Select Policy (UCB1)
     ↓
LLM Reasoning
     ↓
Token Idea Generation
     ↓
AI Image Generation
     ↓
On-Chain Deployment (nad.fun)
     ↓
Portfolio Management
     ↓
Memory Update
```

### Core Components

* `main.py` — orchestration loop
* `economy.py` — CORE funding & payout logic
* `policy.py` — UCB1 learning + edge computation
* `portfolio/` — ladder sells + trailing logic
* `onchain/nadfun_executor.py` — Monad mainnet execution
* `ingest/` — Twitter + Dex ingestion
* `memory.json` — persistent state

---

# ⛓ Monad Integration

MemeSeer interacts directly with Monad mainnet:

* Router.create() for token deployment
* Router.sell() for CORE funding
* Lens.getAmountOut() for quotes
* Bonding curve interaction
* On-chain transaction signing via Web3
* Mainnet deployment only

The agent wallet:

* Funds launches
* Executes bonding curve trades
* Manages portfolio exits
* Applies buyback logic

All actions are executed on-chain.

---

# 💰 Token Economics

MemeSeer operates with a CORE token (SEER):

* CORE is sold to fund new launches
* Profits partially used for buyback
* Risk caps limit treasury exposure
* Loss streak triggers protective cooldown
* Portfolio max active positions enforced

This creates a flywheel:

Launch → Outcome → Profit → Buyback → Treasury → Next Launch

---

# 🔁 Portfolio Logic

Each position follows:

* Profit ladder:

  * +100%
  * +300%
  * +600%
* 20% sell at each ladder level
* MOON_BAG mode with trailing exit
* Dead token rule (gradual exit)
* CORE guard on loss streak

This is fully automated.

---

# 🖼 AI Image Generation

* Generates 1:1 memecoin logo
* Meme-native style
* No watermark
* Stored locally during launch
* Uploaded to nad.fun metadata endpoint

If AI fails → deterministic fallback generator.

---

# 📂 Persistent Memory

All state is saved to `memory.json`:

* World signals
* Policy stats
* Portfolio
* Launch history
* Learning data
* CORE guard state
* Social ritual history

The agent survives restarts without losing context.

---

# 🚀 Setup

## Requirements

* Python 3.10+
* Monad RPC URL
* Private key (agent wallet)
* OpenRouter API key (https://openrouter.ai/)
* Social Data API key (https://socialdata.tools/)

## Installation

```bash
git clone https://github.com/memeseer/MemeSeer.git
cd MemeSeer
pip install -r requirements.txt
```

## Environment Variables

Create `.env`:

```
RPC_URL=https://rpc.monad.xyz
PRIVATE_KEY=your_private_key
OPENROUTER_API_KEY=your_openrouter_key
SOCIALDATA_API_KEY=your_SocialData_key
SEER_TOKEN_ADDRESS=0x...
EXECUTION_DRY_RUN=0 (1 == test mod)

```

## Run Agent

```bash
python main.py
```

The agent will:

* Run ingestion
* Observe market
* Select policy
* Possibly launch
* Execute on-chain

---

# 🎥 Demo Video

2-minute demo:

```
https://www.youtube.com/watch?v=WdFX1LYFtmA
```

Video demonstrates:

* Agent boot
* Market observation
* Policy selection
* Token creation
* On-chain transaction
* Portfolio entry
* Ritual post

---

# 🔐 Safety & Controls


* Daily launch cooldown
* Loss streak protection
* Portfolio limit (max 3 active)

Designed to prevent runaway capital depletion.

---

# 🧪 Mainnet Proof

Token Address:

```
0x17De1C1346EA528B4BEBF8711d1DDAb5B9157777
```

Explorer:

```
https://monadvision.com/token/0x17De1C1346EA528B4BEBF8711d1DDAb5B9157777
```

Launch Transaction:

```
https://monadvision.com/tx/0x3a2d77755bf5d504d8f539e26bda3475ccc23a9f117f32449f0451011f77d95c
```

---

# 💡 Innovation

MemeSeer is not a trading bot.

It is a memetic capital allocator.

It creates narrative-driven tokens based on real-time cultural signals and deploys them autonomously on-chain.

The agent:

* Generates culture
* Deploys liquidity
* Manages risk
* Learns from outcomes

This is fully autonomous token creation.

---

# 📜 License

MIT License


