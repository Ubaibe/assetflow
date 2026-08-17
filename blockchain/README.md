# AssetFlow Blockchain

Smart contracts for the AssetFlow invoice financing platform, built for BOT Chain.

## Contracts

- `AssetRegistry.sol` — registers invoice assets on-chain with originator, face value, financing target, maturity, and risk score.
- `FinancingPool.sol` — accepts USDT funding for listed assets, tracks investments, handles repayments, and distributes returns to investors.
- `MockUSDT.sol` — local ERC20 mock token for Hardhat testing only. Do not use on BOT Chain Mainnet.

## Networks

### BOT Chain Testnet
- Chain ID: `968`
- RPC: `https://rpc.bohr.life`
- Explorer: `https://scan.bohr.life/`
- Native currency: `BOT`

### BOT Chain Mainnet
- Chain ID: `677`
- RPC: `https://rpc.botchain.ai`
- Explorer: `https://scan.botchain.ai/`
- Native currency: `BOT`

> **Mainnet deployment is disabled until final audit. Do not execute mainnet deployment commands.**

## Local Testing

```bash
cd blockchain
npm install
npm test
```

Local tests run against Hardhat's in-memory network. No external RPC or private key is required.

## Token Decimals

The application converts human-readable token amounts to base units using the payment token's decimals.

- **Local / MockUSDT**: 18 decimals
- **BOT Chain testnet / mainnet**: determined by the configured payment token address

The Python backend reads `PAYMENT_TOKEN_DECIMALS` from the environment (default: `18`). The deploy script reads `decimals()` from the deployed payment token and stores it in the deployment record.

### Decimal Safety Rules
- All conversions use `Decimal` arithmetic only.
- Zero and negative amounts are rejected.
- Amounts that cannot be represented exactly in the token's decimal precision are rejected.
- No floating-point arithmetic is used for token conversion.

## Environment Variables

Create a `.env` file in the project root (do not commit it):

```env
# BOT Chain Testnet
BOT_CHAIN_RPC_URL=https://rpc.bohr.life
BOT_CHAIN_CHAIN_ID=968
BOT_CHAIN_NETWORK_NAME=BOT Chain Testnet
BOT_CHAIN_EXPLORER_URL=https://scan.bohr.life/
BOT_CHAIN_NATIVE_CURRENCY=BOT

# BOT Chain Mainnet (do NOT deploy until final audit)
# BOT_CHAIN_RPC_URL=https://rpc.botchain.ai
# BOT_CHAIN_CHAIN_ID=677
# BOT_CHAIN_NETWORK_NAME=BOT Chain
# BOT_CHAIN_EXPLORER_URL=https://scan.botchain.ai/

# Deployer
PRIVATE_KEY=0x...

# Payment token decimals (default 18 for MockUSDT)
PAYMENT_TOKEN_DECIMALS=18

# Contracts (populate after deployment)
RPC_URL=
CHAIN_ID=
ASSET_REGISTRY_ADDRESS=
FINANCING_POOL_ADDRESS=
PAYMENT_TOKEN_ADDRESS=
```

> **Do not paste real private keys into source code or `.env.example`.**
> **Do not commit `.env`.**

## Deployment

```bash
cd blockchain
npm run deploy:bot
```

This will:
1. Validate BOT Chain configuration.
2. Verify the connected network chain ID matches `BOT_CHAIN_CHAIN_ID`.
3. Check deployer BOT balance.
4. Deploy or reference the payment token.
5. Deploy `AssetRegistry`.
6. Deploy `FinancingPool` with the correct dependencies.
7. Authorize `FinancingPool` in `AssetRegistry`.
8. Verify contract relationships and token decimals.
9. Write public deployment metadata to `blockchain/deployments/botchain-testnet.json`.

### Deployment Record

The deployment record contains only public information:
- network name
- chain ID
- deployer address
- AssetRegistry address
- FinancingPool address
- payment token address
- payment token decimals
- deployment timestamp

**Never** write the following to deployment artifacts:
- `PRIVATE_KEY`
- seed phrases
- RPC credentials
- Authorization headers
- bearer tokens

## Verification

```bash
npm run verify
```

This reads the deployment record and confirms contract relationships on-chain.

## Smoke Test

The Python backend includes a conditional smoke test for BOT Chain testnet.

```bash
RUN_BOTCHAIN_TESTNET_SMOKE=1 pytest tests/test_botchain_smoke.py -v
```

Prerequisites:
- `.env` configured with BOT Chain testnet values
- Deployer funded with testnet BOT for gas
- Contract addresses populated

If any required environment variable is missing, the smoke tests are skipped cleanly.

## Security Notes

- `PRIVATE_KEY` must never be logged, committed, or exposed in error messages.
- `MockUSDT` is for local testing only. BOT Chain requires the configured production payment token address.
- Always verify deployment addresses independently before sending real funds.
- The deploy script validates required fields but never logs private keys or RPC credentials.

## Architecture

```
Borrower
    ↓
local Asset
    ↓
AssetRegistry on BOT Chain
    ↓
actual blockchain assetId
    ↓
Investor
    ↓
FinancingPool on BOT Chain
    ↓
Investment + BlockchainTransaction records
```
