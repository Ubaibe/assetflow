const { expect } = require("chai");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

describe("Deployment Infrastructure", function () {
  let AssetRegistry;
  let assetRegistry;
  let MockUSDT;
  let mockUSDT;
  let FinancingPool;
  let financingPool;
  let owner;

  beforeEach(async function () {
    [owner] = await ethers.getSigners();
  });

  it("Should deploy AssetRegistry on local Hardhat network", async function () {
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
    await assetRegistry.waitForDeployment();

    expect(await assetRegistry.owner()).to.equal(owner.address);
    expect(await assetRegistry.nextAssetId()).to.equal(0);
  });

  it("Should deploy FinancingPool with correct dependencies", async function () {
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
    await assetRegistry.waitForDeployment();

    MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();
    await mockUSDT.waitForDeployment();

    FinancingPool = await ethers.getContractFactory("FinancingPool");
    financingPool = await FinancingPool.deploy(await mockUSDT.getAddress(), await assetRegistry.getAddress());
    await financingPool.waitForDeployment();

    expect(await financingPool.paymentToken()).to.equal(await mockUSDT.getAddress());
    expect(await financingPool.assetRegistry()).to.equal(await assetRegistry.getAddress());
  });

  it("Should wire AssetRegistry to FinancingPool", async function () {
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
    await assetRegistry.waitForDeployment();

    MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();
    await mockUSDT.waitForDeployment();

    FinancingPool = await ethers.getContractFactory("FinancingPool");
    financingPool = await FinancingPool.deploy(await mockUSDT.getAddress(), await assetRegistry.getAddress());
    await financingPool.waitForDeployment();

    await assetRegistry.setFinancingPool(await financingPool.getAddress());

    expect(await assetRegistry.financingPool()).to.equal(await financingPool.getAddress());
  });

  it("Should create an asset and fund it end-to-end", async function () {
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
    await assetRegistry.waitForDeployment();

    MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();
    await mockUSDT.waitForDeployment();

    FinancingPool = await ethers.getContractFactory("FinancingPool");
    financingPool = await FinancingPool.deploy(await mockUSDT.getAddress(), await assetRegistry.getAddress());
    await financingPool.waitForDeployment();

    await assetRegistry.setFinancingPool(await financingPool.getAddress());

    const [owner, originator, investor] = await ethers.getSigners();
    await mockUSDT.mint(investor.address, ethers.parseUnits("1000", 18));

    const assetHash = ethers.keccak256(ethers.toUtf8Bytes("deployment-test"));
    const faceValue = ethers.parseUnits("1000", 18);
    const financingTarget = ethers.parseUnits("800", 18);
    const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
    const riskScore = 50;

    await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    expect(await assetRegistry.nextAssetId()).to.equal(1);

    await mockUSDT.connect(investor).approve(await financingPool.getAddress(), financingTarget);
    await financingPool.connect(investor).fund(0, financingTarget);

    const state = await financingPool.getFundingState(0);
    expect(state.totalFunded).to.equal(financingTarget);
    expect(state.exists).to.equal(true);
  });

  it("Should produce deployment record without secrets", async function () {
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
    await assetRegistry.waitForDeployment();

    MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();
    await mockUSDT.waitForDeployment();

    FinancingPool = await ethers.getContractFactory("FinancingPool");
    financingPool = await FinancingPool.deploy(await mockUSDT.getAddress(), await assetRegistry.getAddress());
    await financingPool.waitForDeployment();

    const record = {
      network: "hardhat",
      chainId: Number((await ethers.provider.getNetwork()).chainId),
      deployer: await (await ethers.getSigners())[0].getAddress(),
      assetRegistry: await assetRegistry.getAddress(),
      financingPool: await financingPool.getAddress(),
      paymentToken: await mockUSDT.getAddress(),
      deployedAt: new Date().toISOString(),
    };

    const serialized = JSON.stringify(record);
    expect(serialized).to.not.include("PRIVATE_KEY");
    expect(serialized).to.not.include("RPC_URL");
    expect(serialized).to.not.include("Authorization");
    expect(serialized).to.not.include("Bearer");

    expect(record.assetRegistry).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(record.financingPool).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(record.paymentToken).to.match(/^0x[a-fA-F0-9]{40}$/);
  });

  it("Should allow importing deployment script without side effects", async function () {
    const deployModule = require("../scripts/deploy.js");
    expect(typeof deployModule.deploy).to.equal("function");
  });
});
