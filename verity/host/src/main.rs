use methods::{METHOD_ELF, METHOD_ID};
use risc0_zkvm::{default_prover, ExecutorEnv};
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 3 {
        eprintln!("Usage: cargo run -- <operation> <numbers...>");
        eprintln!("Operations: 1=Sum, 2=Average, 3=Maximum, 4=Minimum");
        std::process::exit(1);
    }

    let operation: u32 = args[1]
        .parse()
        .expect("Invalid operation");

    let numbers: Vec<u32> = args[2..]
        .iter()
        .map(|x| x.parse::<u32>().expect("Invalid number"))
        .collect();

    if !(1..=4).contains(&operation) {
        eprintln!("Unsupported operation");
        std::process::exit(1);
    }

    let input = (operation, numbers.clone());

    let executor_env = ExecutorEnv::builder()
        .write(&input)
        .unwrap()
        .build()
        .unwrap();

    println!("Generating proof...");

    let receipt = default_prover()
        .prove(executor_env, METHOD_ELF)
        .unwrap()
        .receipt;

    receipt.verify(METHOD_ID).unwrap();

    let (proved_operation, proved_numbers, result):
        (u32, Vec<u32>, u64) = receipt.journal.decode().unwrap();

    assert_eq!(proved_operation, operation);
    assert_eq!(proved_numbers, numbers);

    println!("PROOF_VERIFIED=true");
    println!("OPERATION={}", proved_operation);
    println!("INPUT={:?}", proved_numbers);
    println!("RESULT={}", result);
}
