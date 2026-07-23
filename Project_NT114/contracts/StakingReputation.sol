// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./ReputationVerifier.sol";

/// @title StakingReputation
/// @notice Decentralized FL incentive mechanism with staking, slashing, on-chain
///         Groth16 verification, and Shapley-value-based reward distribution.
/// @dev Inherits Groth16Verifier from ReputationVerifier.sol for on-chain ZKP checks.
contract StakingReputation is Groth16Verifier {

    // ======================== Constants ========================

    uint256 public constant MIN_STAKE = 0.01 ether;
    uint256 public constant SLASH_THRESHOLD = 3;
    uint256 public constant SLASH_PERCENT = 30; // 30%
    uint256 public constant MAX_REPUTATION = 200;

    // ======================== State ========================

    address public owner;
    address public aggregator;

    struct ClientInfo {
        uint256 stake;
        bool isRegistered;
        uint256 reputation;        // starts at 100, max 200
        uint256 consecutiveFailures;
        uint256 totalRoundsParticipated;
        uint256 totalRewardsEarned;
        uint256 pendingRewards;
    }

    struct Update {
        uint256 round;
        uint256 clientId;
        string cid;
        string proofHash;
        uint256 accuracy;
        bool verified;
    }

    mapping(uint256 => ClientInfo) public clients;
    Update[] public updates;

    // ======================== Events ========================

    event ClientRegistered(uint256 indexed clientId, uint256 stake);
    event UpdateSubmitted(uint256 indexed round, uint256 indexed clientId, string cid, uint256 accuracy);
    event UpdateVerified(uint256 indexed round, uint256 indexed clientId, bool result);
    event StakeSlashed(uint256 indexed clientId, uint256 amount, uint256 remaining);
    event RewardDistributed(uint256 indexed round, uint256 indexed clientId, uint256 amount);
    event StakeWithdrawn(uint256 indexed clientId, uint256 amount);
    event RewardWithdrawn(uint256 indexed clientId, uint256 amount);

    // ======================== Modifiers ========================

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner allowed");
        _;
    }

    modifier onlyAggregator() {
        require(msg.sender == aggregator, "Only aggregator allowed");
        _;
    }

    // ======================== Constructor ========================

    constructor() {
        owner = msg.sender;
        aggregator = msg.sender;
    }

    // ======================== Registration ========================

    /// @notice Register a client with a stake deposit.
    /// @param clientId The unique identifier for the FL client.
    function registerClient(uint256 clientId) external payable {
        require(msg.value >= MIN_STAKE, "Insufficient stake");
        require(!clients[clientId].isRegistered, "Client already registered");

        clients[clientId] = ClientInfo({
            stake: msg.value,
            isRegistered: true,
            reputation: 100,
            consecutiveFailures: 0,
            totalRoundsParticipated: 0,
            totalRewardsEarned: 0,
            pendingRewards: 0
        });

        emit ClientRegistered(clientId, msg.value);
    }

    // ======================== Update Submission ========================

    /// @notice Submit a model update for a given round.
    function submitUpdate(
        uint256 round,
        uint256 clientId,
        string memory cid,
        string memory proofHash,
        uint256 accuracy
    ) external {
        require(clients[clientId].isRegistered, "Client not registered");
        require(clients[clientId].stake > 0, "Client has no stake");

        updates.push(Update({
            round: round,
            clientId: clientId,
            cid: cid,
            proofHash: proofHash,
            accuracy: accuracy,
            verified: false
        }));

        emit UpdateSubmitted(round, clientId, cid, accuracy);
    }

    // ======================== On-Chain ZKP Verification ========================

    /// @notice Verify a client update using an on-chain Groth16 proof.
    /// @dev The contract performs elliptic curve pairing checks via EVM precompiles.
    function verifyUpdateWithProof(
        uint256 clientId,
        uint256 round,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[4] calldata publicSignals
    ) external {
        require(clients[clientId].isRegistered, "Client not registered");
        require(publicSignals[1] == clientId, "client mismatch");
        require(publicSignals[2] == round, "round mismatch");

        bool isValid = verifyProof(a, b, c, publicSignals);
        _handleVerificationResult(clientId, round, isValid);
    }

    // ======================== Off-Chain Verification Fallback ========================

    /// @notice Record the result of an off-chain verification performed by the aggregator.
    function verifyUpdate(
        uint256 clientId,
        uint256 round,
        bool result
    ) external onlyAggregator {
        require(clients[clientId].isRegistered, "Client not registered");
        _handleVerificationResult(clientId, round, result);
    }

    // ======================== Internal Verification Logic ========================

    function _handleVerificationResult(
        uint256 clientId,
        uint256 round,
        bool result
    ) internal {
        ClientInfo storage client = clients[clientId];

        // Find and update the matching submission
        for (uint256 i = 0; i < updates.length; i++) {
            if (updates[i].clientId == clientId && updates[i].round == round) {
                updates[i].verified = result;
                break;
            }
        }

        if (result) {
            // Reward: increment reputation (capped)
            client.reputation += 10;
            if (client.reputation > MAX_REPUTATION) {
                client.reputation = MAX_REPUTATION;
            }
            client.consecutiveFailures = 0;
            client.totalRoundsParticipated += 1;
        } else {
            // Penalty: decrement reputation (floored at 0)
            if (client.reputation >= 20) {
                client.reputation -= 20;
            } else {
                client.reputation = 0;
            }
            client.consecutiveFailures += 1;

            // Slash if consecutive failures exceed threshold
            if (client.consecutiveFailures >= SLASH_THRESHOLD) {
                uint256 slashAmount = (client.stake * SLASH_PERCENT) / 100;
                client.stake -= slashAmount;
                client.consecutiveFailures = 0;
                emit StakeSlashed(clientId, slashAmount, client.stake);
            }
        }

        emit UpdateVerified(round, clientId, result);
    }

    // ======================== Reward Distribution ========================

    /// @notice Fund the reward pool. Anyone can deposit ETH.
    function depositRewardPool() external payable {}

    /// @notice Distribute rewards based on Shapley-value-like contribution scores.
    /// @param round The FL round number.
    /// @param clientIds Array of client identifiers.
    /// @param rewardShares Array of reward amounts (in wei) for each client.
    function distributeRewards(
        uint256 round,
        uint256[] calldata clientIds,
        uint256[] calldata rewardShares
    ) external onlyAggregator {
        require(clientIds.length == rewardShares.length, "Arrays length mismatch");

        for (uint256 i = 0; i < clientIds.length; i++) {
            uint256 clientId = clientIds[i];
            uint256 rewardAmount = rewardShares[i];
            if (rewardAmount > 0 && clients[clientId].isRegistered) {
                clients[clientId].pendingRewards += rewardAmount;
                clients[clientId].totalRewardsEarned += rewardAmount;
                emit RewardDistributed(round, clientId, rewardAmount);
            }
        }
    }

    // ======================== Withdrawals ========================

    /// @notice Withdraw remaining stake. Requires reputation >= 50.
    function withdrawStake(uint256 clientId) external {
        ClientInfo storage client = clients[clientId];
        require(client.isRegistered, "Client not registered");
        require(client.reputation >= 50, "Reputation too low to withdraw");

        uint256 amount = client.stake;
        require(amount > 0, "No stake to withdraw");

        client.stake = 0;
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        emit StakeWithdrawn(clientId, amount);
    }

    /// @notice Withdraw accumulated rewards.
    function withdrawRewards(uint256 clientId) external {
        ClientInfo storage client = clients[clientId];
        uint256 amount = client.pendingRewards;
        require(amount > 0, "No pending rewards");

        client.pendingRewards = 0;
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        emit RewardWithdrawn(clientId, amount);
    }

    // ======================== Admin ========================

    /// @notice Set the aggregator address (only owner).
    function setAggregator(address _aggregator) external onlyOwner {
        require(_aggregator != address(0), "Invalid address");
        aggregator = _aggregator;
    }

    // ======================== View Functions ========================

    function getClientInfo(uint256 clientId) external view returns (ClientInfo memory) {
        return clients[clientId];
    }

    function getReputation(uint256 clientId) external view returns (uint256) {
        return clients[clientId].reputation;
    }

    function getStake(uint256 clientId) external view returns (uint256) {
        return clients[clientId].stake;
    }

    function getUpdates() external view returns (Update[] memory) {
        return updates;
    }

    function isRegistered(uint256 clientId) external view returns (bool) {
        return clients[clientId].isRegistered;
    }
}
