use risc0_zkvm::guest::env;

fn main() {
    let (operation, numbers): (u32, Vec<u32>) = env::read();

    assert!(!numbers.is_empty(), "Input cannot be empty");

    let result: u64 = match operation {
        1 => numbers.iter().map(|&n| n as u64).sum(),

        2 => {
            let sum: u64 = numbers.iter().map(|&n| n as u64).sum();
            sum / numbers.len() as u64
        }

        3 => *numbers.iter().max().unwrap() as u64,

        4 => *numbers.iter().min().unwrap() as u64,

        _ => panic!("Unsupported operation"),
    };

    env::commit(&(operation, numbers, result));
}
