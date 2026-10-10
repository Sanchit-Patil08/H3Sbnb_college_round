import { expect } from "chai";
import { network } from "hardhat";

const { ethers } = await network.connect();

describe("VerityAudit", function () {
  async function deployAudit() {
    const [owner, attacker] = await ethers.getSigners();

    const audit = await ethers.deployContract("VerityAudit");

    await audit.waitForDeployment();

    return { audit, owner, attacker };
  }

  const requestId = ethers.id("request-001");
  const inputHash = ethers.id("input-10-20-30");
  const programId = ethers.id("program-v1");
  const outputHash = ethers.id("output-60");

  it("allows the authorized verifier to record an audit", async function () {
    const { audit } = await deployAudit();

    await audit.recordAudit(
      requestId,
      inputHash,
      programId,
      outputHash
    );

    expect(await audit.requestExists(requestId)).to.equal(true);

    const record = await audit.audits(requestId);

    expect(record.inputHash).to.equal(inputHash);
    expect(record.programId).to.equal(programId);
    expect(record.outputHash).to.equal(outputHash);
    expect(record.verified).to.equal(true);
  });

  it("rejects unauthorized users", async function () {
    const { audit, attacker } = await deployAudit();

    await expect(
      audit.connect(attacker).recordAudit(
        requestId,
        inputHash,
        programId,
        outputHash
      )
    ).to.be.revertedWith("Unauthorized verifier");
  });

  it("rejects duplicate request IDs", async function () {
    const { audit } = await deployAudit();

    await audit.recordAudit(
      requestId,
      inputHash,
      programId,
      outputHash
    );

    await expect(
      audit.recordAudit(
        requestId,
        inputHash,
        programId,
        outputHash
      )
    ).to.be.revertedWith("Request already recorded");
  });
});
