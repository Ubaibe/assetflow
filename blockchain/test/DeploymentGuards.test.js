const { expect } = require("chai");
const { deploy, validateNetworkConfig } = require("../scripts/deploy.js");

describe("Deployment Safety Guards", function () {
  const originalEnv = process.env;

  beforeEach(function () {
    process.env = { ...originalEnv };
  });

  afterEach(function () {
    process.env = originalEnv;
  });

  describe("validateNetworkConfig", function () {
    it("Should allow hardhat network", function () {
      process.env.BOT_CHAIN_NETWORK_NAME = "hardhat";
      expect(() => validateNetworkConfig("hardhat", 31337)).to.not.throw();
    });

    it("Should allow botchain network with matching chain ID", function () {
      process.env.BOT_CHAIN_NETWORK_NAME = "botchain";
      process.env.BOT_CHAIN_CHAIN_ID = "968";
      process.env.BOT_CHAIN_RPC_URL = "https://rpc.bohr.life";
      process.env.PRIVATE_KEY = "0x" + "ab".repeat(32);
      process.env.PAYMENT_TOKEN_ADDRESS = "0x" + "cd".repeat(20);
      expect(() => validateNetworkConfig("botchain", 968)).to.not.throw();
    });

    it("Should reject mismatched chain ID", function () {
      process.env.BOT_CHAIN_NETWORK_NAME = "botchain";
      process.env.BOT_CHAIN_CHAIN_ID = "968";
      process.env.BOT_CHAIN_RPC_URL = "https://rpc.bohr.life";
      process.env.PRIVATE_KEY = "0x" + "ab".repeat(32);
      process.env.PAYMENT_TOKEN_ADDRESS = "0x" + "cd".repeat(20);
      expect(() => validateNetworkConfig("botchain", 31337)).to.throw(
        "Network safety check failed: expected chain ID 968, but connected to 31337"
      );
    });

    it("Should reject invalid network name", function () {
      expect(() => validateNetworkConfig("mainnet", 677)).to.throw(
        "Invalid BOT_CHAIN_NETWORK_NAME"
      );
    });

    it("Should reject mainnet without explicit opt-in", function () {
      process.env.BOT_CHAIN_NETWORK_NAME = "botchain";
      process.env.BOT_CHAIN_CHAIN_ID = "677";
      process.env.BOT_CHAIN_RPC_URL = "https://rpc.botchain.ai";
      process.env.PRIVATE_KEY = "0x" + "ab".repeat(32);
      process.env.PAYMENT_TOKEN_ADDRESS = "0x" + "cd".repeat(20);
      expect(() => validateNetworkConfig("botchain", 677)).to.throw(
        "BOT Chain mainnet deployment requires explicit opt-in"
      );
    });

    it("Should allow mainnet with explicit opt-in", function () {
      process.env.BOT_CHAIN_NETWORK_NAME = "botchain";
      process.env.BOT_CHAIN_CHAIN_ID = "677";
      process.env.BOT_CHAIN_RPC_URL = "https://rpc.botchain.ai";
      process.env.PRIVATE_KEY = "0x" + "ab".repeat(32);
      process.env.PAYMENT_TOKEN_ADDRESS = "0x" + "cd".repeat(20);
      process.env.CONFIRM_BOTCHAIN_MAINNET_DEPLOY = "YES";
      expect(() => validateNetworkConfig("botchain", 677)).to.not.throw();
    });

    it("Should reject missing RPC_URL for botchain", function () {
      delete process.env.BOT_CHAIN_RPC_URL;
      expect(() => validateNetworkConfig("botchain", 968)).to.throw(
        "BOT_CHAIN_RPC_URL is required for BOT Chain deployment"
      );
    });

    it("Should reject missing PRIVATE_KEY for botchain", function () {
      delete process.env.PRIVATE_KEY;
      expect(() => validateNetworkConfig("botchain", 968)).to.throw(
        "PRIVATE_KEY is required for BOT Chain deployment"
      );
    });

    it("Should reject missing PAYMENT_TOKEN_ADDRESS for botchain", function () {
      delete process.env.PAYMENT_TOKEN_ADDRESS;
      expect(() => validateNetworkConfig("botchain", 968)).to.throw(
        "PAYMENT_TOKEN_ADDRESS is required for BOT Chain deployment"
      );
    });
  });
});
