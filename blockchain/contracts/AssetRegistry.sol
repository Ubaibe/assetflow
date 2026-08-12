// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

contract AssetRegistry is Ownable, Pausable {
    enum AssetStatus {
        LISTED,
        PARTIALLY_FUNDED,
        FULLY_FUNDED,
        REPAID,
        SETTLED,
        CANCELLED,
        DEFAULTED
    }

    uint256 public nextAssetId;
    mapping(bytes32 => uint256) public hashToAssetId;
    mapping(bytes32 => bool) private hashExists;

    struct Asset {
        uint256 assetId;
        bytes32 assetHash;
        address originator;
        uint256 faceValue;
        uint256 financingTarget;
        uint256 maturityTimestamp;
        uint256 riskScore;
        AssetStatus status;
    }

    mapping(uint256 => Asset) public assets;

    event AssetCreated(
        uint256 indexed assetId,
        bytes32 indexed assetHash,
        address indexed originator,
        uint256 faceValue,
        uint256 financingTarget,
        uint256 maturityTimestamp,
        uint256 riskScore
    );
    event AssetStatusUpdated(uint256 indexed assetId, AssetStatus newStatus);
    event AssetVerified(uint256 indexed assetId);
    event AssetCancelled(uint256 indexed assetId);

    error AssetHashAlreadyExists();
    error AssetNotFound();
    error InvalidStatusTransition();
    error Unauthorized();
    error AlreadyFinalized();

    address public financingPool;

    constructor() Ownable(msg.sender) {}

    function setFinancingPool(address pool) external onlyOwner {
        financingPool = pool;
    }

    function createAsset(
        bytes32 assetHash,
        address originator,
        uint256 faceValue,
        uint256 financingTarget,
        uint256 maturityTimestamp,
        uint256 riskScore
    ) external whenNotPaused returns (uint256) {
        if (hashExists[assetHash]) revert AssetHashAlreadyExists();

        uint256 assetId = nextAssetId++;
        hashToAssetId[assetHash] = assetId;
        hashExists[assetHash] = true;

        assets[assetId] = Asset({
            assetId: assetId,
            assetHash: assetHash,
            originator: originator,
            faceValue: faceValue,
            financingTarget: financingTarget,
            maturityTimestamp: maturityTimestamp,
            riskScore: riskScore,
            status: AssetStatus.LISTED
        });

        emit AssetCreated(assetId, assetHash, originator, faceValue, financingTarget, maturityTimestamp, riskScore);
        return assetId;
    }

    function getAsset(uint256 assetId) external view returns (Asset memory) {
        if (assetId >= nextAssetId) revert AssetNotFound();
        return assets[assetId];
    }

    function updateAssetStatus(uint256 assetId, AssetStatus newStatus) external onlyOwner whenNotPaused {
        if (assetId >= nextAssetId) revert AssetNotFound();

        Asset storage asset = assets[assetId];
        AssetStatus current = asset.status;
        if (current == AssetStatus.SETTLED || current == AssetStatus.CANCELLED || current == AssetStatus.DEFAULTED) {
            revert AlreadyFinalized();
        }

        if (current == AssetStatus.LISTED && newStatus != AssetStatus.PARTIALLY_FUNDED && newStatus != AssetStatus.CANCELLED) {
            revert InvalidStatusTransition();
        }
        if (current == AssetStatus.PARTIALLY_FUNDED && newStatus != AssetStatus.FULLY_FUNDED && newStatus != AssetStatus.CANCELLED) {
            revert InvalidStatusTransition();
        }
        if (current == AssetStatus.FULLY_FUNDED && newStatus != AssetStatus.REPAID && newStatus != AssetStatus.DEFAULTED) {
            revert InvalidStatusTransition();
        }
        if (current == AssetStatus.REPAID && newStatus != AssetStatus.SETTLED) {
            revert InvalidStatusTransition();
        }

        asset.status = newStatus;
        emit AssetStatusUpdated(assetId, newStatus);
    }

    function cancelAsset(uint256 assetId) external onlyOwner whenNotPaused {
        if (assetId >= nextAssetId) revert AssetNotFound();
        Asset storage asset = assets[assetId];
        if (asset.status != AssetStatus.LISTED && asset.status != AssetStatus.PARTIALLY_FUNDED) {
            revert InvalidStatusTransition();
        }
        asset.status = AssetStatus.CANCELLED;
        emit AssetCancelled(assetId);
        emit AssetStatusUpdated(assetId, AssetStatus.CANCELLED);
    }

    function verifyAsset(uint256 assetId) external onlyOwner whenNotPaused {
        if (assetId >= nextAssetId) revert AssetNotFound();
        emit AssetVerified(assetId);
    }

    function getAssetStatus(uint256 assetId) external view returns (uint8) {
        if (assetId >= nextAssetId) revert AssetNotFound();
        return uint8(assets[assetId].status);
    }

    function getAssetFinancingTarget(uint256 assetId) external view returns (uint256) {
        if (assetId >= nextAssetId) revert AssetNotFound();
        return assets[assetId].financingTarget;
    }

    function getAssetOriginator(uint256 assetId) external view returns (address) {
        if (assetId >= nextAssetId) revert AssetNotFound();
        return assets[assetId].originator;
    }

    function confirmRepaid(uint256 assetId) external {
        if (msg.sender != financingPool) revert Unauthorized();
        if (assetId >= nextAssetId) revert AssetNotFound();

        Asset storage asset = assets[assetId];
        if (asset.status != AssetStatus.FULLY_FUNDED) revert InvalidStatusTransition();

        asset.status = AssetStatus.REPAID;
        emit AssetStatusUpdated(assetId, AssetStatus.REPAID);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }
}
