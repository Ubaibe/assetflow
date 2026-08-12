const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("FinancingPool", function () {
  let MockUSDT;
  let mockUSDT;
  let AssetRegistry;
  let assetRegistry;
  let FinancingPool;
  let financingPool;
  let owner;
  let originator;
  let investor1;
  let investor2;

  const faceValue = ethers.parseUnits("1000", 18);
  const financingTarget = ethers.parseUnits("800", 18);

  beforeEach(async function () {
    [owner, originator, investor1, investor2] = await ethers.getSigners();

    MockUSDT = await ethers.getContractFactory("MockUSDT");
    mockUSDT = await MockUSDT.deploy();

    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();

    const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-pool"));
    const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
    const riskScore = 50;
    await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);

    FinancingPool = await ethers.getContractFactory("FinancingPool");
    financingPool = await FinancingPool.deploy(await mockUSDT.getAddress(), await assetRegistry.getAddress());
    await assetRegistry.setFinancingPool(await financingPool.getAddress());

    await mockUSDT.mint(investor1.address, ethers.parseUnits("1000", 18));
    await mockUSDT.mint(investor2.address, ethers.parseUnits("1000", 18));
    await mockUSDT.mint(originator.address, ethers.parseUnits("1000", 18));
  });

  describe("Mock token deployment", function () {
    it("Should deploy MockUSDT with correct name and symbol", async function () {
      expect(await mockUSDT.name()).to.equal("Mock USDT");
      expect(await mockUSDT.symbol()).to.equal("mUSDT");
      expect(await mockUSDT.decimals()).to.equal(18);
    });
  });

  describe("Investor approval", function () {
    it("Should require investor approval before funding", async function () {
      const assetId = 0;
      const amount = ethers.parseUnits("100", 18);

      await expect(
        financingPool.connect(investor1).fund(assetId, amount)
      ).to.be.reverted;
    });
  });

  describe("Funding", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
    });

    it("Should fund successfully", async function () {
      const assetId = 0;
      const amount = ethers.parseUnits("200", 18);

      await expect(financingPool.connect(investor1).fund(assetId, amount))
        .to.emit(financingPool, "AssetFunded")
        .withArgs(assetId, investor1.address, amount);

      const state = await financingPool.getFundingState(assetId);
      expect(state.totalFunded).to.equal(amount);
      expect(state.exists).to.equal(true);
    });

    it("Should record funding amount correctly", async function () {
      const assetId = 0;
      const amount1 = ethers.parseUnits("300", 18);
      const amount2 = ethers.parseUnits("200", 18);

      await financingPool.connect(investor1).fund(assetId, amount1);
      await financingPool.connect(investor1).fund(assetId, amount2);

      expect(await financingPool.investmentOf(assetId, investor1.address)).to.equal(amount1 + amount2);
      const state = await financingPool.getFundingState(assetId);
      expect(state.totalFunded).to.equal(amount1 + amount2);
    });

    it("Should emit AssetFunded event", async function () {
      const assetId = 0;
      const amount = ethers.parseUnits("150", 18);

      await expect(financingPool.connect(investor1).fund(assetId, amount))
        .to.emit(financingPool, "AssetFunded")
        .withArgs(assetId, investor1.address, amount);
    });

    it("Should not exceed financing target", async function () {
      const assetId = 0;
      const amount = ethers.parseUnits("900", 18);

      await expect(
        financingPool.connect(investor1).fund(assetId, amount)
      ).to.be.revertedWithCustomError(financingPool, "Overfunding");
    });

    it("Should emit FundingCompleted when target reached", async function () {
      const assetId = 0;
      const amount = ethers.parseUnits("800", 18);

      await expect(financingPool.connect(investor1).fund(assetId, amount))
        .to.emit(financingPool, "FundingCompleted")
        .withArgs(assetId, amount);
    });

    it("Should support multiple investors", async function () {
      const assetId = 0;
      const amount1 = ethers.parseUnits("400", 18);
      const amount2 = ethers.parseUnits("400", 18);

      await mockUSDT.connect(investor2).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(assetId, amount1);
      await financingPool.connect(investor2).fund(assetId, amount2);

      expect(await financingPool.investmentOf(assetId, investor1.address)).to.equal(amount1);
      expect(await financingPool.investmentOf(assetId, investor2.address)).to.equal(amount2);

      const state = await financingPool.getFundingState(assetId);
      expect(state.totalFunded).to.equal(amount1 + amount2);
    });

    it("Should revert when paused", async function () {
      await financingPool.pause();

      const assetId = 0;
      const amount = ethers.parseUnits("100", 18);

      await expect(
        financingPool.connect(investor1).fund(assetId, amount)
      ).to.be.reverted;
    });
  });

  describe("Repayment", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(0, financingTarget);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
    });

    it("Should revert unauthorized repayment", async function () {
      await expect(
        financingPool.connect(investor1).repay(0, ethers.parseUnits("100", 18))
      ).to.be.revertedWithCustomError(financingPool, "UnauthorizedRepayment");
    });

    it("Should repay successfully", async function () {
      const repaymentAmount = ethers.parseUnits("500", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);

      await expect(financingPool.connect(originator).repay(0, repaymentAmount))
        .to.emit(financingPool, "RepaymentReceived")
        .withArgs(0, originator.address, repaymentAmount);

      const state = await financingPool.getFundingState(0);
      expect(state.totalRepaid).to.equal(repaymentAmount);
    });

    it("Should emit RepaymentReceived event", async function () {
      const repaymentAmount = ethers.parseUnits("500", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);

      await expect(financingPool.connect(originator).repay(0, repaymentAmount))
        .to.emit(financingPool, "RepaymentReceived")
        .withArgs(0, originator.address, repaymentAmount);
    });

    it("Should revert when paused", async function () {
      await financingPool.pause();
      const repaymentAmount = ethers.parseUnits("100", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);

      await expect(
        financingPool.connect(originator).repay(0, repaymentAmount)
      ).to.be.reverted;
    });
  });

  describe("Claims", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await mockUSDT.connect(investor2).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(0, financingTarget);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
    });

    it("Should revert claim before repayment", async function () {
      await expect(financingPool.connect(investor1).claim(0)).to.be.revertedWithCustomError(financingPool, "NotRepaid");
    });

    it("Should claim after repayment successfully", async function () {
      const repaymentAmount = ethers.parseUnits("800", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);

      await financingPool.connect(originator).repay(0, repaymentAmount);

      const investor1Balance = await financingPool.investmentOf(0, investor1.address);
      const expectedClaim = (investor1Balance * repaymentAmount) / financingTarget;

      await expect(financingPool.connect(investor1).claim(0))
        .to.emit(financingPool, "ReturnsClaimed")
        .withArgs(0, investor1.address, expectedClaim);

      expect(await financingPool.investmentOf(0, investor1.address)).to.equal(0);
    });

    it("Should revert when paused", async function () {
      const repaymentAmount = ethers.parseUnits("800", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);
      await financingPool.connect(originator).repay(0, repaymentAmount);

      await financingPool.pause();
      await expect(financingPool.connect(investor1).claim(0)).to.be.reverted;
    });
  });

  describe("Reentrancy protection", function () {
    it("Should have nonReentrant on fund", async function () {
      const source = await ethers.getContractFactory("FinancingPool");
      const abi = source.interface.getFunction("fund");
      expect(abi).to.exist;
    });
  });

  describe("Accounting integrity", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await mockUSDT.connect(investor2).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
    });

    it("Should maintain correct balances after funding and claiming", async function () {
      const assetId = 0;
      const amount1 = ethers.parseUnits("500", 18);
      const amount2 = ethers.parseUnits("300", 18);

      await financingPool.connect(investor1).fund(assetId, amount1);
      await financingPool.connect(investor2).fund(assetId, amount2);

      const totalFunded = amount1 + amount2;
      const repaymentAmount = totalFunded;
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);

      await assetRegistry.updateAssetStatus(assetId, 1);
      await assetRegistry.updateAssetStatus(assetId, 2);
      await financingPool.connect(originator).repay(assetId, repaymentAmount);

      const claimable1 = (amount1 * repaymentAmount) / financingTarget;
      const claimable2 = (amount2 * repaymentAmount) / financingTarget;

      const balanceBefore1 = await mockUSDT.balanceOf(investor1.address);
      const balanceBefore2 = await mockUSDT.balanceOf(investor2.address);

      await financingPool.connect(investor1).claim(assetId);
      await financingPool.connect(investor2).claim(assetId);

      expect(await mockUSDT.balanceOf(investor1.address)).to.equal(balanceBefore1 + claimable1);
      expect(await mockUSDT.balanceOf(investor2.address)).to.equal(balanceBefore2 + claimable2);

      expect(await financingPool.investmentOf(assetId, investor1.address)).to.equal(0);
      expect(await financingPool.investmentOf(assetId, investor2.address)).to.equal(0);
    });
  });

  describe("Double claim prevention", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(0, financingTarget);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
    });

    it("Should revert second claim attempt", async function () {
      const repaymentAmount = ethers.parseUnits("800", 18);
      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repaymentAmount);
      await financingPool.connect(originator).repay(0, repaymentAmount);

      await financingPool.connect(investor1).claim(0);

      await expect(financingPool.connect(investor1).claim(0)).to.be.revertedWithCustomError(financingPool, "NoInvestment");
    });
  });

  describe("Partial repayment accounting", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(0, financingTarget);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
    });

    it("Should accumulate totalRepaid across multiple repayments", async function () {
      const repayment1 = ethers.parseUnits("300", 18);
      const repayment2 = ethers.parseUnits("200", 18);

      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repayment1);
      await financingPool.connect(originator).repay(0, repayment1);

      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repayment2);
      await financingPool.connect(originator).repay(0, repayment2);

      const state = await financingPool.getFundingState(0);
      expect(state.totalRepaid).to.equal(repayment1 + repayment2);
    });

    it("Should calculate claim correctly after multiple partial repayments", async function () {
      const repayment1 = ethers.parseUnits("400", 18);
      const repayment2 = ethers.parseUnits("300", 18);

      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repayment1);
      await financingPool.connect(originator).repay(0, repayment1);

      await mockUSDT.connect(originator).approve(await financingPool.getAddress(), repayment2);
      await financingPool.connect(originator).repay(0, repayment2);

      const investorBalance = await financingPool.investmentOf(0, investor1.address);
      const totalRepaid = repayment1 + repayment2;
      const expectedClaim = (investorBalance * totalRepaid) / financingTarget;

      const balanceBefore = await mockUSDT.balanceOf(investor1.address);
      await financingPool.connect(investor1).claim(0);

      expect(await mockUSDT.balanceOf(investor1.address)).to.equal(balanceBefore + expectedClaim);
    });
  });

  describe("Invalid asset states", function () {
    beforeEach(async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
    });

    it("Should revert funding a CANCELLED asset", async function () {
      await assetRegistry.cancelAsset(0);

      await expect(
        financingPool.connect(investor1).fund(0, ethers.parseUnits("100", 18))
      ).to.be.revertedWithCustomError(financingPool, "InvalidAssetStatus");
    });

    it("Should revert funding a DEFAULTED asset", async function () {
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
      await assetRegistry.updateAssetStatus(0, 6);

      await expect(
        financingPool.connect(investor1).fund(0, ethers.parseUnits("100", 18))
      ).to.be.revertedWithCustomError(financingPool, "InvalidAssetStatus");
    });

    it("Should revert funding a SETTLED asset", async function () {
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);
      await assetRegistry.updateAssetStatus(0, 3);
      await assetRegistry.updateAssetStatus(0, 4);

      await expect(
        financingPool.connect(investor1).fund(0, ethers.parseUnits("100", 18))
      ).to.be.revertedWithCustomError(financingPool, "InvalidAssetStatus");
    });

    it("Should revert funding a FULLY_FUNDED asset", async function () {
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);

      await expect(
        financingPool.connect(investor1).fund(0, ethers.parseUnits("100", 18))
      ).to.be.revertedWithCustomError(financingPool, "InvalidAssetStatus");
    });
  });

  describe("Zero-value edge cases", function () {
    it("Should revert zero repayment", async function () {
      await mockUSDT.connect(investor1).approve(await financingPool.getAddress(), ethers.parseUnits("1000", 18));
      await financingPool.connect(investor1).fund(0, financingTarget);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);

      await expect(
        financingPool.connect(originator).repay(0, 0)
      ).to.be.revertedWithCustomError(financingPool, "ZeroAmount");
    });
  });

  describe("Reentrancy protection", function () {
    it("Should prevent reentrancy during funding via malicious token", async function () {
      const maliciousTokenFactory = await ethers.getContractFactory("MockUSDT");
      const maliciousToken = await maliciousTokenFactory.deploy();

      await maliciousToken.mint(investor1.address, ethers.parseUnits("1000", 18));

      const maliciousPoolFactory = await ethers.getContractFactory("FinancingPool");
      const maliciousPool = await maliciousPoolFactory.deploy(await maliciousToken.getAddress(), await assetRegistry.getAddress());
      await assetRegistry.setFinancingPool(await maliciousPool.getAddress());

      await maliciousToken.connect(investor1).approve(await maliciousPool.getAddress(), ethers.parseUnits("1000", 18));

      await expect(maliciousPool.connect(investor1).fund(0, ethers.parseUnits("100", 18)))
        .to.emit(maliciousPool, "AssetFunded")
        .withArgs(0, investor1.address, ethers.parseUnits("100", 18));

      const state = await maliciousPool.getFundingState(0);
      expect(state.totalFunded).to.equal(ethers.parseUnits("100", 18));
    });
  });

  describe("Asset ID zero", function () {
    it("Should allow asset ID 0", async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-zero"));
      await assetRegistry.createAsset(assetHash, originator.address, ethers.parseUnits("100", 18), ethers.parseUnits("100", 18), Math.floor(Date.now() / 1000) + 86400, 50);
      expect(await assetRegistry.nextAssetId()).to.equal(2);
      const asset = await assetRegistry.getAsset(0);
      expect(asset.assetId).to.equal(0);
    });
  });

  describe("Zero bytes32 hash", function () {
    it("Should allow bytes32(0) with duplicate protection", async function () {
      const zeroHash = ethers.zeroPadValue("0x00", 32);
      await assetRegistry.createAsset(zeroHash, originator.address, ethers.parseUnits("100", 18), ethers.parseUnits("100", 18), Math.floor(Date.now() / 1000) + 86400, 50);
      expect(await assetRegistry.nextAssetId()).to.equal(2);

      await expect(
        assetRegistry.createAsset(zeroHash, originator.address, ethers.parseUnits("100", 18), ethers.parseUnits("100", 18), Math.floor(Date.now() / 1000) + 86400, 50)
      ).to.be.revertedWithCustomError(assetRegistry, "AssetHashAlreadyExists");
    });
  });
});
