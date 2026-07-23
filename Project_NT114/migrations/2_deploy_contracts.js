const Reputation = artifacts.require("Reputation");
const StakingReputation = artifacts.require("StakingReputation");

module.exports = function (deployer) {
  deployer.deploy(Reputation);
  deployer.deploy(StakingReputation);
};
