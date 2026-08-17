const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

const DEPLOYMENTS_DIR = path.join(__dirname, "..", "deployments");

function loadDeploymentRecord(networkName) {
  const filePath = path.join(DEPLOYMENTS_DIR, `${networkName}.json`);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Deployment record not found: ${filePath}`);
  }
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

async function main() {
  const networkName = process.env.BOT_CHAIN_NETWORK_NAME || "hardhat";
  const record = loadDeploymentRecord(networkName);

  console.log(`Verifying deployment for network: ${networkName}`);

  const provider = ethers.provider;
  const connectedChainId = (await provider.getNetwork()).chainId;
  const expectedChainId = record.chainId;
  if (Number(connectedChainId) !== Number(expectedChainId)) {
    console.error(
      `Network safety check failed: deployment record expects chain ID ${expectedChainId}, but connected to ${connectedChainId}`
    );
    process.exit(1);
  }

  const assetRegistry = await ethers.getContractAt("AssetRegistry", record.assetRegistry);
  const financingPool = await ethers.getContractAt("FinancingPool", record.financingPool);
  const mockUSDT = await ethers.getContractAt("MockUSDT", record.paymentToken);

  console.log("Checking AssetRegistry...");
  const registryOwner = await assetRegistry.owner();
  console.log(`  Owner: ${registryOwner}`);
  console.log(`  FinancingPool set: ${await assetRegistry.financingPool()}`);
  console.log(`  Next asset ID: ${await assetRegistry.nextAssetId()}`);

  console.log("Checking FinancingPool...");
  console.log(`  Payment token: ${await financingPool.paymentToken()}`);
  console.log(`  AssetRegistry: ${await financingPool.assetRegistry()}`);

  console.log("Checking MockUSDT...");
  console.log(`  Name: ${await mockUSDT.name()}`);
  console.log(`  Symbol: ${await mockUSDT.symbol()}`);
  const onChainDecimals = await mockUSDT.decimals();
  console.log(`  Decimals: ${onChainDecimals}`);

  const checks = [
    registryOwner.toLowerCase() === record.deployer.toLowerCase(),
    (await assetRegistry.financingPool()).toLowerCase() === record.financingPool.toLowerCase(),
    (await financingPool.paymentToken()).toLowerCase() === record.paymentToken.toLowerCase(),
    (await financingPool.assetRegistry()).toLowerCase() === record.assetRegistry.toLowerCase(),
    Number(onChainDecimals) === record.paymentTokenDecimals,
  ];

  if (checks.every(Boolean)) {
    console.log("All deployment verification checks passed.");
  } else {
    console.error("Deployment verification failed.");
    process.exit(1);
  }
}

module.exports = { main, loadDeploymentRecord };

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
