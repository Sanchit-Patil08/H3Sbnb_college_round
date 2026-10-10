import { network } from "hardhat";

async function main() {
  const { ethers } = await network.create();

  const [deployer] = await ethers.getSigners();

  console.log("Deploying VerityAudit...");
  console.log("Deployer:", deployer.address);

  const audit = await ethers.deployContract("VerityAudit");

  await audit.waitForDeployment();

  const address = await audit.getAddress();

  console.log("VerityAudit deployed at:", address);
  console.log("Authorized verifier:", await audit.verifier());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
