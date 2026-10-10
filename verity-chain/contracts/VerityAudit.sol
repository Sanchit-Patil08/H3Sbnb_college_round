// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

contract VerityAudit {
    address public owner;
    address public verifier;

    struct Audit {
        bytes32 inputHash;
        bytes32 programId;
        bytes32 outputHash;
        uint256 timestamp;
    }

    mapping(bytes32 => Audit) public audits;
    mapping(bytes32 => bool) public requestExists;

    event AuditRecorded(
        bytes32 indexed requestId,
        bytes32 inputHash,
        bytes32 programId,
        bytes32 outputHash
    );

    constructor() {
        owner = msg.sender;
        verifier = msg.sender;
    }

    function recordAudit(
        bytes32 requestId,
        bytes32 inputHash,
        bytes32 programId,
        bytes32 outputHash
    ) external {
        require(msg.sender == verifier, "Unauthorized verifier");
        require(!requestExists[requestId], "Request already recorded");

        requestExists[requestId] = true;

        audits[requestId] = Audit({
            inputHash: inputHash,
            programId: programId,
            outputHash: outputHash,
            timestamp: block.timestamp
        });

        emit AuditRecorded(
            requestId,
            inputHash,
            programId,
            outputHash
        );
    }
}
