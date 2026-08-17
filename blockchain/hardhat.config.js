require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

const botChainRpcUrl = process.env.BOT_CHAIN_RPC_URL;
const botChainChainId = process.env.BOT_CHAIN_CHAIN_ID ? parseInt(process.env.BOT_CHAIN_CHAIN_ID, 10) : undefined;
const botChainAccounts = process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [];

const networks = {
  hardhat: {
    chainId: 31337,
  },
};

if (botChainRpcUrl && botChainChainId) {
  networks.botchain = {
    url: botChainRpcUrl,
    chainId: botChainChainId,
    accounts: botChainAccounts,
  };
}

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks,
};
