const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

const DEPLOYMENTS_DIR = path.join(__dirname, "..", "deployments");

function ensureDeploymentsDir() {
  if (!fs.existsSync(DEPLOYMENTS_DIR)) {
    fs.mkdirSync(DEPLOYMENTS_DIR, { recursive: true });
  }
}

function writeDeploymentRecord(networkName, record) {
  ensureDeploymentsDir();
  const filePath = path.join(DEPLOYMENTS_DIR, `${networkName}.json`);
  fs.writeFileSync(filePath, JSON.stringify(record, null, 2));
  console.log(`Deployment record written to ${filePath}`);
}

function validateNetworkConfig(networkName, chainId) {
  const normalizedNetworkName = networkName.trim().toLowerCase();
  const allowedNetworkNames = ["hardhat", "botchain"];
  if (!allowedNetworkNames.includes(normalizedNetworkName)) {
    throw new Error(
      `Invalid BOT_CHAIN_NETWORK_NAME: "${networkName}". Allowed values: ${allowedNetworkNames.join(", ")}`
    );
  }

  if (normalizedNetworkName === "botchain") {
    if (!process.env.BOT_CHAIN_RPC_URL) {
      throw new Error("BOT_CHAIN_RPC_URL is required for BOT Chain deployment");
    }
    if (!process.env.BOT_CHAIN_CHAIN_ID) {
      throw new Error("BOT_CHAIN_CHAIN_ID is required for BOT Chain deployment");
    }
    const expectedChainId = parseInt(process.env.BOT_CHAIN_CHAIN_ID, 10);
    if (Number(chainId) !== expectedChainId) {
      throw new Error(
        `Network safety check failed: expected chain ID ${expectedChainId}, but connected to ${chainId}`
      );
    }
    if (!process.env.PRIVATE_KEY) {
      throw new Error("PRIVATE_KEY is required for BOT Chain deployment");
    }
    if (!process.env.PAYMENT_TOKEN_ADDRESS) {
      throw new Error("PAYMENT_TOKEN_ADDRESS is required for BOT Chain deployment");
    }

    if (Number(chainId) === 677) {
      const mainnetConfirm = process.env.CONFIRM_BOTCHAIN_MAINNET_DEPLOY;
      if (mainnetConfirm !== "YES") {
        throw new Error(
          "BOT Chain mainnet deployment requires explicit opt-in. Set CONFIRM_BOTCHAIN_MAINNET_DEPLOY=YES to proceed."
        );
      }
    }
  }
}

async function deploy() {
  const networkName = process.env.BOT_CHAIN_NETWORK_NAME || "hardhat";
  const chainId = (await ethers.provider.getNetwork()).chainId;
  const [deployer] = await ethers.getSigners();
  const deployerAddress = await deployer.getAddress();

  validateNetworkConfig(networkName, chainId);

  if (networkName === "botchain") {
    const balance = await ethers.provider.getBalance(deployerAddress);
    if (balance < ethers.parseUnits("0.01", 18)) {
      throw new Error(
        `Deployer balance is too low to cover gas: ${ethers.formatEther(balance)} BOT`
      );
    }
  }

  console.log(`Deploying to network: ${networkName} (chainId: ${chainId})`);
  console.log(`Deployer: ${deployerAddress}`);

  const paymentTokenAddress = process.env.PAYMENT_TOKEN_ADDRESS;
  let mockUSDT;
  let tokenDecimals = 18;

  if (paymentTokenAddress) {
    console.log(`Using existing payment token: ${paymentTokenAddress}`);
    mockUSDT = await ethers.getContractAt("MockUSDT", paymentTokenAddress);
    try {
      tokenDecimals = await mockUSDT.decimals();
    } catch (error) {
      console.warn(`Could not read decimals from payment token: ${error.message}`);
    }
  } else {
    console.log("Deploying MockUSDT...");
    const MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();
    await mockUSDT.waitForDeployment();
    console.log(`MockUSDT deployed to: ${await mockUSDT.getAddress()}`);
  }

  console.log("Deploying AssetRegistry...");
  const AssetRegistry = await ethers.getContractFactory("AssetRegistry");
  const assetRegistry = await AssetRegistry.deploy();
  await assetRegistry.waitForDeployment();
  const assetRegistryAddress = await assetRegistry.getAddress();
  console.log(`AssetRegistry deployed to: ${assetRegistryAddress}`);

  const paymentTokenForPool = paymentTokenAddress || (await mockUSDT.getAddress());
  console.log("Deploying FinancingPool...");
  const FinancingPool = await ethers.getContractFactory("FinancingPool");
  const financingPool = await FinancingPool.deploy(paymentTokenForPool, assetRegistryAddress);
  await financingPool.waitForDeployment();
  const financingPoolAddress = await financingPool.getAddress();
  console.log(`FinancingPool deployed to: ${financingPoolAddress}`);

  console.log("Configuring AssetRegistry with FinancingPool...");
  const setPoolTx = await assetRegistry.setFinancingPool(financingPoolAddress);
  await setPoolTx.wait();
  console.log("AssetRegistry financing pool configured.");

  const deploymentRecord = {
    network: networkName,
    chainId: Number(chainId),
    deployer: deployerAddress,
    assetRegistry: assetRegistryAddress,
    financingPool: financingPoolAddress,
    paymentToken: paymentTokenForPool,
    paymentTokenDecimals: Number(tokenDecimals),
    deployedAt: new Date().toISOString(),
  };

  writeDeploymentRecord(networkName, deploymentRecord);
  console.log("Deployment complete:", JSON.stringify(deploymentRecord, null, 2));
}

module.exports = { deploy, validateNetworkConfig };

if (require.main === module) {
  deploy()
    .then(() => process.exit(0))
    .catch((error) => {
      console.error(error);
      process.exit(1);
    });
}
