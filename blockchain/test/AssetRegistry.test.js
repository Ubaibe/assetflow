const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AssetRegistry", function () {
  let AssetRegistry;
  let assetRegistry;
  let owner;
  let originator;
  let other;

  beforeEach(async function () {
    [owner, originator, other] = await ethers.getSigners();
    AssetRegistry = await ethers.getContractFactory("AssetRegistry");
    assetRegistry = await AssetRegistry.deploy();
  });

  describe("Deployment", function () {
    it("Should set the correct owner", async function () {
      expect(await assetRegistry.owner()).to.equal(owner.address);
    });
  });

  describe("Asset creation", function () {
    it("Should create an asset successfully", async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-1"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 75;

      const tx = await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
      const receipt = await tx.wait();

      expect(await assetRegistry.nextAssetId()).to.equal(1);
      expect(await assetRegistry.hashToAssetId(assetHash)).to.equal(0);

      const asset = await assetRegistry.getAsset(0);
      expect(asset.assetId).to.equal(0);
      expect(asset.assetHash).to.equal(assetHash);
      expect(asset.originator).to.equal(originator.address);
      expect(asset.faceValue).to.equal(faceValue);
      expect(asset.financingTarget).to.equal(financingTarget);
      expect(asset.maturityTimestamp).to.equal(maturityTimestamp);
      expect(asset.riskScore).to.equal(riskScore);
      expect(asset.status).to.equal(0);

      await expect(tx).to.emit(assetRegistry, "AssetCreated")
        .withArgs(0, assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should record correct originator when originator != msg.sender", async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-originator"));
      const faceValue = ethers.parseUnits("500", 18);
      const financingTarget = ethers.parseUnits("400", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 60;

      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
      const asset = await assetRegistry.getAsset(0);
      expect(asset.originator).to.equal(originator.address);
      expect(asset.originator).to.not.equal(owner.address);
    });

    it("Should revert on duplicate asset hash", async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-duplicate"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;

      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);

      await expect(
        assetRegistry.createAsset(assetHash, other.address, faceValue, financingTarget, maturityTimestamp, riskScore)
      ).to.be.revertedWithCustomError(assetRegistry, "AssetHashAlreadyExists");
    });

    it("Should increment asset ID correctly", async function () {
      const assetHash1 = ethers.keccak256(ethers.toUtf8Bytes("asset-id-1"));
      const assetHash2 = ethers.keccak256(ethers.toUtf8Bytes("asset-id-2"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;

      await assetRegistry.createAsset(assetHash1, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
      await assetRegistry.createAsset(assetHash2, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);

      expect(await assetRegistry.nextAssetId()).to.equal(2);

      const asset0 = await assetRegistry.getAsset(0);
      const asset1 = await assetRegistry.getAsset(1);
      expect(asset0.assetId).to.equal(0);
      expect(asset1.assetId).to.equal(1);
    });

    it("Should emit correct AssetCreated event", async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-event"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;

      await expect(
        assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore)
      ).to.emit(assetRegistry, "AssetCreated")
        .withArgs(0, assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should revert when paused", async function () {
      await assetRegistry.pause();

      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-paused"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;

      await expect(
        assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore)
      ).to.be.reverted;
    });
  });

  describe("Status updates", function () {
    beforeEach(async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-status"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;
      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should revert unauthorized status update", async function () {
      await expect(
        assetRegistry.connect(other).updateAssetStatus(0, 1)
      ).to.be.revertedWithCustomError(assetRegistry, "OwnableUnauthorizedAccount");
    });

    it("Should allow valid status transition", async function () {
      await expect(assetRegistry.updateAssetStatus(0, 1))
        .to.emit(assetRegistry, "AssetStatusUpdated")
        .withArgs(0, 1);

      const asset = await assetRegistry.getAsset(0);
      expect(asset.status).to.equal(1);
    });

    it("Should revert invalid status transition", async function () {
      await assetRegistry.updateAssetStatus(0, 1);
      await expect(
        assetRegistry.updateAssetStatus(0, 0)
      ).to.be.revertedWithCustomError(assetRegistry, "InvalidStatusTransition");
    });

    it("Should revert when paused", async function () {
      await assetRegistry.pause();
      await expect(
        assetRegistry.updateAssetStatus(0, 1)
      ).to.be.reverted;
    });
  });

  describe("Cancellation", function () {
    beforeEach(async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-cancel"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;
      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should revert unauthorized cancellation", async function () {
      await expect(
        assetRegistry.connect(other).cancelAsset(0)
      ).to.be.revertedWithCustomError(assetRegistry, "OwnableUnauthorizedAccount");
    });

    it("Should cancel asset successfully", async function () {
      await expect(assetRegistry.cancelAsset(0))
        .to.emit(assetRegistry, "AssetCancelled")
        .withArgs(0);

      const asset = await assetRegistry.getAsset(0);
      expect(asset.status).to.equal(5);
    });

    it("Should revert when paused", async function () {
      await assetRegistry.pause();
      await expect(
        assetRegistry.cancelAsset(0)
      ).to.be.reverted;
    });
  });

  describe("Verification", function () {
    beforeEach(async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-verify"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;
      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should revert unauthorized verification", async function () {
      await expect(
        assetRegistry.connect(other).verifyAsset(0)
      ).to.be.revertedWithCustomError(assetRegistry, "OwnableUnauthorizedAccount");
    });

    it("Should verify asset successfully", async function () {
      await expect(assetRegistry.verifyAsset(0))
        .to.emit(assetRegistry, "AssetVerified")
        .withArgs(0);
    });

    it("Should revert when paused", async function () {
      await assetRegistry.pause();
      await expect(
        assetRegistry.verifyAsset(0)
      ).to.be.reverted;
    });
  });

  describe("Pause functionality", function () {
    beforeEach(async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-pause"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;
      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should allow only owner to pause", async function () {
      await expect(assetRegistry.connect(other).pause()).to.be.revertedWithCustomError(assetRegistry, "OwnableUnauthorizedAccount");
      await assetRegistry.pause();
      expect(await assetRegistry.paused()).to.equal(true);
    });

    it("Should allow only owner to unpause", async function () {
      await assetRegistry.pause();
      await expect(assetRegistry.connect(other).unpause()).to.be.revertedWithCustomError(assetRegistry, "OwnableUnauthorizedAccount");
      await assetRegistry.unpause();
      expect(await assetRegistry.paused()).to.equal(false);
    });

    it("Should restore operation after unpausing", async function () {
      await assetRegistry.pause();
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-unpause"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;

      await expect(
        assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore)
      ).to.be.reverted;

      await assetRegistry.unpause();

      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
      expect(await assetRegistry.nextAssetId()).to.equal(2);
    });
  });

  describe("FinancingPool authorization", function () {
    beforeEach(async function () {
      const assetHash = ethers.keccak256(ethers.toUtf8Bytes("asset-pool-auth"));
      const faceValue = ethers.parseUnits("1000", 18);
      const financingTarget = ethers.parseUnits("800", 18);
      const maturityTimestamp = Math.floor(Date.now() / 1000) + 86400 * 30;
      const riskScore = 50;
      await assetRegistry.createAsset(assetHash, originator.address, faceValue, financingTarget, maturityTimestamp, riskScore);
    });

    it("Should allow owner to set financing pool", async function () {
      await assetRegistry.setFinancingPool(other.address);

      expect(await assetRegistry.financingPool()).to.equal(other.address);
    });

    it("Should revert unauthorized confirmRepaid", async function () {
      await expect(
        assetRegistry.connect(other).confirmRepaid(0)
      ).to.be.revertedWithCustomError(assetRegistry, "Unauthorized");
    });

    it("Should allow authorized pool to confirm repaid", async function () {
      await assetRegistry.setFinancingPool(owner.address);
      await assetRegistry.updateAssetStatus(0, 1);
      await assetRegistry.updateAssetStatus(0, 2);

      await expect(assetRegistry.confirmRepaid(0))
        .to.emit(assetRegistry, "AssetStatusUpdated")
        .withArgs(0, 3);

      expect(await assetRegistry.getAssetStatus(0)).to.equal(3);
    });

    it("Should revert confirmRepaid on invalid status", async function () {
      await assetRegistry.setFinancingPool(owner.address);

      await expect(assetRegistry.confirmRepaid(0))
        .to.be.revertedWithCustomError(assetRegistry, "InvalidStatusTransition");
    });
  });
});
