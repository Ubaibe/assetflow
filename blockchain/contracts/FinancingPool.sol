// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

interface IAssetRegistry {
    function confirmRepaid(uint256 assetId) external;
}

contract FinancingPool is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    IERC20 public immutable paymentToken;
    address public immutable assetRegistry;

    struct FundingState {
        uint256 totalFunded;
        uint256 totalRepaid;
        bool exists;
    }

    mapping(uint256 => FundingState) public fundingStates;
    mapping(uint256 => mapping(address => uint256)) public investmentOf;

    event AssetFunded(uint256 indexed assetId, address indexed investor, uint256 amount);
    event FundingCompleted(uint256 indexed assetId, uint256 totalFunded);
    event RepaymentReceived(uint256 indexed assetId, address indexed payer, uint256 amount);
    event ReturnsClaimed(uint256 indexed assetId, address indexed investor, uint256 amount);

    error AssetNotFound();
    error InvalidAssetStatus();
    error Overfunding();
    error UnauthorizedRepayment();
    error NotRepaid();
    error ZeroAmount();
    error NoInvestment();

    constructor(address paymentToken_, address assetRegistry_) Ownable(msg.sender) {
        paymentToken = IERC20(paymentToken_);
        assetRegistry = assetRegistry_;
    }

    function fund(uint256 assetId, uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();

        FundingState storage state = fundingStates[assetId];
        if (!state.exists) {
            state.exists = true;
        }

        (bool exists, uint8 status) = _getAssetStatus(assetId);
        if (!exists) revert AssetNotFound();
        if (status != 0 && status != 1) {
            revert InvalidAssetStatus();
        }

        uint256 financingTarget = _getFinancingTarget(assetId);
        if (state.totalFunded + amount > financingTarget) revert Overfunding();

        state.totalFunded += amount;
        investmentOf[assetId][msg.sender] += amount;

        paymentToken.safeTransferFrom(msg.sender, address(this), amount);

        emit AssetFunded(assetId, msg.sender, amount);

        if (state.totalFunded == financingTarget) {
            emit FundingCompleted(assetId, state.totalFunded);
        }
    }

    function repay(uint256 assetId, uint256 amount) external whenNotPaused nonReentrant {
        if (amount == 0) revert ZeroAmount();

        (bool exists, uint8 status) = _getAssetStatus(assetId);
        if (!exists) revert AssetNotFound();
        if (status != 2 && status != 3) {
            revert InvalidAssetStatus();
        }

        address originator = _getOriginator(assetId);
        if (msg.sender != originator) revert UnauthorizedRepayment();

        FundingState storage state = fundingStates[assetId];
        state.totalRepaid += amount;

        paymentToken.safeTransferFrom(msg.sender, address(this), amount);

        emit RepaymentReceived(assetId, msg.sender, amount);

        if (status == 2) {
            IAssetRegistry(assetRegistry).confirmRepaid(assetId);
        }
    }

    function claim(uint256 assetId) external whenNotPaused nonReentrant {
        (bool exists, uint8 status) = _getAssetStatus(assetId);
        if (!exists) revert AssetNotFound();
        if (status != 3) revert NotRepaid();

        uint256 investorBalance = investmentOf[assetId][msg.sender];
        if (investorBalance == 0) revert NoInvestment();

        FundingState storage state = fundingStates[assetId];
        if (state.totalRepaid == 0) revert NoInvestment();

        uint256 claimable = (investorBalance * state.totalRepaid) / state.totalFunded;
        if (claimable == 0) revert NoInvestment();

        investmentOf[assetId][msg.sender] = 0;

        paymentToken.safeTransfer(msg.sender, claimable);

        emit ReturnsClaimed(assetId, msg.sender, claimable);
    }

    function getFundingState(uint256 assetId) external view returns (uint256 totalFunded, uint256 totalRepaid, bool exists) {
        FundingState memory state = fundingStates[assetId];
        return (state.totalFunded, state.totalRepaid, state.exists);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _getAssetStatus(uint256 assetId) internal view returns (bool, uint8) {
        (bool success, bytes memory data) = assetRegistry.staticcall(abi.encodeWithSignature("getAssetStatus(uint256)", assetId));
        if (!success || data.length == 0) return (false, 0);

        uint8 status = abi.decode(data, (uint8));
        return (true, status);
    }

    function _getFinancingTarget(uint256 assetId) internal view returns (uint256) {
        (bool success, bytes memory data) = assetRegistry.staticcall(abi.encodeWithSignature("getAssetFinancingTarget(uint256)", assetId));
        if (!success || data.length == 0) revert AssetNotFound();

        uint256 financingTarget_ = abi.decode(data, (uint256));
        return financingTarget_;
    }

    function _getOriginator(uint256 assetId) internal view returns (address) {
        (bool success, bytes memory data) = assetRegistry.staticcall(abi.encodeWithSignature("getAssetOriginator(uint256)", assetId));
        if (!success || data.length == 0) revert AssetNotFound();

        address originator_ = abi.decode(data, (address));
        return originator_;
    }
}
