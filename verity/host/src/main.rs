use methods::{METHOD_ELF, METHOD_ID};
use risc0_zkvm::{default_prover, ExecutorEnv, InnerReceipt, Receipt};
use serde_json::json;
use std::{env, io};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("info") {
        println!("{}", json!({"protocol": "verity-risc0/v2", "image_id": METHOD_ID}));
        return Ok(());
    }
    let receipt: Receipt = match args.get(1).map(String::as_str) {
        Some("verify") => serde_json::from_reader(io::stdin().lock())?,
        Some("prove") if args.len() >= 4 => {
            let operation: u32 = args[2].parse()?;
            let numbers: Vec<u64> = args[3..].iter().map(|n| n.parse()).collect::<Result<_, _>>()?;
            let executor = ExecutorEnv::builder().write(&(operation, numbers))?.build()?;
            default_prover().prove(executor, METHOD_ELF)?.receipt
        }
        _ => return Err("Usage: host info | host verify (receipt on stdin) | host prove <operation> <numbers...>".into()),
    };
    if matches!(&receipt.inner, InnerReceipt::Fake(_)) {
        return Err("Development-mode receipts are not cryptographic proofs".into());
    }
    receipt.verify(METHOD_ID)?;
    let (operation, numbers, result): (u32, Vec<u64>, u64) = receipt.journal.decode()?;
    println!("{}", json!({"protocol": "verity-risc0/v2", "image_id": METHOD_ID,
        "proof_verified": true, "operation": operation, "numbers": numbers,
        "result": result, "receipt": receipt}));
    Ok(())
}
